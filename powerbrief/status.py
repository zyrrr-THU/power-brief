"""给网页“设置”“运行记录”页导出状态：当前生效的配置（不含任何密钥值）、哪些密钥已配置、最近的运行记录。

docs/data/settings.js  生效配置 = config.yaml 等默认值叠加 settings.json；密钥只给“是否已配置”
docs/data/runlog.js    最近 14 次运行：时间、触发方式、条数、AI、推送结果、失败原因、日志尾部
"""
from __future__ import annotations

import os

from . import render
from .util import RUN_LINES, STATE, load_settings, load_yaml, now_utc, read_json, version, write_json

RUNLOG = STATE / "runlog.json"
KEEP_RUNS = 30
SHOW_RUNS = 14

# 推送渠道需要的密钥（与 notify.py 一致）
CHANNEL_SECRETS = {
    "pushplus": ["PUSHPLUS_TOKEN"], "serverchan": ["SERVERCHAN_SENDKEY"], "wecom": ["WECOM_WEBHOOK"],
    "feishu": ["FEISHU_WEBHOOK"], "dingtalk": ["DINGTALK_WEBHOOK"], "bark": ["BARK_KEY"],
    "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    "email": ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"],
}
FILES = {"config": "config.yaml", "stocks": "stocks.yaml", "sources": "sources.yaml", "topics": "topics.yaml"}


def secret_names(cfg):
    names = []
    for p in ((cfg.get("ai") or {}).get("provider_settings") or {}).values():
        if isinstance(p, dict) and p.get("api_key_env"):
            names.append(p["api_key_env"])
    for ks in CHANNEL_SECRETS.values():
        names += ks
    return list(dict.fromkeys(names))


def secrets_state(cfg):
    """只返回每个密钥是否已配置，绝不输出密钥内容。"""
    return {n: bool(os.environ.get(n, "").strip()) for n in secret_names(cfg)}


def github_run():
    """在 GitHub Actions 中运行时返回触发方式和本次运行的网址。"""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return {"runner": "local", "trigger": "manual", "run_id": "", "run_url": ""}
    rid = os.environ.get("GITHUB_RUN_ID", "")
    url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}"
           f"/actions/runs/{rid}") if rid else ""
    ev = os.environ.get("GITHUB_EVENT_NAME", "")
    return {"runner": "github", "trigger": {"schedule": "schedule", "workflow_dispatch": "dispatch"}.get(ev, ev),
            "run_id": rid, "run_url": url}


def export_settings():
    eff = {k: load_yaml(f) for k, f in FILES.items()}
    defaults = {k: load_yaml(f, overlay=False) for k, f in FILES.items()}
    runs = read_json(RUNLOG, [])
    obj = {
        "version": version(), "generated": now_utc().isoformat(timespec="seconds"),
        "effective": eff, "defaults": defaults, "overlay": load_settings(),
        "secrets": secrets_state(eff["config"]), "channel_secrets": CHANNEL_SECRETS,
        "repo": os.environ.get("GITHUB_REPOSITORY", "") or (eff["config"].get("feedback") or {}).get("github_repo", ""),
        "last_run": runs[-1] if runs else None,
    }
    render.write_extra("settings", obj)
    return obj


def record_run(info):
    """追加一条运行记录并导出给网页。info 至少含 date、ok。"""
    row = {"time": now_utc().isoformat(timespec="seconds"), "version": version(), **github_run(), **info}
    runs = read_json(RUNLOG, [])
    runs.append(row)
    runs = runs[-KEEP_RUNS:]
    write_json(RUNLOG, runs)
    render.write_extra("runlog", {"runs": list(reversed(runs[-SHOW_RUNS:])), "log_tail": RUN_LINES[-80:]})
    return row
