"""摘要：AI 模式（大模型写摘要、解读、术语）与规则模式（词典解释），AI 失败自动降级。"""
from __future__ import annotations

import json
import re
from datetime import date

from .llm import run_chain
from .process import select
from .util import log

SYSTEM = (
    "你是一名资深电力行业分析师，为一位希望系统了解电力行业的读者编写每日简报。"
    "读者不是专家：要用通俗中文，解释专业术语，突出对行业的影响。"
    "只能依据给出的标题和摘录写作，不得编造数字、日期或细节；信息不足时就写得概括一些。"
    "只输出一个 JSON 对象，不要输出任何其他文字。"
)

PROMPT = """今天是 {today}。下面是从政府网站、行业媒体和新闻搜索抓取的 {n} 条电力/能源候选新闻（已初步去重）。

任务：
1. 从中挑选对理解电力行业最有价值的约 {k} 条（政策、市场电价、大型和中小企业动态、新能源储能、电网技术、国际都要兼顾；广告、软文、与电力无关的剔除）。
2. 对每条入选新闻写：summary（2句话、不超过80字，说清发生了什么）；why（1句话、不超过50字，说明对行业或企业意味着什么）；terms（标题或摘要里外行看不懂的专业术语，0-2个，每个解释不超过40字）。
3. importance 打分 1-5（5=全国性重大政策或市场变化）。category 从 [{cats}] 中选一个。
4. 政策类新闻：policy_type 填“正式文件”“征求意见”“政策解读”之一（非政策填空字符串）；征求意见稿如摘录里有截止日期，deadline 填 YYYY-MM-DD，否则空。
5. topics：从专题列表 [{topics}] 中选 0-2 个最相关的；如果确实属于一个反复出现、列表里没有的新议题，可以写一个 4-8 字的新专题名。
6. highlights：今日三件事，3条，每条不超过40字，概括当天最重要的趋势或事件。
7. concept：挑一个与今天新闻相关、值得新人掌握的行业概念，用不超过150字讲清楚。
8. data_points：从全部候选的标题和摘录中摘出最多 8 个有价值的行业数字（价格、电量、装机、增速等），每个给 name（指标名，含地区和口径）、value（纯数字）、unit、date（数据所属日期 YYYY-MM-DD 或月份 YYYY-MM，不确定填空）、i（来源编号）。只摘原文明确写出的数字。
{prefs}
输出 JSON 格式：
{{"highlights": ["", "", ""],
 "items": [{{"i": 编号, "importance": 1-5, "category": "", "policy_type": "", "deadline": "", "topics": [""], "summary": "", "why": "", "terms": [{{"term": "", "explain": ""}}]}}],
 "concept": {{"term": "", "explain": ""}},
 "data_points": [{{"name": "", "value": 0, "unit": "", "date": "", "i": 编号}}]}}

候选新闻：
{lines}
"""

DEEP_PROMPT = """下面是专题“{topic}”最近一周的新闻时间线（日期｜标题｜摘要）。请为一位希望系统了解电力行业的读者写一篇约 600 字的专题解读，
分四段，每段以小标题开头：【背景】这个议题是什么、为什么重要；【本周进展】按时间梳理；【影响】对电价、企业、用户的影响；【接下来关注】2-3 个值得跟踪的信号。
只依据时间线内容，不编造数字。直接输出正文，不要输出 JSON。

{lines}
"""

CATS = ["政策法规", "市场与电价", "新能源与储能", "电网与技术", "企业动态", "国际", "综合"]


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("返回中没有 JSON")
    data = json.loads(text[start:end + 1])
    if not isinstance(data.get("items"), list):
        raise ValueError("JSON 缺少 items")
    return data


def glossary_terms(text, glossary, limit=2):
    found = [(k, v) for k, v in glossary.items() if k in text]
    found.sort(key=lambda kv: -len(kv[0]))  # 长词优先，避免“现货”压过“电力现货市场”
    return [{"term": k, "explain": v} for k, v in found[:limit]]


def concept_of_day(glossary, today):
    if not glossary:
        return None
    keys = list(glossary)
    k = keys[date.fromisoformat(today).toordinal() % len(keys)]
    return {"term": k, "explain": glossary[k]}


def rule_mode(cands, cfg, glossary, today):
    run = cfg["run"]
    chosen = select(cands, run.get("max_items", 22), run.get("max_per_category", 6))
    for it in chosen:
        it["summary"] = it.get("snippet", "")[:120]
        it["why"] = ""
        it["terms"] = glossary_terms(it["title"] + it["summary"], glossary)
        it["importance"] = None
    return {"highlights": [it["title"] for it in chosen[:3]], "items": chosen,
            "concept": concept_of_day(glossary, today), "mode": "rule", "provider": None}


def ai_mode(cands, cfg, glossary, today, topic_names=(), prefs=""):
    ai = cfg["ai"]
    run = cfg["run"]
    pool = cands[: int(ai.get("max_candidates", 40))]
    lines = []
    for i, it in enumerate(pool):
        extra = f"｜摘录：{it['snippet'][:220]}" if it.get("snippet") else ""
        lines.append(f"[{i}] {it['title']}｜来源：{it['origin']}｜初分类：{it['category']}{extra}")
    prompt = PROMPT.format(today=today, n=len(pool), k=run.get("max_items", 22), cats="、".join(CATS),
                           topics="、".join(topic_names), prefs=prefs, lines="\n".join(lines))
    data, provider = run_chain(ai, SYSTEM, prompt, parse_json)
    if not data:
        return None
    picked = []
    for row in data["items"]:
        try:
            it = dict(pool[int(row["i"])])
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        it["summary"] = str(row.get("summary", "")).strip()
        it["why"] = str(row.get("why", "")).strip()
        it["terms"] = [t for t in row.get("terms") or [] if isinstance(t, dict) and t.get("term")][:2] \
            or glossary_terms(it["title"], glossary)
        try:
            it["importance"] = max(1, min(5, int(row.get("importance") or 3)))
        except (TypeError, ValueError):
            it["importance"] = 3
        if row.get("category") in CATS:
            it["category"] = row["category"]
        if row.get("policy_type") in ("正式文件", "征求意见", "政策解读"):
            it["policy_type"] = row["policy_type"]
        dl = str(row.get("deadline") or "")
        it["deadline"] = dl if re.match(r"^20\d{2}-\d{2}-\d{2}$", dl) else ""
        tps = [str(t).strip() for t in row.get("topics") or [] if str(t).strip()]
        it["topics"] = tps[:2]
        it["score"] = round(it["score"] + it["importance"] * 3, 2)
        picked.append(it)
    if not picked:
        return None
    picked.sort(key=lambda x: -x["score"])
    chosen = select(picked, run.get("max_items", 22), run.get("max_per_category", 6))
    concept = data.get("concept") if isinstance(data.get("concept"), dict) and data["concept"].get("term") \
        else concept_of_day(glossary, today)
    highlights = [str(h) for h in data.get("highlights", []) if h][:3] or [it["title"] for it in chosen[:3]]
    dps = data.get("data_points") if isinstance(data.get("data_points"), list) else []
    return {"highlights": highlights, "items": chosen, "concept": concept, "mode": "ai", "provider": provider,
            "data_points": dps, "pool": pool}


def summarize(cands, cfg, glossary, today, force_rule=False, topic_names=(), prefs=""):
    if cfg["ai"].get("enabled") and not force_rule:
        res = ai_mode(cands, cfg, glossary, today, topic_names, prefs)
        if res:
            return res
        log.warning("所有大模型都不可用，降级为无 AI 模式")
    res = rule_mode(cands, cfg, glossary, today)
    res.update(data_points=[], pool=cands)
    return res


def deep_dive(cfg, topic, entries):
    """周日专题深度解读；无 AI 时返回 None。"""
    if not cfg["ai"].get("enabled") or not entries:
        return None
    lines = "\n".join(f"{e['date']}｜{e['title']}｜{e.get('summary', '')}" for e in entries[-30:])
    system = "你是一名资深电力行业分析师，擅长把复杂议题讲给行业新人听。"
    text, provider = run_chain(cfg["ai"], system, DEEP_PROMPT.format(topic=topic, lines=lines), _long_text,
                               purpose="weekly")
    return {"topic": topic, "text": text, "provider": provider} if text else None


def _long_text(t):
    t = t.strip()
    if len(t) < 100:
        raise ValueError("返回内容太短")
    return t
