"""公共工具：路径、配置、环境变量、日志、HTTP。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"            # 生成的网站（GitHub Pages 从这里发布）
DATA = DOCS / "data"            # 每日简报数据
STATE = ROOT / "state"          # 去重记录、推送记录
LOGS = ROOT / "logs"
# 网页设置页保存的改动（覆盖 config.yaml 等文件中的默认值），由网页通过 GitHub 提交到仓库
SETTINGS_FILE = ROOT / "settings.json"
OVERLAY_KEYS = {"config.yaml": "config", "stocks.yaml": "stocks", "sources.yaml": "sources", "topics.yaml": "topics"}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

log = logging.getLogger("powerbrief")
RUN_LINES: list[str] = []       # 本次运行的日志（写入运行记录，网页“运行记录”页显示）


class _MemoryHandler(logging.Handler):
    def emit(self, record):
        RUN_LINES.append(self.format(record))
        del RUN_LINES[:-400]


def version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


def setup_logging(verbose: bool = False) -> None:
    LOGS.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.handlers.clear()
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)
    fh = logging.FileHandler(LOGS / f"{datetime.now():%Y-%m}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    mh = _MemoryHandler()
    mh.setFormatter(fmt)
    log.addHandler(mh)


def _kind(v):
    return "dict" if isinstance(v, dict) else "list" if isinstance(v, list) else "scalar"


def deep_merge(base, over, path=""):
    """覆盖层合并：字典逐键合并，列表和单值整体替换；类型对不上（如把列表改成了文字）时保留默认值。"""
    if base is None or over is None:
        return base if over is None else over
    if _kind(base) != _kind(over):
        log.warning("settings.json 中 %s 的类型与默认值不同，已忽略", path or "(根)")
        return base
    if isinstance(base, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep_merge(base.get(k), v, f"{path}.{k}" if path else str(k))
        return out
    return over


def load_settings() -> dict:
    """读取网页保存的覆盖层；文件缺失或损坏时当作没有改动。"""
    d = read_json(SETTINGS_FILE, {})
    if not isinstance(d, dict):
        log.warning("settings.json 格式不对（应为对象），已忽略")
        return {}
    return d


def load_yaml(name: str, overlay: bool = True) -> dict:
    """读取配置文件；overlay=True 时叠加 settings.json 里对应部分（网页上改过的设置）。"""
    with open(ROOT / name, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    key = OVERLAY_KEYS.get(name)
    if overlay and key:
        ov = load_settings().get(key)
        if isinstance(ov, dict) and ov:
            data = deep_merge(data, ov, key)
    return data


def load_env() -> None:
    """读取项目根目录的 .env（不覆盖已存在的系统环境变量）。"""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v and not os.environ.get(k):
            os.environ[k] = v


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def local_today(offset_hours: int = 8) -> str:
    return (now_utc() + timedelta(hours=offset_hours)).strftime("%Y-%m-%d")


def http(retries: int = 3) -> requests.Session:
    """带自动重试的会话：GET/HEAD 遇到网络错误、429、5xx 时指数退避重试。"""
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    retry = Retry(total=retries, connect=retries, read=retries, backoff_factor=0.8,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET", "HEAD"}),
                  raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def short_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


_PUNCT = re.compile(r"[\s　，。、！？：；“”‘’「」『』《》【】（）()\[\]<>|·…—\-_.,!?:;'\"/\\#@%&*+=~`^]+")


def norm_title(title: str) -> str:
    """去掉来源后缀和标点，用于去重。"""
    t = re.sub(r"\s+[-–—|_]\s+[^-–—|_]{1,30}$", "", title.strip())  # 去掉 “ - 新浪财经” 这类来源
    return _PUNCT.sub("", t).lower()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
