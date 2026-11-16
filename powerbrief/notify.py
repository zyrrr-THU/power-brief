"""推送渠道：PushPlus、Server酱（微信）、企业微信、飞书、钉钉、Bark、Telegram、邮件。

每个渠道的密钥从环境变量读取（见 .env.example）。某个渠道失败不影响其他渠道。
"""
from __future__ import annotations

import html
import smtplib
from email.header import Header
from email.mime.text import MIMEText

from .util import env, http, log

CAT_ICON = {"政策法规": "📜", "市场与电价": "💹", "新能源与储能": "🔋", "电网与技术": "🔌",
            "企业动态": "🏢", "国际": "🌍", "综合": "📰"}


def _pct(p):
    return f"{'+' if p > 0 else ''}{p:.2f}%"


def _by_cat(items):
    groups = {}
    for it in items:
        groups.setdefault(it["category"], []).append(it)
    order = list(CAT_ICON)
    return sorted(groups.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)


def _fmt_num(v):
    return f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else str(v)


def _ind_line(x):
    ch = ""
    if x.get("change") is not None:
        sign = "+" if x["change"] > 0 else ""
        ch = f"（{sign}{_fmt_num(x['change'])}{'个百分点' if x['unit'] == '%' else ''}）"
    return f"{x['name']} {_fmt_num(x['value'])}{x['unit']}{ch}"


def build_html(b):
    e = html.escape
    if b.get("alert"):
        return f"<p>{e(b['alert'])}</p>"
    p = [f"<h3>今日三件事</h3><ol>" + "".join(f"<li>{e(h)}</li>" for h in b["highlights"]) + "</ol>"]
    if b.get("policy"):
        rows = []
        for x in b["policy"][:6]:
            dl = f" <b style='color:#b26a00'>截止 {e(x['deadline'])}</b>" if x.get("deadline") else ""
            rows.append(f"<li>[{e(x['policy_type'])}] <a href='{e(x['url'])}'>{e(x['title'])}</a>{dl}"
                        f" <small style='color:#888'>{e(x['origin'])}</small></li>")
        p.append("<h3>📜 政策雷达</h3><ul>" + "".join(rows) + "</ul>")
    if b.get("indicators"):
        p.append("<h3>📊 关键数据</h3><p style='font-size:13px'>" +
                 "<br>".join(e(_ind_line(x)) + f" <small style='color:#888'>{e(x['date'])}</small>"
                             for x in b["indicators"]) + "</p>")
    if b.get("stocks"):
        rows = "".join(
            f"<tr><td>{e(s['name'])}</td><td align=right>{s['price']:g}</td>"
            f"<td align=right style='color:{'#d03030' if s['pct'] > 0 else '#1a9a4a' if s['pct'] < 0 else '#666'}'>"
            f"{'⚠️' if s['alert'] else ''}{_pct(s['pct'])}</td></tr>" for s in b["stocks"])
        p.append(f"<h3>能源股收盘</h3><table style='font-size:13px;border-collapse:collapse'>{rows}</table>")
    if b.get("announcements"):
        p.append("<h3>🏛 公司公告</h3><ul>" + "".join(
            f"<li>{e(a['name'])}：<a href='{e(a['url'])}'>{e(a['title'])}</a></li>" for a in b["announcements"][:5])
            + "</ul>")
    for cat, items in _by_cat(b["items"]):
        p.append(f"<h3>{CAT_ICON.get(cat, '')} {e(cat)}</h3>")
        for it in items:
            star = "★ " if it.get("watch_hit") else ""
            s = f"<p><b>{star}<a href='{e(it['url'])}'>{e(it['title'])}</a></b><br>"
            if it.get("summary"):
                s += f"{e(it['summary'])}<br>"
            if it.get("why"):
                s += f"<i>👉 {e(it['why'])}</i><br>"
            for t in it.get("terms", []):
                s += f"<small>📖 {e(t['term'])}：{e(t['explain'])}</small><br>"
            thread = "".join(f" 🧵{e(ti['name'])}" + (f"·此前{ti['prior']}条" if ti.get("prior") else "")
                             for ti in it.get("topic_info") or [])
            s += f"<small style='color:#888'>{e(it['origin'])}{thread}</small></p>"
            p.append(s)
    if b.get("key_numbers"):
        p.append("<h3>🔢 新闻中的关键数字</h3><ul style='font-size:13px'>" + "".join(
            f"<li>{e(k['name'])}：{_fmt_num(k['value'])}{e(k['unit'])}</li>" for k in b["key_numbers"][:8]) + "</ul>")
    if b.get("concept"):
        c = b["concept"]
        p.append(f"<h3>💡 今日学一个概念：{e(c['term'])}</h3><p>{e(c['explain'])}</p>")
    if b.get("weekly"):
        w = b["weekly"]
        p.append("<h3>📅 本周回顾</h3><ol>" + "".join(
            f"<li><a href='{e(x['url'])}'>{e(x['title'])}</a></li>" for x in w["top"]) + "</ol>")
        tp = w.get("topic")
        if tp:
            body = e(tp.get("deep_dive") or "").replace("\n", "<br>") or "<br>".join(
                f"{e(x['date'][5:])} {e(x['title'])}" for x in tp["entries"])
            p.append(f"<h3>🧵 本周专题：{e(tp['name'])}</h3><p style='font-size:14px'>{body}</p>")
    if b.get("notes"):
        p.append("<p style='color:#b26a00;font-size:12px'>⚠ 运行提示：" + "；".join(e(n) for n in b["notes"]) + "</p>")
    if b.get("site_url"):
        p.append(f"<p><a href='{e(b['site_url'])}'>👉 打开完整简报网页（归档、搜索、收藏）</a></p>")
    return "".join(p)


def build_md(b, compact=False, limit=None):
    if b.get("alert"):
        return b["alert"]
    lines = ["**今日三件事**"] + [f"{i}. {h}" for i, h in enumerate(b["highlights"], 1)]
    if b.get("policy"):
        lines += ["", "**📜 政策雷达**"] + [
            f"- [{x['policy_type']}] [{x['title']}]({x['url']})" + (f" 截止{x['deadline']}" if x.get("deadline") else "")
            for x in b["policy"][: (3 if compact else 6)]]
    if b.get("indicators"):
        lines += ["", "**📊 数据** " + " ｜ ".join(_ind_line(x) for x in b["indicators"])]
    if b.get("stocks"):
        movers = sorted(b["stocks"], key=lambda s: -abs(s["pct"]))[: (5 if compact else 15)]
        lines += ["", "**能源股** " + " ｜ ".join(f"{s['name']} {_pct(s['pct'])}" for s in movers)]
    if b.get("announcements"):
        lines += ["", "**🏛 公告**"] + [f"- {a['name']}：[{a['title']}]({a['url']})"
                                        for a in b["announcements"][: (3 if compact else 5)]]
    for cat, items in _by_cat(b["items"]):
        lines += ["", f"**{CAT_ICON.get(cat, '')} {cat}**"]
        for it in items:
            star = "★" if it.get("watch_hit") else ""
            lines.append(f"- {star}[{it['title']}]({it['url']})")
            if not compact and it.get("summary"):
                lines.append(f"  {it['summary']}" + (f" 👉{it['why']}" if it.get("why") else ""))
    if b.get("concept"):
        lines += ["", f"**💡 {b['concept']['term']}**：{b['concept']['explain']}"]
    tp = (b.get("weekly") or {}).get("topic")
    if tp and tp.get("deep_dive") and not compact:
        lines += ["", f"**🧵 本周专题：{tp['name']}**", tp["deep_dive"]]
    if b.get("notes"):
        lines += ["", "⚠ " + "；".join(b["notes"])]
    if b.get("site_url"):
        lines += ["", f"[👉 完整简报]({b['site_url']})"]
    text = "\n".join(lines)
    if limit and len(text.encode("utf-8")) > limit:
        tail = f"\n\n…更多见完整简报 {b.get('site_url', '')}"
        while len((text + tail).encode("utf-8")) > limit:
            text = text[: int(len(text) * 0.9)]
        text = text.rsplit("\n", 1)[0] + tail
    return text


def build_text(b, limit=None):
    if b.get("alert"):
        return b["alert"][:limit] if limit else b["alert"]
    lines = [f"{i}. {h}" for i, h in enumerate(b["highlights"], 1)]
    lines.append(f"共 {len(b['items'])} 条新闻")
    if b.get("site_url"):
        lines.append(b["site_url"])
    text = "\n".join(lines)
    return text[:limit] if limit else text


# —— 各渠道 ——

def _check(r):
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r


def send_pushplus(title, b):
    token = env("PUSHPLUS_TOKEN")
    if not token:
        raise RuntimeError("未设置 PUSHPLUS_TOKEN")
    r = _check(http().post("https://www.pushplus.plus/send", timeout=20,
                           json={"token": token, "title": title, "content": build_html(b), "template": "html"}))
    if r.json().get("code") != 200:
        raise RuntimeError(r.text[:200])


def send_serverchan(title, b):
    key = env("SERVERCHAN_SENDKEY")
    if not key:
        raise RuntimeError("未设置 SERVERCHAN_SENDKEY")
    host = f"https://{key.split('t')[0]}.push.ft07.com" if key.startswith("sctp") else "https://sctapi.ftqq.com"
    _check(http().post(f"{host}/{key}.send", timeout=20, data={"title": title, "desp": build_md(b, limit=30000)}))


def send_wecom(title, b):
    hook = env("WECOM_WEBHOOK")
    if not hook:
        raise RuntimeError("未设置 WECOM_WEBHOOK")
    md = f"## {title}\n" + build_md(b, compact=True, limit=4000)
    r = _check(http().post(hook, timeout=20, json={"msgtype": "markdown", "markdown": {"content": md}}))
    if r.json().get("errcode", 0) != 0:
        raise RuntimeError(r.text[:200])


def send_dingtalk(title, b):
    hook = env("DINGTALK_WEBHOOK")
    if not hook:
        raise RuntimeError("未设置 DINGTALK_WEBHOOK")
    md = f"## {title}\n" + build_md(b, compact=True, limit=18000)
    r = _check(http().post(hook, timeout=20, json={"msgtype": "markdown", "markdown": {"title": title, "text": md}}))
    if r.json().get("errcode", 0) != 0:
        raise RuntimeError(r.text[:200])


def send_feishu(title, b):
    hook = env("FEISHU_WEBHOOK")
    if not hook:
        raise RuntimeError("未设置 FEISHU_WEBHOOK")
    card = {"header": {"title": {"tag": "plain_text", "content": title}},
            "elements": [{"tag": "markdown", "content": build_md(b, compact=True, limit=25000)}]}
    r = _check(http().post(hook, timeout=20, json={"msg_type": "interactive", "card": card}))
    if r.json().get("code", 0) != 0:
        raise RuntimeError(r.text[:200])


def send_bark(title, b):
    key = env("BARK_KEY")
    if not key:
        raise RuntimeError("未设置 BARK_KEY")
    server = env("BARK_SERVER", "https://api.day.app").rstrip("/")
    body = {"title": title, "body": build_text(b, 900), "group": "PowerBrief", "device_key": key}
    if b.get("site_url"):
        body["url"] = b["site_url"]
    _check(http().post(f"{server}/push", timeout=20, json=body))


def send_telegram(title, b):
    tok, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        raise RuntimeError("未设置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    text = f"*{title}*\n" + build_md(b, compact=True, limit=3800).replace("**", "*")
    _check(http().post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=20,
                       json={"chat_id": chat, "text": text, "parse_mode": "Markdown",
                             "disable_web_page_preview": True}))


def send_email(title, b):
    host, user, pwd, to = env("SMTP_HOST"), env("SMTP_USER"), env("SMTP_PASSWORD"), env("EMAIL_TO")
    if not (host and user and pwd and to):
        raise RuntimeError("SMTP_HOST / SMTP_USER / SMTP_PASSWORD / EMAIL_TO 未填全")
    msg = MIMEText(f"<div style='max-width:680px;font-family:sans-serif'>{build_html(b)}</div>", "html", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"], msg["To"] = user, to
    with smtplib.SMTP_SSL(host, int(env("SMTP_PORT", "465")), timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())


CHANNELS = {"pushplus": send_pushplus, "serverchan": send_serverchan, "wecom": send_wecom,
            "dingtalk": send_dingtalk, "feishu": send_feishu, "bark": send_bark,
            "telegram": send_telegram, "email": send_email}


def alert(cfg, title, message):
    """运行告警：用同样的渠道发一条简短提醒。"""
    b = {"alert": message, "highlights": [], "items": [], "stocks": [], "concept": None, "site_url": ""}
    for ch in cfg.get("notify", {}).get("channels", []) or []:
        fn = CHANNELS.get(ch)
        if not fn:
            continue
        try:
            fn(title, b)
            log.info("告警已发送：%s", ch)
        except Exception as e:  # noqa: BLE001
            log.warning("告警发送失败 %s：%s", ch, str(e)[:120])


def notify_all(cfg, brief, title):
    results = {}
    for ch in cfg.get("notify", {}).get("channels", []) or []:
        fn = CHANNELS.get(ch)
        if not fn:
            log.warning("未知推送渠道 %s", ch)
            continue
        try:
            fn(title, brief)
            results[ch] = "ok"
            log.info("推送成功：%s", ch)
        except Exception as e:  # noqa: BLE001
            results[ch] = str(e)[:120]
            log.warning("推送失败 %s：%s", ch, str(e)[:200])
    return results


def preview_html(brief, title):
    """把推送内容存成本地 HTML，便于查看推送效果。"""
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{html.escape(title)}</title><body style='max-width:680px;margin:auto;padding:12px;"
            f"font-family:sans-serif'><h2>{html.escape(title)}</h2>{build_html(brief)}</body>")
