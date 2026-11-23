"""写出网站数据：每日 JSON + 同内容的 .js（本地双击 index.html 也能读取）、索引、术语表、周回顾。"""
from __future__ import annotations

import json
from datetime import date, timedelta

from .util import DATA, read_json, write_json

SCHEMA_VERSION = 1


def _write_js(path, callback, obj):
    path.write_text(f"PB.{callback}({json.dumps(obj, ensure_ascii=False)});\n", encoding="utf-8")


def public_item(it):
    keep = ("id", "title", "url", "source", "origin", "published", "category", "score", "summary",
            "why", "terms", "watch_hit", "coverage", "also", "importance", "lang", "policy_type", "deadline",
            "topics", "topic_info")
    return {k: it.get(k) for k in keep}


def load_day(day):
    """读取历史简报，缺字段补默认值，保证旧数据始终能用。"""
    d = read_json(DATA / f"{day}.json", None)
    if not d:
        return None
    d.setdefault("highlights", [])
    d.setdefault("stocks", [])
    d.setdefault("source_stats", {})
    for k in ("policy", "announcements", "key_numbers", "indicators", "notes"):
        d.setdefault(k, [])
    for it in d.get("items", []):
        it.setdefault("terms", [])
        it.setdefault("topics", [])
        it.setdefault("topic_info", [])
        it.setdefault("policy_type", "")
        it.setdefault("category", "综合")
        it.setdefault("summary", "")
        it.setdefault("why", "")
    d.setdefault("items", [])
    return d


def weekly_review(today, current_items, stocks, days=7):
    """周日生成：本周得分最高的 10 条 + 股价周涨跌。"""
    pool = list(current_items)
    t = date.fromisoformat(today)
    for i in range(1, days):
        d = load_day((t - timedelta(days=i)).isoformat())
        if d:
            pool += d["items"]
    seen, top = set(), []
    for it in sorted(pool, key=lambda x: -(x.get("score") or 0)):
        if it["title"] in seen:
            continue
        seen.add(it["title"])
        top.append({"title": it["title"], "url": it["url"], "category": it.get("category", "综合")})
        if len(top) >= 10:
            break
    cats = {}
    for it in pool:
        cats[it.get("category", "综合")] = cats.get(it.get("category", "综合"), 0) + 1
    movers = sorted([s for s in stocks if s.get("week_pct") is not None], key=lambda s: -abs(s["week_pct"]))[:5]
    return {"top": top, "category_count": cats,
            "stock_week": [{"name": s["name"], "week_pct": s["week_pct"]} for s in movers]}


def write_day(brief):
    DATA.mkdir(parents=True, exist_ok=True)
    brief = dict(brief, schema=SCHEMA_VERSION)
    write_json(DATA / f"{brief['date']}.json", brief)
    _write_js(DATA / f"{brief['date']}.js", "onDay", brief)
    rebuild_index()


def rebuild_index():
    days = []
    for p in sorted(DATA.glob("20*.json"), reverse=True):
        d = load_day(p.stem)
        if not d:
            continue
        days.append({
            "date": d["date"], "mode": d.get("mode", "rule"), "count": len(d["items"]),
            "headline": (d["highlights"] or [""])[0],
            # [id, 标题, 类别, 摘要, 来源, 关注命中, 分数]：网页的搜索、趋势、关注页都用它；旧网页只读前 4 项
            "items": [[it["id"], it["title"], it["category"], it.get("summary", "")[:60], it.get("origin", ""),
                       list(it.get("watch_hit") or []), round(float(it.get("score") or 0), 1)] for it in d["items"]],
        })
    idx = {"days": days}
    write_json(DATA / "index.json", idx)
    _write_js(DATA / "index.js", "onIndex", idx)


def write_extra(name, obj):
    """写出网页其他页面用的数据：indicators / topics / policy / weights。"""
    DATA.mkdir(parents=True, exist_ok=True)
    write_json(DATA / f"{name}.json", obj)
    _write_js(DATA / f"{name}.js", "onExtra_" + name, obj)


def write_glossary(glossary):
    DATA.mkdir(parents=True, exist_ok=True)
    _write_js(DATA / "glossary.js", "onGlossary", glossary)


def _source_bad(name, stats, raw):
    """真正的故障：抓取失败（-1），或列表页一条都没抓到。抓到了但都被“电力相关”关键词过滤掉的不算。
    旧数据没有原始条数（raw）时，只把失败算作故障；搜索类来源不记录原始条数，也只看失败。"""
    v = stats.get(name)
    if v is None:          # 当天没有这个来源（未启用）
        return False
    if v < 0:
        return True
    return raw is not None and raw.get(name, 1) == 0


def source_alerts(today, stats, days=3, raw=None):
    """某来源连续 days 天故障时提醒检查。"""
    t = date.fromisoformat(today)
    hist = [(stats, raw)]
    for i in range(1, days):
        d = load_day((t - timedelta(days=i)).isoformat())
        if not d or d.get("source_stats") is None:
            return []
        hist.append((d["source_stats"], d.get("source_raw")))
    return [name for name in stats if all(_source_bad(name, st, rw) for st, rw in hist)]