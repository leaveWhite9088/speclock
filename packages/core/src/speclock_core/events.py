"""核心内部的轻量事件：让「发布」不必认识「执行记录」。

下层（engine / commits）只管发出事件，上层（executions）订阅并作出反应，
依赖方向因此永远是 订阅者 → events ← 发布者，不会有下层反过来 import 上层。

事件（参数都是 ``(db, block, actor)``，在发布者的事务里同步调用）：
- ``block.published``：模块发布了新版本；
- ``block.restored``：模块从归档恢复。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

BLOCK_PUBLISHED = "block.published"
BLOCK_RESTORED = "block.restored"

_handlers: dict[str, list[Callable]] = defaultdict(list)


def on(event: str, handler: Callable) -> None:
    """订阅事件（同一个 handler 重复订阅只算一次）。"""
    if handler not in _handlers[event]:
        _handlers[event].append(handler)


def emit(event: str, *args, **kwargs) -> None:
    for handler in list(_handlers[event]):
        handler(*args, **kwargs)
