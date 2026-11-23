"""新闻抓取：Google 新闻搜索 RSS、标准 RSS、网站列表页。每个来源失败互不影响。"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .util import http, log, now_utc

CN = re.compile(r"[一-鿿]")


def _item(title, url, src, published=None, snippet="", origin=""):
    return {
        "title": re.sub(r"\s+", " ", title).strip(),
        "url": url,
        "source": src["name"],
        "origin": origin or src["name"],
        "tier": int(src.get("tier", 1)),
        "lang": src.get("lang", "zh"),
        "published": published.astimezone(timezone.utc).isoformat() if published else None,
        "snippet": snippet.strip(),
        "policy_src": bool(src.get("policy")),
    }


def _parse_date(text):
    if not text:
        return None
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _strip_html(s):
    return BeautifulSoup(s or "", "html.parser").get_text(" ", strip=True)


def fetch_gnews(src, sess, lookback_hours):
    days = max(1, math.ceil(lookback_hours / 24))
    q = f'{src["query"]} when:{days}d'
    if src.get("lang") == "en":
        loc = "hl=en-US&gl=US&ceid=US:en"
    else:
        loc = "hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    url = f"https://news.google.com/rss/search?q={quote(q)}&{loc}"
    r = sess.get(url, timeout=20)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).findall("./channel/item"):
        title = it.findtext("title") or ""
        origin = it.findtext("source") or ""
        if origin and title.endswith(" - " + origin):
            title = title[: -len(origin) - 3]
        out.append(_item(title, it.findtext("link"), src, _parse_date(it.findtext("pubDate")), "", origin))
    return out


def fetch_rss(src, sess, lookback_hours):
    r = sess.get(src["url"], timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = lambda name: next((c for c in it if c.tag.split("}")[-1] == name), None)
        t, l = get("title"), get("link")
        link = (l.get("href") or l.text) if l is not None else ""
        d = get("pubDate") or get("published") or get("updated")
        desc = get("description") or get("summary")
        out.append(_item(t.text if t is not None else "", link, src,
                         _parse_date(d.text if d is not None else None),
                         _strip_html(desc.text if desc is not None else "")[:300]))
    return out


DATE_IN_URL = re.compile(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})")
DATE_IN_TEXT = re.compile(r"(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})")


def _date_from(url, context):
    for rx, s in ((DATE_IN_URL, url), (DATE_IN_TEXT, context)):
        m = rx.search(s or "")
        if m:
            try:
                return datetime(int(m[1]), int(m[2]), int(m[3]), 12, tzinfo=timezone(timedelta(hours=8)))
            except ValueError:
                pass
    return None


def fetch_html_list(src, sess, lookback_hours):
    r = sess.get(src["url"], timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")
    need = src.get("link_contains")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        title = a.get("title") or a.get_text(" ", strip=True)
        url = urljoin(src["url"], a["href"])
        if len(title) < 8 or not CN.search(title) or url in seen:
            continue
        if need and need not in url:
            continue
        if not need and urlparse(url).netloc != urlparse(src["url"]).netloc:
            continue
        seen.add(url)
        ctx = a.parent.get_text(" ", strip=True) if a.parent else ""
        out.append(_item(title, url, src, _date_from(url, ctx)))
    return out


def fetch_nea_json(src, sess, lookback_hours):
    """国家能源局栏目数据（网站前端用的 ds_<id>.json）。"""
    r = sess.get(f"https://www.nea.gov.cn/ds_{src['ds']}.json", timeout=20)
    r.raise_for_status()
    out = []
    for it in r.json().get("datasource", []):
        title = _strip_html(it.get("title") or it.get("showTitle") or "")
        link = it.get("publishUrl") or ""
        m = re.search(r"href='([^']+)'", it.get("showTitle") or "")
        if m:
            link = m.group(1)
        if link and not link.startswith("http"):
            link = urljoin("https://www.nea.gov.cn/", link)
        pub = None
        if it.get("publishTime"):
            try:
                pub = datetime.strptime(it["publishTime"][:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone(timedelta(hours=8)))
            except ValueError:
                pass
        out.append(_item(title, link, src, pub, _strip_html(it.get("summary") or "")[:300]))
    return out


FETCHERS = {"gnews": fetch_gnews, "rss": fetch_rss, "html_list": fetch_html_list, "nea_json": fetch_nea_json}

POLICY_TYPES = [
    ("征求意见", ("征求意见", "公开征求", "意见稿")),
    ("政策解读", ("解读", "答记者问", "一图读懂", "专家")),
    ("正式文件", ("通知", "办法", "规定", "意见", "方案", "规划", "细则", "公告", "批复", "复函", "印发", "条例", "指南")),
]


def policy_type(title):
    for name, kws in POLICY_TYPES:
        if any(k in title for k in kws):
            return name
    return ""


def expand_sources(sources, cfg):
    """根据 config.policy_provinces 自动加上各省政策搜索。"""
    out = list(sources)
    for p in cfg.get("policy_provinces", []) or []:
        out.append({"name": f"政策·{p}", "type": "gnews", "tier": 2, "policy": True,
                    "query": f"{p} (发改委 OR 能源局 OR 电力交易中心) 电力 (通知 OR 征求意见 OR 方案 OR 办法)"})
    return out


def relevant(title, keywords):
    t = title.lower()
    return any(k.lower() in t for k in keywords)


# 最近一次抓取的附加信息：raw = {来源名: 过滤前抓到的条数}（只记列表页/RSS 等；搜索类 0 条是正常的，不记录）
LAST = {"raw": {}}


def fetch_all(sources, cfg):
    """返回 (新闻列表, {来源名: 条数})。"""
    lookback = cfg["run"].get("lookback_hours", 36)
    cutoff = now_utc() - timedelta(hours=lookback)
    rel_kw = cfg.get("relevance_keywords", [])
    sess = http()

    def one(src):
        try:
            items = FETCHERS[src["type"]](src, sess, lookback)
        except Exception as e:  # noqa: BLE001 单个来源失败不影响整体
            log.warning("来源失败 %s: %s", src["name"], str(e)[:120])
            return src["name"], None
        kept = []
        # 政策类来源更新慢，可单独设置 max_age_days（默认 14 天），靠跨日去重避免重复
        src_cutoff = now_utc() - timedelta(days=src["max_age_days"]) if src.get("max_age_days") else             (now_utc() - timedelta(days=14) if src.get("policy") and src["type"] != "gnews" else cutoff)
        for it in items:
            if not it["title"] or not it["url"]:
                continue
            if it["published"] and datetime.fromisoformat(it["published"]) < src_cutoff:
                continue
            # 中文来源默认都做相关性过滤（filter: none 可关闭），英文来源只在 filter: power 时过滤
            flt = src.get("filter", "power" if src.get("lang", "zh") == "zh" else "none")
            if flt == "power" and not relevant(it["title"], rel_kw):
                continue
            kept.append(it)
        log.info("来源 %-14s 抓到 %3d 条，保留 %3d 条", src["name"], len(items), len(kept))
        if src["type"] != "gnews":
            LAST["raw"][src["name"]] = len(items)
        return src["name"], kept

    LAST["raw"] = {}
    active = [s for s in expand_sources(sources, cfg) if s.get("enabled", True)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(one, active))
    stats = {name: (len(items) if items is not None else -1) for name, items in results}
    allitems = [it for _, items in results if items for it in items]
    return allitems, stats

