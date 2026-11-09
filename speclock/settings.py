"""环境配置：单个 speclock.toml 管理多套环境，改 active 一键切换。

文件位置（按序）：
1. 环境变量 SPECLOCK_CONFIG 指定的路径；
2. 仓库根目录 speclock.toml（pyproject.toml 旁）。

当前环境也可由环境变量 SPECLOCK_ENV 覆盖（systemd / CI 场景不方便改文件时）。
文件缺失时回退到 local 默认值，保证裸 checkout 也能跑。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent.parent / "speclock.toml"


@dataclass(frozen=True)
class ReviewSettings:
    """内部整理的「语义复核」阈值（speclock.toml 的 [review] 节）。保守的默认值：只放行
    单条条目里的小幅文字改动（错别字、标点、个别措辞），超过任何一项就按业务变更处理。"""

    enabled: bool = True  # false = 关闭这一档，回到「条目的字只要变了就拒绝」
    max_entries: int = 3  # 一个 Commit 里最多有几条条目被改
    max_edit_chars: int = 6  # 一条条目的名称 / 详述，各自最多改动多少个字（编辑距离）
    max_edit_ratio: float = 0.15  # 并且改动不超过原文的这个比例
    max_text_len: int = 2000  # 单段文字超过这个长度不做对比，直接按业务变更处理


@dataclass(frozen=True)
class Settings:
    env: str
    db_url: str  # 数据库 URL（SPECLOCK_DB_URL 环境变量优先，测试用它隔离）
    host: str  # uvicorn 监听地址
    port: int  # uvicorn 监听端口
    public_url: str  # 保留字段，当前未被服务端使用（SPA 按 window.location.origin 生成接入配置）
    review: ReviewSettings = ReviewSettings()  # 语义复核阈值（各环境共用）


def load_settings() -> Settings:
    path = Path(os.environ.get("SPECLOCK_CONFIG", str(_DEFAULT_PATH)))
    data: dict = {}
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    env = os.environ.get("SPECLOCK_ENV") or data.get("active", "local")
    profile = data.get(env, {})
    if env not in ("local",) and not profile:
        available = [k for k, v in data.items() if isinstance(v, dict)]
        raise ValueError(f"speclock.toml 中没有环境 [{env}]（可选：{available}）")
    r = data.get("review", {})
    defaults = ReviewSettings()
    review = ReviewSettings(
        enabled=bool(r.get("enabled", defaults.enabled)),
        max_entries=int(r.get("max_entries", defaults.max_entries)),
        max_edit_chars=int(r.get("max_edit_chars", defaults.max_edit_chars)),
        max_edit_ratio=float(r.get("max_edit_ratio", defaults.max_edit_ratio)),
        max_text_len=int(r.get("max_text_len", defaults.max_text_len)),
    )
    return Settings(
        env=env,
        db_url=profile.get("db_url", "sqlite:///speclock.db"),
        host=profile.get("host", "127.0.0.1"),
        port=int(profile.get("port", 8000)),
        public_url=profile.get("public_url", ""),
        review=review,
    )
