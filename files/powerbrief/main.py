"""主流程：抓取 → 原文 → 去重分类 → 股价/公告/数据 → 摘要 → 专题 → 生成网站数据 → 推送 → 发布。

用法（在 power-brief 目录下）：
  python -m powerbrief                 正常运行（当天已推送过、或定时任务已成功运行过会跳过）
  python -m powerbrief --force         今天已推送过也重新运行并推送
  python -m powerbrief --no-push       只生成，不推送、不发布
  python -m powerbrief --no-ai         本次强制用无 AI 模式
  python -m powerbrief --dry-run       只抓取并打印统计，不写文件、不推送
  python -m powerbrief --weekly        非周日也生成周回顾和专题解读
  python -m powerbrief --check         检查今天是否已成功推送，没有则发提醒（10:47 自动运行）
  python -m powerbrief --test-push     用最近一期简报测试推送渠道
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import announce, article, feedback, indicators, notify, process, render, status, topics, usage
from .sources import fetch_all
from .stocks import fetch_stocks
from .summarize import deep_dive, summarize
from .util import DATA, DOCS, ROOT, STATE, load_env, load_yaml, local_today, log, now_utc, read_json, \
    setup_logging, version, write_json

PUSH_LOG = STATE / "push_log.json"


def scheduled_done(today):
    """今天是否已有一次成功的定时运行。网页手动“只更新网页”的运行不算，之后的定时运行照常生成并推送。"""
    return any(r.get("date") == today and r.get("ok") and r.get("trigger") == "schedule"
               for r in read_json(status.RUNLOG, []))


POLICY_FILE = STATE / "policy.json"


def runner():
    return "github" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"


def fill_repo_defaults(cfg):
    """云端运行时，网页地址和反馈仓库没填就按仓库名自动推出（https://用户名.github.io/仓库名/）。"""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return
    owner, name = repo.split("/", 1)
    for k in ("publish", "feedback"):
        if not isinstance(cfg.get(k), dict):
            cfg[k] = {}
    if not cfg["publish"].get("site_url"):
        cfg["publish"]["site_url"] = f"https://{owner.lower()}.github.io/{name}/"
    if not cfg["feedback"].get("github_repo"):
        cfg["feedback"]["github_repo"] = repo


def publish(cfg, today):
    pub = cfg.get("publish", {})
    target = pub.get("target", "none")
    if target == "folder" and pub.get("folder_path"):
        dst = pub["folder_path"]
        shutil.copytree(DOCS, dst, dirs_exist_ok=True)
        log.info("网站已复制到 %s", dst)
    elif target == "github_pages" and runner() == "local" and pub.get("git_push", True):
        if not (ROOT / ".git").exists():
            log.warning("publish.target=github_pages 但本目录不是 git 仓库，跳过发布（见 README 第 4 节）")
            return
        cmds = [["git", "add", "docs", "state"],
                ["git", "commit", "-m", f"brief {today}"],
                ["git", "pull", "--rebase", "-X", "ours"],
                ["git", "push"]]
        for c in cmds:
            r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0 and c[1] != "commit":
                log.warning("git %s 失败：%s", c[1], (r.stderr or r.stdout)[:200])
                return
        log.info("已推送到 GitHub，Pages 约 1 分钟后更新")


def update_policy_history(today, cands, chosen_ids):
    """政策雷达：保存近 60 天的政策条目，返回 (今日政策, 近 60 天政策)。"""
    hist = read_json(POLICY_FILE, [])
    known = {p["id"] for p in hist}
    todays = []
    for it in cands:
        if not it.get("policy_type"):
            continue
        row = {"id": it["id"], "date": today, "title": it["title"], "url": it["url"], "origin": it["origin"],
               "policy_type": it["policy_type"], "deadline": it.get("deadline", ""),
               "summary": it.get("summary", "") or it.get("snippet", "")[:100], "in_brief": it["id"] in chosen_ids,
               "official": it["tier"] >= 3}
        todays.append(row)
        if row["id"] not in known:
            hist.append(row)
            known.add(row["id"])
        else:  # 同日重跑或 AI 补充了截止日期时更新
            for p in hist:
                if p["id"] == row["id"]:
                    p.update({k: v for k, v in row.items() if v and k != "date"})
    cutoff = (date.fromisoformat(today) - timedelta(days=60)).isoformat()
    hist = [p for p in hist if p["date"] >= cutoff]
    write_json(POLICY_FILE, hist)
    todays.sort(key=lambda r: (not r["official"], not r["in_brief"], r["policy_type"] != "征求意见"))
    return todays[:10], hist


def build(cfg, args, today):
    sources = load_yaml("sources.yaml").get("sources", [])
    glossary = load_yaml("glossary.yaml").get("terms", {})
    stocks_conf = load_yaml("stocks.yaml")
    topic_conf = load_yaml("topics.yaml").get("topics", {})
    notes = []  # 运行提示，附在推送末尾

    feedback.collect(cfg)
    weights = feedback.load_weights()

    items, stats = fetch_all(sources, cfg)
    log.info("共抓到 %d 条（%d 个来源）", len(items), len(stats))
    items = process.cluster(items)
    seen = process.load_seen()
    fresh = process.drop_seen(items, seen, today)
    log.info("合并同类后 %d 条，去掉往日已推送后 %d 条", len(items), len(fresh))
    cands = process.enrich(fresh, cfg, weights)

    # 股价、公告与抓原文互不依赖，放到后台同时进行（节省约 20 秒）
    bg = ThreadPoolExecutor(max_workers=2)
    fut_stocks = bg.submit(fetch_stocks, stocks_conf)
    fut_anns = bg.submit(announce.fetch_announcements, stocks_conf)

    # 原文：解码 Google 链接、抓正文、补日期；原本没日期、从正文页查到其实是旧文章的剔除，然后重新排序
    art = article.enrich_articles(cands, limit=int(cfg["ai"].get("max_candidates", 40)) + 10, workers=8)
    cutoff = now_utc() - timedelta(hours=cfg["run"].get("lookback_hours", 36) + 24)
    cands = [it for it in cands if not it.get("date_from_page") or datetime.fromisoformat(it["published"]) >= cutoff]
    cands = process.enrich(cands, cfg, weights)

    stocks = fut_stocks.result()
    anns, ann_raw = fut_anns.result()
    bg.shutdown()
    ind_store = indicators.load()
    ind_ok = indicators.update_hard(ind_store, today, [it["title"] for it in items])

    if args.dry_run:
        for it in cands[:30]:
            log.info("  %5.1f [%s%s] %s ｜%s", it["score"], it["category"],
                     "/" + it["policy_type"] if it.get("policy_type") else "", it["title"][:50], it["origin"])
        for a in anns:
            log.info("  公告 [%s] %s：%s", a["level"], a["name"], a["title"][:50])
        for s in indicators.summary(ind_store):
            log.info("  指标 %s = %s %s（%s，共 %d 点）", s["name"], s["value"], s["unit"], s["date"], len(s["series"]))
        return None

    st = topics.load()
    known_topics = topics.all_topics(topic_conf, st)
    res = summarize(cands, cfg, glossary, today, force_rule=args.no_ai,
                    topic_names=list(known_topics), prefs=feedback.prompt_hint(weights))
    if cfg["ai"].get("enabled") and res["mode"] == "rule" and not args.no_ai:
        notes.append("AI 解读不可用，今天为规则模式（查看日志中“跳过/失败”原因）")

    # 专题：AI 没给的按关键词补；写入时间线并标注往期
    topics.tag(res["items"], known_topics)
    topics.update(st, res["items"], today, set(topic_conf))
    topics.annotate(res["items"], st, today)

    key_numbers = indicators.apply_data_points(ind_store, res.get("data_points"), cfg.get("indicator_aliases"),
                                               today, res.get("pool") or cands)
    indicators.save(ind_store)

    # 股价异动关联当日新闻和公告
    for s in stocks:
        key = s["name"][:4]
        s["news"] = [it["id"] for it in res["items"] if key and key in it["title"]]
        s["anns"] = [a["id"] for a in anns if a.get("stock") == s["code"]]
    if len(stocks) < len(stocks_conf.get("stocks", [])):
        notes.append(f"股价只取到 {len(stocks)}/{len(stocks_conf.get('stocks', []))} 只")
    if ann_raw == 0 and stocks_conf.get("announcements", {}).get("enabled", True):
        notes.append("公告接口今天没有返回数据")

    chosen_ids = {it["id"] for it in res["items"]}
    # AI 只对入选条目给出 policy_type/deadline，回填到候选里
    by_id = {it["id"]: it for it in res["items"]}
    for it in cands:
        if it["id"] in by_id:
            it.update({k: by_id[it["id"]].get(k) for k in ("policy_type", "deadline", "summary") if by_id[it["id"]].get(k)})
    policy_today, policy_hist = update_policy_history(today, cands, chosen_ids)

    alerts = render.source_alerts(today, stats)
    if alerts:
        notes.append("连续 3 天无数据的来源：" + "、".join(alerts))

    brief = {
        "version": version(), "date": today, "mode": res["mode"], "provider": res["provider"],
        "highlights": res["highlights"], "concept": res["concept"], "stocks": stocks,
        "items": [render.public_item(it) for it in res["items"]],
        "policy": policy_today, "announcements": anns, "key_numbers": key_numbers,
        "indicators": [{k: v for k, v in s.items() if k != "series"} | {"series": s["series"][-30:]}
                       for s in indicators.summary(ind_store) if s["core"]],
        "source_stats": stats, "source_alerts": alerts, "notes": notes,
        "article_stats": art, "site_url": cfg.get("publish", {}).get("site_url", ""),
    }
    if date.fromisoformat(today).weekday() == 6 or args.weekly:
        brief["weekly"] = render.weekly_review(today, brief["items"], stocks)
        hot, entries = topics.weekly_hot(st, today)
        if hot:
            dd = deep_dive(cfg, hot, entries)
            brief["weekly"]["topic"] = {"name": hot, "entries": entries[-15:],
                                        "deep_dive": dd["text"] if dd else ""}
    topics.save(st)
    render.write_day(brief)
    render.write_glossary(glossary)
    render.write_extra("indicators", {"indicators": indicators.summary(ind_store)})
    render.write_extra("topics", topics.export(st))
    render.write_extra("policy", {"policy": sorted(policy_hist, key=lambda p: p["date"], reverse=True)})
    rep = usage.report(cfg)
    today_use = next((d for d in rep["days"] if d["date"] == today), None)
    brief["usage"] = {k: today_use[k] for k in ("total", "input", "output", "cost_usd", "calls")} if today_use else {}
    render.write_day(brief)
    render.write_extra("usage", rep)
    render.write_extra("weights", feedback.load_weights() | {"repo": cfg.get("feedback", {}).get("github_repo", "")})
    process.mark_seen(res["items"], seen, today)
    log.info("简报已生成：%d 条，政策 %d 条，公告 %d 条，指标 %d 个，模式 %s%s", len(brief["items"]), len(policy_today),
             len(anns), len(ind_store), brief["mode"], f"（{brief['provider']}）" if brief["provider"] else "")
    return brief


def finish(info):
    """写运行记录和网页设置页用的生效配置（失败也要记录，网页上能看到原因）。"""
    try:
        status.record_run(info)
        status.export_settings()
    except Exception as e:  # noqa: BLE001 记录失败不影响主流程
        log.warning("写运行记录失败：%s", e)


def check(cfg, today, title_prefix):
    """监控：今天还没成功推送就发提醒。"""
    pl = read_json(PUSH_LOG, {})
    if pl.get(today):
        log.info("检查：今天 %s 已成功推送", today)
        return
    data_ok = (DATA / f"{today}.json").exists()
    msg = ("今天的简报已生成但推送失败，请在网页“运行记录”页查看原因。" if data_ok else
           "今天的简报还没有生成：云端定时任务可能延迟或出错，请在网页“运行记录”页或 GitHub Actions 查看。")
    notify.alert(cfg, f"⚠ {title_prefix} {today[5:]} 未送达", msg)


def cli():
    ap = argparse.ArgumentParser(description="PowerBrief 电力行业每日简报")
    ap.add_argument("--force", action="store_true", help="忽略“今天已推送”和运行方式检查")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--weekly", action="store_true", help="非周日也生成周回顾")
    ap.add_argument("--check", action="store_true", help="检查今天是否已推送，未推送则提醒")
    ap.add_argument("--test-push", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    load_env()
    cfg = load_yaml("config.yaml")
    fill_repo_defaults(cfg)
    today =local_today(cfg["run"].get("timezone_offset_hours", 8))
    log.info("PowerBrief v%s  日期 %s  运行环境 %s", version(), today, runner())
    prefix = cfg.get("notify", {}).get("title_prefix", "电力日报")
    title = f"{prefix} {today[5:]}"

    if args.check:
        if cfg["run"].get("mode", "local") == runner() or args.force:
            check(cfg, today, prefix)
        return

    if args.test_push:
        latest = sorted(DATA.glob("20*.json"))
        if not latest:
            log.error("还没有任何简报，请先运行一次")
            sys.exit(1)
        brief = render.load_day(latest[-1].stem)
        brief["site_url"] = cfg.get("publish", {}).get("site_url", "")
        notify.notify_all(cfg, brief, title + "（测试）")
        return

    if not args.force and not args.dry_run:
        if cfg["run"].get("mode", "local") != runner():
            log.info("config.yaml 设置由 %s 运行，当前在 %s，跳过（用 --force 强制）", cfg["run"]["mode"], runner())
            return
        if read_json(PUSH_LOG, {}).get(today) and not args.no_push:
            log.info("今天 %s 已推送过，跳过（用 --force 重跑）", today)
            return
        if scheduled_done(today):
            log.info("今天 %s 的定时任务已成功运行过，跳过（每天设了几个备用时段，先到的那次生成）", today)
            return

    try:
        brief = build(cfg, args, today)
    except Exception as e:  # noqa: BLE001 运行失败时主动告警
        tb = traceback.format_exc()
        log.error("运行失败：%s\n%s", e, tb)
        err = f"{type(e).__name__}: {str(e)[:300]}"
        if not args.dry_run:
            finish({"date": today, "ok": False, "error": err})
        if not args.no_push and not args.dry_run:
            where = status.github_run()["run_url"] or "logs/ 当月日志"
            notify.alert(cfg, f"⚠ {prefix} {today[5:]} 运行失败", f"错误：{err}\n\n详细信息：{where}")
        sys.exit(1)
    if brief is None:
        return
    run_info = {"date": today, "ok": True, "items": len(brief["items"]), "mode": brief["mode"],
                "provider": brief.get("provider") or "", "tokens": (brief.get("usage") or {}).get("total", 0),
                "notes": brief.get("notes", [])[:5], "push": "未推送（只更新网页）" if args.no_push else ""}
    (STATE / "last_push_preview.html").write_text(notify.preview_html(brief, title), encoding="utf-8")
    if args.no_push:
        log.info("--no-push：不推送、不发布。推送效果预览：state/last_push_preview.html")
        finish(run_info)
        return
    results = notify.notify_all(cfg, brief, title)
    publish(cfg, today)
    # 只有至少一个渠道成功（或根本没配渠道）才记为“今天已推送”，全部失败时下次运行会重试
    if not results or "ok" in results.values():
        pl = read_json(PUSH_LOG, {})
        pl[today] = results or {"none": "未配置推送渠道"}
        write_json(PUSH_LOG, dict(sorted(pl.items())[-60:]))
    else:
        log.error("所有推送渠道都失败了，今天会在下次运行时重试")
    run_info["push"] = "、".join(f"{k}:{'成功' if v == 'ok' else '失败'}" for k, v in results.items()) or "未配置推送渠道"
    finish(run_info)


if __name__ == "__main__":
    cli()
