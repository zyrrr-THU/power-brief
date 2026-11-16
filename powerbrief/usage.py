"""大模型用量统计：每次调用的 token 数、折算费用，按天汇总，并估算占订阅额度的比例。

费用：Claude 命令行直接返回折算的 API 价格（total_cost_usd）；其他供应商按下方价目表估算。
订阅占比：Anthropic 不公开订阅套餐的 token 上限，这里用“折算 API 费用 ÷ 套餐月费”作为参考指标，
真实剩余额度以 Claude Code 中 /usage 显示为准。
"""
from __future__ import annotations

from datetime import date, timedelta

from .util import STATE, local_today, read_json, write_json

FILE = STATE / "usage.json"

# 美元 / 百万 token：输入、输出、缓存读取、缓存写入（可在 config.yaml 的 usage.pricing 覆盖）
PRICING = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "deepseek-chat": (0.27, 1.10, 0.07, 0.27),
    "gpt-5-mini": (0.25, 2.0, 0.025, 0.25),
    "qwen-plus": (0.11, 0.28, 0.03, 0.11),
    "moonshot-v1-32k": (3.3, 3.3, 3.3, 3.3),
    "glm-4-flash": (0.0, 0.0, 0.0, 0.0),
}
ALIASES = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5"}

# 订阅套餐月费（美元）
PLANS = {"pro": ("Claude Pro", 20), "max5": ("Claude Max 5x", 100), "max20": ("Claude Max 20x", 200),
         "api": ("按量付费 API", None)}


def _price(model, overrides):
    m = ALIASES.get(model, model or "")
    table = dict(PRICING)
    table.update({k: tuple(v) for k, v in (overrides or {}).items()})
    if m in table:
        return table[m]
    for k, v in table.items():  # 带日期后缀等变体
        if m.startswith(k) or k in m:
            return v
    return None


def estimate_cost(u, overrides=None):
    p = _price(u.get("model"), overrides)
    if not p:
        return None
    return round((u.get("input", 0) * p[0] + u.get("output", 0) * p[1] + u.get("cache_read", 0) * p[2]
                  + u.get("cache_write", 0) * p[3]) / 1e6, 5)


def record(ai_cfg, provider, conf, purpose, u, ok, seconds, prompt_chars):
    data = read_json(FILE, {})
    today = local_today(8)
    u = dict(u or {})
    row = {"provider": provider, "type": conf.get("type"), "model": u.get("model") or conf.get("model", ""),
           "purpose": purpose, "ok": ok, "seconds": round(seconds, 1), "prompt_chars": prompt_chars,
           "input": int(u.get("input", 0)), "output": int(u.get("output", 0)),
           "cache_read": int(u.get("cache_read", 0)), "cache_write": int(u.get("cache_write", 0))}
    row["total"] = row["input"] + row["output"] + row["cache_read"] + row["cache_write"]
    cost = u.get("cost_usd")
    row["cost_usd"] = round(cost, 5) if isinstance(cost, (int, float)) else estimate_cost(row, (ai_cfg or {}).get("pricing"))
    row["cost_source"] = "claude" if isinstance(cost, (int, float)) else "估算"
    data.setdefault(today, []).append(row)
    keep = (date.fromisoformat(today) - timedelta(days=120)).isoformat()
    write_json(FILE, {k: v for k, v in sorted(data.items()) if k >= keep})


def report(cfg, days=30):
    """用量报告：每日汇总、近 days 天平均、月度折算和占套餐比例。"""
    data = read_json(FILE, {})
    ucfg = cfg.get("usage", {}) or {}
    plan_key = ucfg.get("plan", "pro")
    plan_name, fee = PLANS.get(plan_key, PLANS["pro"])
    rows = []
    for d, calls in sorted(data.items()):
        tot = {k: sum(c.get(k, 0) or 0 for c in calls) for k in ("input", "output", "cache_read", "cache_write", "total")}
        cost = sum(c.get("cost_usd") or 0 for c in calls)
        rows.append({"date": d, **tot, "cost_usd": round(cost, 4), "calls": len(calls),
                     "failed": sum(1 for c in calls if not c.get("ok")),
                     "providers": sorted({c["provider"] for c in calls}),
                     "detail": calls})
    recent = [r for r in rows if r["date"] >= (date.fromisoformat(local_today(8)) - timedelta(days=days)).isoformat()]
    ok_days = [r for r in recent if r["total"] > 0]
    avg_tokens = round(sum(r["total"] for r in ok_days) / len(ok_days)) if ok_days else 0
    avg_cost = round(sum(r["cost_usd"] for r in ok_days) / len(ok_days), 4) if ok_days else 0
    month_cost = round(avg_cost * 30, 2)
    return {
        "plan": plan_key, "plan_name": plan_name, "plan_fee_usd": fee,
        "days": rows[-60:], "days_with_usage": len(ok_days),
        "avg_tokens_per_day": avg_tokens, "avg_cost_per_day_usd": avg_cost,
        "month_tokens": avg_tokens * 30, "month_cost_usd": month_cost,
        "plan_share_pct": round(month_cost / fee * 100, 1) if fee and ok_days else None,
        "note": ("“约占套餐”= 按 API 价格折算的月费用 ÷ 套餐月费，是偏保守的参考值：订阅额度按 5 小时和每周窗口计算，"
                 "官方未公布 token 上限，一般可用量折算成 API 价格高于月费，所以实际占用比例通常更低。"
                 "在 Claude Code 中输入 /usage 可看到真实的额度使用情况。"),
    }
