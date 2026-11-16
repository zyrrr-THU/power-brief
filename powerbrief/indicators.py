"""行业数据看板：碳价、国际油气、全社会用电量，以及从新闻中抽取的关键数字。

历史数据存 state/indicators.json：{指标名: {"unit", "source", "freq", "points": {日期或月份: 数值}}}
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import quote

from .util import STATE, http, log, read_json, write_json

FILE = STATE / "indicators.json"

# 网页侧栏默认展示的核心指标
CORE = ["全国碳市场收盘价", "布伦特原油", "全社会用电量累计同比", "美国天然气"]


def _gnews_items(query, days):
    url = f"https://news.google.com/rss/search?q={quote(query + f' when:{days}d')}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    r = http().get(url, timeout=20)
    r.raise_for_status()
    return [((it.findtext("title") or ""), it.findtext("link") or "")
            for it in ET.fromstring(r.content).findall("./channel/item")]


def _gnews_titles(query, days):
    return [t for t, _ in _gnews_items(query, days)]


CEA_DAILY_RX = re.compile(r"CEA】全国碳市场每日综合价格行情及成交信息(20\d{6})")
PAGE_PRICE_RX = re.compile(r"收盘价[^，。；\d]{0,12}?([\d.]+)\s*元")


def carbon_from_daily_pages(items, have, max_fetch=8):
    """碳排放交易网每日行情页：标题只有日期，价格在正文里。只抓还没有数据的日期。"""
    from .article import decode_gnews, extract  # noqa: PLC0415 避免循环导入

    pts = {}
    for title, link in items:
        m = CEA_DAILY_RX.search(title)
        if not m:
            continue
        d = f"{m[1][:4]}-{m[1][4:6]}-{m[1][6:]}"
        if d in have or d in pts or max_fetch <= 0:
            continue
        max_fetch -= 1
        try:
            url = decode_gnews(link)
            text, _ = extract(url, limit=5000) if url else ("", None)
            pm = PAGE_PRICE_RX.search(text)
            if pm:
                pts[d] = float(pm[1])
        except Exception as e:  # noqa: BLE001
            log.debug("碳价页面解析失败 %s: %s", d, e)
    return pts


def _infer_year(month, today):
    return today.year if month <= today.month else today.year - 1


CARBON_RX = re.compile(r"(\d{1,2})月(\d{1,2})日全国碳(?:排放权交易)?市场[^\d]{0,12}?收盘价\s*([\d.]+)\s*元")


def parse_carbon(titles, today):
    pts = {}
    for t in titles:
        for m in CARBON_RX.finditer(t):
            mo, d, v = int(m[1]), int(m[2]), float(m[3])
            try:
                pts[date(_infer_year(mo, today), mo, d).isoformat()] = v
            except ValueError:
                pass
    return pts


MONTH_RX = re.compile(r"(?<![-－—–~～至到前\d])(\d{1,2})月份?[，,]?\s*全社会用电量[^，。；]*?同比(增长|下降)(-?[\d.]+)%")
CUM_RX = re.compile(r"(?:1[-－—–~～至到](\d{1,2})月|前(\d{1,2})个?月|(前三季度)|(上半年)|(前三季))[，,]?\s*(?:我国)?全社会用电量"
                    r"[^，。；]*?同比(增长|下降)(-?[\d.]+)%")


REGIONS = ("北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建",
           "江西", "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海",
           "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门", "台湾", "省", "市", "区", "县", "州", "盟")


def _regional(text, start):
    """匹配位置前面 8 个字里出现地名，说明是地方数据而非全国。"""
    return any(r in text[max(0, start - 8):start] for r in REGIONS)


def parse_power_use(titles, today):
    month, cum = {}, {}
    for t in titles:
        for m in MONTH_RX.finditer(t):
            if _regional(t, m.start()):
                continue
            mo = int(m[1])
            v = float(m[3]) * (-1 if m[2] == "下降" else 1)
            month[f"{_infer_year(mo, today)}-{mo:02d}"] = v
        for m in CUM_RX.finditer(t):
            if _regional(t, m.start()):
                continue
            mo = int(m[1] or m[2] or (9 if (m[3] or m[5]) else 6))
            v = float(m[7]) * (-1 if m[6] == "下降" else 1)
            cum[f"{_infer_year(mo, today)}-{mo:02d}"] = v
    return month, cum


SINA = {"hf_OIL": ("布伦特原油", "美元/桶"), "hf_CL": ("WTI原油", "美元/桶"), "hf_NG": ("美国天然气", "美元/百万英热")}


def fetch_sina():
    out = {}
    r = http().get("https://hq.sinajs.cn/list=" + ",".join(SINA), timeout=15,
                   headers={"Referer": "https://finance.sina.com.cn"})
    for line in r.text.split(";"):
        m = re.search(r"hq_str_(\w+)=\"([^\"]*)\"", line)
        if not m or m[1] not in SINA or not m[2]:
            continue
        f = m[2].split(",")
        try:
            out[SINA[m[1]][0]] = (f[12], float(f[0]), SINA[m[1]][1])
        except (IndexError, ValueError):
            pass
    return out


def _put(store, name, unit, source, points, freq="day"):
    s = store.setdefault(name, {"unit": unit, "source": source, "freq": freq, "points": {}})
    s.update(unit=unit, source=source, freq=freq)
    s["points"].update({k: round(v, 4) for k, v in points.items()})
    # 每个指标最多保留 400 个点
    if len(s["points"]) > 400:
        s["points"] = dict(sorted(s["points"].items())[-400:])


def update_hard(store, today_s, extra_titles=()):
    """抓取硬数据并写入 store，返回成功的指标名列表。"""
    today = date.fromisoformat(today_s)
    ok = []
    first = "全国碳市场收盘价" not in store
    try:
        days = 30 if first else 5
        its = _gnews_items("全国碳市场 收盘价", days) + _gnews_items("今日碳价 CEA", days)
        pts = parse_carbon([t for t, _ in its], today)
        have = set((store.get("全国碳市场收盘价") or {}).get("points", {})) | set(pts)
        pts.update(carbon_from_daily_pages(its, have, 30 if first else 6))
        if pts:
            _put(store, "全国碳市场收盘价", "元/吨", "全国碳排放权交易市场每日收盘价（新闻报道）", pts)
            ok.append("全国碳市场收盘价")
    except Exception as e:  # noqa: BLE001
        log.warning("碳价获取失败：%s", e)
    try:
        titles = list(extra_titles) + _gnews_titles("全社会用电量 同比", 90 if "全社会用电量累计同比" not in store else 10)
        month, cum = parse_power_use(titles, today)
        if month:
            _put(store, "全社会用电量当月同比", "%", "国家能源局月度发布（新闻报道）", month, "month")
            ok.append("全社会用电量当月同比")
        if cum:
            _put(store, "全社会用电量累计同比", "%", "国家能源局月度发布（新闻报道）", cum, "month")
            ok.append("全社会用电量累计同比")
    except Exception as e:  # noqa: BLE001
        log.warning("用电量获取失败：%s", e)
    try:
        for name, (d, v, unit) in fetch_sina().items():
            _put(store, name, unit, "新浪财经 国际期货连续合约", {d: v})
            ok.append(name)
    except Exception as e:  # noqa: BLE001
        log.warning("油气价格获取失败：%s", e)
    return ok


def match_alias(name, aliases):
    for canon, keys in (aliases or {}).items():
        if any(k in name for k in keys):
            return canon
    return None


def apply_data_points(store, points, aliases, today_s, items):
    """AI 抽取的数字：能匹配别名的写入时间序列，其余作为“今日关键数字”返回。"""
    key_numbers = []
    for p in points or []:
        try:
            name, value = str(p["name"]).strip(), float(str(p["value"]).replace(",", ""))
        except (KeyError, TypeError, ValueError):
            continue
        unit = str(p.get("unit", "")).strip()
        idx = p.get("i")
        src = items[idx] if isinstance(idx, int) and 0 <= idx < len(items) else None
        when = str(p.get("date") or today_s)[:10]
        if not re.match(r"^20\d{2}-\d{2}(-\d{2})?$", when):
            when = today_s
        canon = match_alias(name, aliases)
        if canon:
            _put(store, canon, unit, "新闻报道（AI 摘录）", {when: value}, "month" if len(when) == 7 else "day")
        key_numbers.append({"name": name, "value": value, "unit": unit, "date": when, "series": canon,
                            "title": src["title"] if src else "", "url": src["url"] if src else ""})
    return key_numbers[:12]


def summary(store, limit_points=120):
    """生成给网页/推送用的摘要：最新值、上期值、变化、最近若干点。"""
    out = []
    for name, s in store.items():
        pts = sorted(s.get("points", {}).items())
        if not pts:
            continue
        latest_d, latest = pts[-1]
        prev = pts[-2][1] if len(pts) > 1 else None
        out.append({"name": name, "unit": s.get("unit", ""), "source": s.get("source", ""), "freq": s.get("freq", "day"),
                    "date": latest_d, "value": latest, "prev": prev,
                    "change": round(latest - prev, 4) if prev is not None else None,
                    "change_pct": round((latest / prev - 1) * 100, 2) if prev not in (None, 0) and s.get("unit") != "%" else None,
                    "series": pts[-limit_points:], "core": name in CORE})
    out.sort(key=lambda x: (not x["core"], CORE.index(x["name"]) if x["core"] else 0, x["name"]))
    return out


def load():
    return read_json(FILE, {})


def save(store):
    write_json(FILE, store)
