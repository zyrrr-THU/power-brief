"""能源企业股价：腾讯行情公开接口（免 key）。获取最新价、涨跌幅、近 5 个交易日收盘价。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .util import http, log


def _num(s, default=None):
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def _kline(sess, code):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,6,qfq"
    try:
        d = sess.get(url, timeout=12).json()["data"][code]
        rows = d.get("qfqday") or d.get("day") or []
        return [round(_num(r[2], 0), 3) for r in rows][-6:]
    except Exception:  # noqa: BLE001
        return []


def fetch_stocks(conf):
    stocks = conf.get("stocks", [])
    if not stocks:
        return []
    sess = http()
    codes = ",".join(s["code"] for s in stocks)
    try:
        r = sess.get(f"https://qt.gtimg.cn/q={codes}", timeout=15)
        r.encoding = "gbk"
        text = r.text
    except Exception as e:  # noqa: BLE001
        log.warning("股价获取失败: %s", e)
        return []
    quotes = {}
    for line in text.split(";"):
        if "=" not in line:
            continue
        key, val = line.strip().split("=", 1)
        f = val.strip('"').split("~")
        if len(f) < 33:
            continue
        quotes[key.replace("v_", "")] = {
            "name": f[1], "price": _num(f[3]), "prev": _num(f[4]),
            "change": _num(f[31]), "pct": _num(f[32]), "time": f[30],
        }
    with ThreadPoolExecutor(max_workers=5) as ex:
        klines = dict(zip([s["code"] for s in stocks], ex.map(lambda s: _kline(sess, s["code"]), stocks)))
    out = []
    alert = float(conf.get("alert_pct", 5))
    for s in stocks:
        q = quotes.get(s["code"])
        if not q or q["price"] is None:
            log.warning("股价缺失: %s %s", s["code"], s.get("name"))
            continue
        trend = klines.get(s["code"], [])
        week_pct = None
        if len(trend) >= 2 and trend[0]:
            week_pct = round((q["price"] / trend[0] - 1) * 100, 2)
        out.append({
            "code": s["code"], "name": q["name"] or s.get("name", ""), "group": s.get("group", ""),
            "price": q["price"], "pct": q["pct"] or 0.0, "trend5": trend[-5:],
            "week_pct": week_pct, "alert": abs(q["pct"] or 0) >= alert,
            "market": "港股" if s["code"].startswith("hk") else "A股", "time": q["time"],
        })
    log.info("股价：取到 %d / %d 只", len(out), len(stocks))
    return out
