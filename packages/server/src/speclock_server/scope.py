"""项目隔离：各路由共用的访问范围检查。"""

from __future__ import annotations

from fastapi import HTTPException

from speclock_core import ApiKey, Block


def check_project_scope(key: ApiKey, project_id: int) -> None:
    """项目隔离：绑定了项目的 agent key 只能访问本项目的小业务/模块。
    跨项目访问一律 404（与不存在同样表现，不泄露其他项目的存在）。
    project_id 为 None 的 key 是全局 key，不做隔离。"""
    if key.project_id is not None and key.project_id != project_id:
        raise HTTPException(status_code=404, detail="not found")


def block_project_id(block: Block) -> int:
    return block.capability.business.project_id
