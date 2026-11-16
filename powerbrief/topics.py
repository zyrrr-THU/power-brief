"""事件追踪与专题：给新闻打专题标签，跨天串成时间线；AI 提议的新专题出现足够多次自动升格。"""
from __future__ import annotations

from datetime import date, timedelta

from .util import STATE, read_json, write_json

FILE = STATE / "topics.json"
MAX_ENTRIES = 300
PROMOTE_TIMES, PROMOTE_DAYS = 3, 14


def load():
    st = read_json(FILE, {})
    st.setdefault("topics", {})
    st.setdefault("candidates", {})
    return st


def save(st):
    write_json(FILE, st)


def all_topics(conf, st):
    """配置中的专题 + 已自动升格的专题：{名称: 关键词列表}。"""
    out = {k: list(v or []) for k, v in (conf or {}).items()}
    for name, t in st["topics"].items():
        if t.get("auto") and name not in out:
            out[name] = [name]
    return out


def match(text, topic_kws, limit=2):
    hits = []
    for name, kws in topic_kws.items():
        n = sum(1 for k in kws if k and k in text)
        if n:
            hits.append((n, name))
    hits.sort(key=lambda x: -x[0])
    return [name for _, name in hits[:limit]]


def tag(items, topic_kws):
    """无 AI 或 AI 未给出专题时，按关键词打标签。"""
    for it in items:
        if not it.get("topics"):
            it["topics"] = match(it["title"] + " " + it.get("summary", ""), topic_kws)


def _entry(it, today):
    return {"date": today, "id": it["id"], "title": it["title"], "url": it["url"], "summary": it.get("summary", "")[:120]}


def update(st, items, today, known):
    """把今天的条目写入专题时间线；处理 AI 提议的新专题。"""
    cutoff = (date.fromisoformat(today) - timedelta(days=PROMOTE_DAYS)).isoformat()
    for it in items:
        for name in it.get("topics", []):
            if name in known or name in st["topics"]:
                t = st["topics"].setdefault(name, {"auto": name not in known, "created": today, "entries": []})
                if all(e["id"] != it["id"] for e in t["entries"]):
                    t["entries"].append(_entry(it, today))
                    t["entries"] = t["entries"][-MAX_ENTRIES:]
            else:
                cands = st["candidates"].setdefault(name, [])
                if all(c["id"] != it["id"] for c in cands):
                    cands.append(_entry(it, today))
    # 升格：14 天内出现次数足够的候选专题
    for name in list(st["candidates"]):
        recent = [c for c in st["candidates"][name] if c["date"] >= cutoff]
        if len(recent) >= PROMOTE_TIMES:
            st["topics"][name] = {"auto": True, "created": today, "entries": recent}
            del st["candidates"][name]
        elif recent:
            st["candidates"][name] = recent
        else:
            del st["candidates"][name]


def annotate(items, st, today):
    """给每条新闻附上专题的往期信息：此前几条、上次日期。"""
    for it in items:
        info = []
        for name in it.get("topics", []):
            prior = [e for e in st["topics"].get(name, {}).get("entries", []) if e["date"] < today]
            info.append({"name": name, "prior": len(prior), "last": prior[-1]["date"] if prior else None})
        it["topic_info"] = info


def weekly_hot(st, today, days=7):
    start = (date.fromisoformat(today) - timedelta(days=days - 1)).isoformat()
    best, best_n = None, 0
    for name, t in st["topics"].items():
        n = sum(1 for e in t["entries"] if e["date"] >= start)
        if n > best_n:
            best, best_n = name, n
    if not best:
        return None, []
    return best, [e for e in st["topics"][best]["entries"] if e["date"] >= start]


def export(st):
    """给网页用的精简数据。"""
    out = []
    for name, t in st["topics"].items():
        es = t.get("entries", [])
        if not es:
            continue
        out.append({"name": name, "auto": bool(t.get("auto")), "count": len(es), "last": es[-1]["date"],
                    "entries": list(reversed(es[-80:]))})
    out.sort(key=lambda x: (x["last"], x["count"]), reverse=True)
    return {"topics": out}
