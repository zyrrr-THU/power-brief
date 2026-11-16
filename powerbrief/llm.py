"""大模型供应商：统一接口 complete(system, prompt) -> str。

三类实现：
- openai_compatible : OpenAI(ChatGPT) / DeepSeek / 通义千问 / Kimi / 智谱 等，只改 base_url、model、key
- anthropic         : Claude API（官方 Python SDK）
- claude_cli        : 本机 Claude Code 命令行 `claude -p`，使用已登录的订阅额度，无需 API key
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .util import env, http, log


class ProviderUnavailable(Exception):
    """供应商未配置（没 key / 没安装），直接跳到下一个。"""


class OpenAICompatible:
    def __init__(self, name, conf):
        self.name, self.conf = name, conf
        self.key = env(conf.get("api_key_env", ""))
        if not self.key:
            raise ProviderUnavailable(f"未设置 {conf.get('api_key_env')}")

    def complete(self, system, prompt):
        url = self.conf["base_url"].rstrip("/") + "/chat/completions"
        body = {
            "model": self.conf["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_tokens": int(self.conf.get("max_tokens", 8000)),
        }
        r = http().post(url, json=body, timeout=int(self.conf.get("timeout_seconds", 180)),
                        headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        u = data.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or u.get("prompt_cache_hit_tokens") or 0
        self.last_usage = {"model": self.conf["model"], "input": (u.get("prompt_tokens") or 0) - cached,
                           "output": u.get("completion_tokens") or 0, "cache_read": cached, "cache_write": 0}
        return data["choices"][0]["message"]["content"]


class AnthropicAPI:
    def __init__(self, name, conf):
        self.name, self.conf = name, conf
        self.key = env(conf.get("api_key_env", "ANTHROPIC_API_KEY"))
        if not self.key:
            raise ProviderUnavailable(f"未设置 {conf.get('api_key_env', 'ANTHROPIC_API_KEY')}")
        try:
            import anthropic  # noqa: PLC0415 只有用到 Claude API 时才需要安装
        except ImportError as e:
            raise ProviderUnavailable("未安装 anthropic（pip install anthropic）") from e
        self.client = anthropic.Anthropic(api_key=self.key, timeout=300, max_retries=2)

    def complete(self, system, prompt):
        resp = self.client.beta.messages.create(
            model=self.conf.get("model", "claude-opus-5-5"),
            max_tokens=int(self.conf.get("max_tokens", 16000)),
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.conf.get("effort", "low")},
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},  # 安全分类器拒答时由服务端自动换模型重试
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("模型拒答")
        u = resp.usage
        self.last_usage = {"model": resp.model, "input": u.input_tokens or 0, "output": u.output_tokens or 0,
                           "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                           "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0}
        return "".join(b.text for b in resp.content if b.type == "text")


class ClaudeCLI:
    def __init__(self, name, conf):
        self.name, self.conf = name, conf
        self.cmd = shutil.which(conf.get("command", "claude"))
        if not self.cmd and os.name == "nt":  # npm 全局目录常不在 PATH 里（尤其是计划任务环境）
            cand = Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"
            self.cmd = str(cand) if cand.exists() else None
        if self.cmd and self.cmd.lower().endswith(".cmd"):
            # 直接调用 npm 包里的 claude.exe，避免经过 cmd.exe 时中文和特殊字符参数被改写
            exe = Path(self.cmd).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
            if exe.exists():
                self.cmd = str(exe)
        if not self.cmd:
            raise ProviderUnavailable("本机未找到 claude 命令（npm i -g @anthropic-ai/claude-code 并登录）")

    def complete(self, system, prompt):
        # 精简调用：用自己的系统提示词替换 Claude Code 默认的长提示词，关闭工具和 MCP，
        # 在临时目录运行避免读入项目 CLAUDE.md，从而大幅减少每次消耗的 token
        args = [self.cmd, "-p", "--output-format", "json", "--system-prompt", system, "--tools", "",
                "--strict-mcp-config", "--no-session-persistence"]
        if self.conf.get("model"):
            args += ["--model", self.conf["model"]]
        r = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           timeout=int(self.conf.get("timeout_seconds", 300)), cwd=tempfile.gettempdir())
        out = (r.stdout or "").strip()
        try:
            data = json.loads(out[out.find("{"):]) if "{" in out else {}
        except ValueError:
            data = {}
        if r.returncode != 0 or data.get("is_error"):
            raise RuntimeError(f"claude 退出码 {r.returncode}: {(data.get('result') or r.stderr or out)[:200]}")
        u = data.get("usage") or {}
        models = list((data.get("modelUsage") or {}).keys())
        self.last_usage = {"model": models[0] if models else self.conf.get("model", "claude"),
                           "input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
                           "cache_read": u.get("cache_read_input_tokens") or 0,
                           "cache_write": u.get("cache_creation_input_tokens") or 0,
                           "cost_usd": data.get("total_cost_usd")}
        return data.get("result") or ""


TYPES = {"openai_compatible": OpenAICompatible, "anthropic": AnthropicAPI, "claude_cli": ClaudeCLI}


def run_chain(ai_cfg, system, prompt, parse, purpose="daily"):
    """按配置顺序尝试供应商，返回 (解析结果, 供应商名)；全部失败返回 (None, None)。每次调用的 token 用量记入 state/usage.json。"""
    from . import usage  # noqa: PLC0415

    settings = ai_cfg.get("provider_settings", {})
    for name in ai_cfg.get("providers", []):
        conf = settings.get(name)
        if not conf or conf.get("type") not in TYPES:
            log.warning("供应商 %s 未在 provider_settings 中正确配置，跳过", name)
            continue
        try:
            client = TYPES[conf["type"]](name, conf)
        except ProviderUnavailable as e:
            log.info("跳过 %s：%s", name, e)
            continue
        t0 = time.time()
        try:
            log.info("调用大模型 %s (%s)…", name, conf.get("model", ""))
            text = client.complete(system, prompt)
            usage.record(ai_cfg, name, conf, purpose, getattr(client, "last_usage", None), True, time.time() - t0,
                         len(system) + len(prompt))
            return parse(text), name
        except Exception as e:  # noqa: BLE001 换下一个
            usage.record(ai_cfg, name, conf, purpose, getattr(client, "last_usage", None), False, time.time() - t0,
                         len(system) + len(prompt))
            log.warning("大模型 %s 失败：%s", name, str(e)[:200])
    return None, None
