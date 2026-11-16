"""原文处理：把 Google 新闻跳转链接解码为原站链接，抓取正文摘录和发布日期。"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from bs4 import BeautifulSoup

from .util import STATE, http, log, read_json, write_json

CACHE_FILE = STATE / "url_cache.json"
GN_PREFIX = "news.google.com/rss/articles/"


def _gnews_session():
    s = http(retries=1)
    s.cookies.update({"CONSENT": "YES+cb", "SOCS": "CAI"})  # 跳过欧盟 Cookie 同意页
    return s


def decode_gnews(url, sess=None):
    """Google 新闻跳转链接 → 原站链接；失败返回 None。"""
    if GN_PREFIX not in url:
        return url
    sess = sess or _gnews_session()
    aid = url.split("/articles/")[1].split("?")[0]
    page = sess.get(f"https://news.google.com/rss/articles/{aid}", timeout=10).text
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not sg or not ts:
        return None
    inner = ["Fbv4je", f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,'
                       f'null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{aid}",{ts.group(1)},"{sg.group(1)}"]']
    r = sess.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", timeout=10,
                  data=f"f.req={quote(json.dumps([[inner]]))}",
                  headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    try:
        real = json.loads(json.loads(r.text.split("\n\n")[1])[0][2])[1]
    except (IndexError, ValueError, TypeError):
        return None
    return real if isinstance(real, str) and real.startswith("http") else None


DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})[日\s]*(\d{1,2}):(\d{2})"),
    re.compile(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})"),
]


def _page_date(soup, text):
    for attr in ("article:published_time", "publishdate", "PubDate", "pubdate", "publish_time"):
        m = soup.find("meta", attrs={"property": attr}) or soup.find("meta", attrs={"name": attr})
        if m and m.get("content"):
            text = m["content"] + " " + text
            break
    for rx in DATE_PATTERNS:
        m = rx.search(text[:3000])
        if m:
            g = [int(x) for x in m.groups()]
            try:
                d = datetime(g[0], g[1], g[2], *(g[3:5] if len(g) > 3 else (12, 0)),
                             tzinfo=timezone(timedelta(hours=8)))
            except ValueError:
                continue
            if d.year >= 2000:
                return d
    return None


def extract(url, sess=None, limit=600):
    """返回 (正文摘录, 发布时间或 None)。"""
    sess = sess or http(retries=1)
    r = sess.get(url, timeout=10)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        t.decompose()
    # 选出包含最多段落文字的容器作为正文
    best, best_len = None, 0
    for node in soup.find_all(["article", "div", "section", "td"]):
        ps = node.find_all("p", recursive=False) or node.find_all("p")
        n = sum(len(p.get_text(strip=True)) for p in ps)
        if n > best_len and len(ps) >= 1:
            best, best_len = node, n
    paras = [p.get_text(" ", strip=True) for p in (best or soup).find_all("p")]
    body = " ".join(p for p in paras if len(p) > 15)
    if len(body) < 40:
        body = " ".join(soup.get_text(" ", strip=True).split())[:limit]
    return body[:limit], _page_date(soup, soup.get_text(" ", strip=True))


def enrich_articles(items, limit=40, workers=6):
    """对排序前 limit 条：解码原站链接、补正文摘录、补发布日期。就地修改，返回统计。"""
    cache = read_json(CACHE_FILE, {})
    stats = {"decoded": 0, "decode_failed": 0, "text": 0}
    gsess = _gnews_session()

    def one(it):
        url = it["url"]
        try:
            if GN_PREFIX in url:
                real = cache.get(url)
                if real is None:
                    real = decode_gnews(url, gsess) or ""
                    cache[url] = real
                if real:
                    it["gnews_url"], it["url"] = url, real
                    stats["decoded"] += 1
                else:
                    stats["decode_failed"] += 1
                    return
            if not it.get("snippet") or len(it["snippet"]) < 80:
                text, pub = extract(it["url"])
                if text:
                    it["snippet"] = text
                    stats["text"] += 1
                if pub and not it.get("published"):
                    it["published"] = pub.astimezone(timezone.utc).isoformat()
                    it["date_from_page"] = True
        except Exception as e:  # noqa: BLE001 单条失败不影响整体
            log.debug("原文处理失败 %s: %s", url[:80], e)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, items[:limit]))
    # 缓存只保留最近 3000 条
    if len(cache) > 3000:
        cache = dict(list(cache.items())[-3000:])
    write_json(CACHE_FILE, cache)
    log.info("原文：解码 %d 条（失败 %d），抓到正文 %d 条", stats["decoded"], stats["decode_failed"], stats["text"])
    return stats
