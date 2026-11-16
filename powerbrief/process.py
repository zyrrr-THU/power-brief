"""处理：去重（当日 + 跨 30 天）、分类、打分、精选。"""
from __future__ import annotations

from datetime import datetime, timedelta
from difflib import SequenceMatcher

from .feedback import bonus as feedback_bonus
from .indicators import REGIONS
from .sources import policy_type
from .util import STATE, norm_title, now_utc, read_json, short_hash, write_json

SEEN_FILE = STATE / "seen.json"
SEEN_DAYS = 30


def _similar(a, b):
    if not a or not b:
        return False
    if a in b or b in a:
        return min(len(a), len(b)) >= 8
    return SequenceMatcher(None, a, b).ratio() >= 0.72


def cluster(items):
    """把同一事件的多家报道合并：保留来源层级最高的一条，记录同报数量和其他来源。"""
    items = sorted(items, key=lambda x: (-x["tier"], x["published"] or ""), reverse=False)
    groups = []
    for it in items:
        it["_norm"] = norm_title(it["title"])
        for g in groups:
            if _similar(it["_norm"], g[0]["_norm"]):
                g.append(it)
                break
        else:
            groups.append([it])
    out = []
    for g in groups:
        head = g[0]
        head["coverage"] = len({x["origin"] for x in g})
        head["also"] = sorted({x["origin"] for x in g[1:] if x["origin"] != head["origin"]})[:4]
        out.append(head)
    return out


def load_seen():
    seen = read_json(SEEN_FILE, {})
    limit = (now_utc() - timedelta(days=SEEN_DAYS)).strftime("%Y-%m-%d")
    return {k: v for k, v in seen.items() if v >= limit}


def drop_seen(items, seen, today):
    """去掉往日已推送过的新闻；今天标记的不算（同一天重跑时结果保持一致）。"""
    out = []
    for it in items:
        keys = (short_hash(it["url"]), short_hash(it["_norm"]))
        if any(seen.get(k, today) < today for k in keys):
            continue
        out.append(it)
    return out


def mark_seen(items, seen, day):
    for it in items:
        for u in (it["url"], it.get("gnews_url")):
            if u:
                seen[short_hash(u)] = day
        seen[short_hash(norm_title(it["title"]))] = day
    write_json(SEEN_FILE, seen)


ISSUERS = ("国务院", "国家能源局", "发改委", "发展改革委", "能源局", "监管局", "生态环境部", "工信部", "工业和信息化部",
           "财政部", "市场监管", "人民政府", "交易中心", "省", "自治区", "市政府", "部门", "印发", "实施细则",
           "实施方案", "长三角", "京津冀", "粤港澳", "成渝", "区域电力市场")
# 只用省级地名判断地方政策；“市”“区”等单字会误中“市场”“园区”
PROVINCES = tuple(r for r in REGIONS if len(r) >= 2)


def classify(title, categories):
    t = title.lower()
    for c in categories:
        if any(k.lower() in t for k in c["keywords"]):
            return c["name"]
    return "综合"


def score(it, cfg, weights=None):
    s = it["tier"] * 2.0
    s += min(it.get("coverage", 1), 5) * 1.2
    if it.get("watch_hit"):
        s += 1.5
    if it["category"] in ("政策法规", "市场与电价"):
        s += 2.5
    if it.get("policy_type") == "征求意见":
        s += 1.5
    if it["lang"] == "en":
        s -= 1.5
    if any(k in it["title"] for k in cfg.get("penalty_keywords", [])):
        s -= 4
    if it["published"]:
        age_h = (now_utc() - datetime.fromisoformat(it["published"])).total_seconds() / 3600
        s += max(0.0, 2.0 - age_h / 12)
    if weights:
        s += feedback_bonus(it, weights)
    return round(s, 2)


def enrich(items, cfg, weights=None):
    cats = cfg.get("categories", [])
    watch = cfg.get("watchlist", [])
    for it in items:
        it["category"] = "国际" if it["lang"] == "en" else classify(it["title"], cats)
        # 政策来源直接判断类型；其他来源要同时出现发文机关才算政策，避免“解决方案”“规划方案中标”之类误判
        if it.get("policy_src") or (it["category"] == "政策法规" and (
                any(k in it["title"] for k in ISSUERS + PROVINCES) or "征求意见" in it["title"])):
            it["policy_type"] = policy_type(it["title"])
        else:
            it["policy_type"] = ""
        if it.get("policy_src") and it["lang"] == "zh":
            it["category"] = "政策法规"
        it["watch_hit"] = [w for w in watch if w in it["title"]]
        it["score"] = score(it, cfg, weights)
        it.setdefault("id", short_hash(it["url"]))
    return sorted(items, key=lambda x: -x["score"])


def select(items, n, per_cat):
    """按分数挑选，同时限制每个分类的条数，保证覆盖面。"""
    chosen, count = [], {}
    for it in items:
        c = it["category"]
        if count.get(c, 0) >= per_cat:
            continue
        chosen.append(it)
        count[c] = count.get(c, 0) + 1
        if len(chosen) >= n:
            break
    return chosen
