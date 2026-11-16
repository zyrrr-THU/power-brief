"""阅读反馈调权：收集网页上的 👍/👎，按来源、分类、关注词计算加减分。

反馈的两种回传方式：
1. GitHub：网页“提交反馈”打开预填的 Issue（标题以 feedback 开头，正文是 JSON），程序用公开 API 读取；
2. 文件：网页下载 feedback.json，放进 state/feedback_inbox/，下次运行自动合并。
"""
from __future__ import annotations

import json
import re
import shutil

from .util import STATE, http, log, read_json, write_json

VOTES = STATE / "feedback.json"
WEIGHTS = STATE / "weights.json"
INBOX = STATE / "feedback_inbox"
STEP, CAP = 0.5, 3.0


def _parse_payload(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) and ("votes" in d or d.get("reset")) else None


def _merge(store, payload):
    if payload.get("reset"):
        store["votes"] = {}
    for v in payload.get("votes", []):
        if isinstance(v, dict) and v.get("id") and v.get("v") in (1, -1, 0):
            if v["v"] == 0:
                store["votes"].pop(v["id"], None)
            else:
                store["votes"][v["id"]] = {k: v.get(k) for k in ("v", "origin", "source", "category", "watch", "title", "date")}


def collect(cfg):
    """合并新反馈，返回新增的反馈批次数。"""
    store = read_json(VOTES, {})
    store.setdefault("votes", {})
    store.setdefault("issues_done", [])
    n = 0
    repo = (cfg.get("feedback", {}) or {}).get("github_repo", "")
    if repo:
        try:
            r = http().get(f"https://api.github.com/repos/{repo}/issues", timeout=15,
                           params={"state": "all", "per_page": 50, "sort": "created", "direction": "desc"},
                           headers={"Accept": "application/vnd.github+json"})
            for iss in r.json() if r.status_code == 200 else []:
                if iss["number"] in store["issues_done"] or not iss.get("title", "").lower().startswith("feedback"):
                    continue
                payload = _parse_payload(iss.get("body"))
                if payload:
                    _merge(store, payload)
                    n += 1
                store["issues_done"].append(iss["number"])
            store["issues_done"] = store["issues_done"][-500:]
        except Exception as e:  # noqa: BLE001
            log.warning("读取 GitHub 反馈失败：%s", e)
    INBOX.mkdir(parents=True, exist_ok=True)
    for p in sorted(INBOX.glob("*.json")):
        payload = _parse_payload(p.read_text(encoding="utf-8", errors="ignore"))
        if payload:
            _merge(store, payload)
            n += 1
        done = INBOX / "processed"
        done.mkdir(exist_ok=True)
        shutil.move(str(p), str(done / p.name))
    write_json(VOTES, store)
    compute_weights(store)
    if n:
        log.info("合并反馈 %d 批，累计 %d 条", n, len(store["votes"]))
    return n


def _clamp(x):
    return max(-CAP, min(CAP, round(x, 2)))


def compute_weights(store):
    w = {"origin": {}, "category": {}, "watch": {}, "liked": [], "disliked": [], "count": len(store["votes"])}
    for v in store["votes"].values():
        s = STEP * v["v"]
        for key, val in (("origin", v.get("origin")), ("category", v.get("category"))):
            if val:
                w[key][val] = w[key].get(val, 0) + s
        for word in v.get("watch") or []:
            w["watch"][word] = w["watch"].get(word, 0) + s
        (w["liked"] if v["v"] > 0 else w["disliked"]).append(v.get("title", ""))
    for key in ("origin", "category", "watch"):
        w[key] = {k: _clamp(x) for k, x in w[key].items() if abs(x) >= 0.01}
    w["liked"], w["disliked"] = w["liked"][-10:], w["disliked"][-10:]
    write_json(WEIGHTS, w)
    return w


def load_weights():
    return read_json(WEIGHTS, {"origin": {}, "category": {}, "watch": {}, "liked": [], "disliked": [], "count": 0})


def bonus(it, w):
    b = w.get("origin", {}).get(it.get("origin"), 0) + w.get("category", {}).get(it.get("category"), 0)
    b += sum(w.get("watch", {}).get(x, 0) for x in it.get("watch_hit") or [])
    return max(-CAP * 2, min(CAP * 2, b))


def prompt_hint(w):
    """给大模型的读者偏好提示。"""
    lines = []
    if w.get("liked"):
        lines.append("读者点赞过的新闻：" + "；".join(t[:30] for t in w["liked"] if t))
    if w.get("disliked"):
        lines.append("读者不感兴趣的新闻：" + "；".join(t[:30] for t in w["disliked"] if t))
    return ("\n参考读者偏好（挑选时适当倾斜，但仍要兼顾覆盖面）：\n" + "\n".join(lines) + "\n") if lines else ""
