"""错误码：集中登记对外接口会返回的、稳定的机器可读错误类型。

错误响应是 ``{"detail": ..., "code": "..."}``：``detail`` 是给人看的中文文本（或带结构的对象），
措辞可能调整，**不要拿它做判断**；``code`` 是稳定的，外部集成方应当按它分支处理。

- 没有特别登记的错误，``code`` 由 HTTP 状态码给出通用值（见 ``GENERIC``）；
- 需要区分的情形（审核单状态不对、批准的哈希过期、版本被取代……）用 ``ApiError`` 带上专门的 ``code``；
- 新增 / 改名 / 删除一个 ``code`` 都是对外接口的变化：改这里的登记表，并在 CHANGELOG 记一条
  （``tests/test_error_codes.py`` 会核对登记表和代码里实际使用的 code 一致）。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

# code -> (HTTP 状态码, 含义)。同一个状态码可以有多个 code；外部集成方按 code 分支。
CODES: dict[str, tuple[int, str]] = {
    # ---- 通用（按状态码兜底） ----
    "bad_request": (400, "请求本身不合法（如 ref 写法不对）"),
    "unauthenticated": (401, "缺少 X-API-Key，或 key 不存在 / 已被吊销"),
    "permission_denied": (403, "这把 key 的角色缺少该接口需要的权限"),
    "not_found": (404, "对象不存在，或这把 key（项目隔离）无权访问——两者故意不区分"),
    "method_not_allowed": (405, "这个路径不支持该 HTTP 方法"),
    "conflict": (409, "与当前状态冲突（没有更具体的 code 时）"),
    "validation_failed": (422, "请求内容校验失败（字段缺失 / 类型不对 / 业务校验不通过）"),
    # ---- 审核单 ----
    "cr_state_conflict": (409, "审核单当前状态不允许这个操作（detail 里有当前状态）"),
    "cr_content_changed": (409, "批准时带的 content_hash 与审核单当前内容不一致（撤回并重新提交过）"),
    "cr_supersede_invalid": (409, "要取代的审核单不是 approved（只能取代已批准但未完成的）"),
    "cr_no_commits": (409, "审核单还没有任何 Commit，不能标记完成"),
    "cr_coverage_incomplete": (409, "仍有验收条件没有被任何 Commit 覆盖（detail.missing 列出缺哪几条）"),
    "cr_not_owner": (403, "草稿只有开单的那把 key（或管理员）能改、提交、撤回"),
    # ---- 执行记录 ----
    "work_superseded": (409, "这条记录针对的版本已被取代（detail.latest_work_id 指向最新的）"),
    "work_state_conflict": (409, "执行记录当前状态不允许这个操作"),
    "work_already_claimed": (409, "已被别人领取，进行中"),
    "work_not_holder": (403, "只有领取者能操作这条任务"),
    "work_surface_mismatch": (403, "这把 key 限定在某个端，这条执行记录属于别的端"),
    "work_verifier_is_implementer": (403, "验证者不能是实现者本人（同一把 key）"),
    # ---- 规格 / Commit ----
    "block_archived": (409, "模块已归档，不能在其上操作"),
    "delete_needs_approval": (409, "删除必须由本项目里人批准过的业务变更单授权（cr_id），且单子里点名了要删的东西"),
    "published_blocks_exist": (409, "下面还有已发布的模块，不能删除：先通过审核单归档它们（detail.published_blocks 列出哪些）"),
    # ---- 密钥 ----
    "project_required": (422, "除超级管理员 admin 外，所有角色的 key 都必须绑定项目（创建时传 project_id）"),
    "super_admin_required": (403, "只有超级管理员（admin）能做：项目管理员只能管本项目的 key，不能改角色、不能建权限比自己大的 key"),
    "web_project_required": (422, "库里有多个项目，网页要指明看哪一个（?project=<项目 id>）"),
    # ---- 其他 ----
    "local_only": (403, "这个接口只对本机地址开放（Host 不是 127.0.0.1 / localhost / ::1）"),
}

# 没有专门 code 时，按 HTTP 状态码给的通用 code
GENERIC: dict[int, str] = {400: "bad_request", 401: "unauthenticated", 403: "permission_denied",
                           404: "not_found", 405: "method_not_allowed", 409: "conflict",
                           422: "validation_failed"}


class ApiError(HTTPException):
    """带稳定错误码的 HTTPException。状态码以登记表为准，避免 code 和状态码对不上。"""

    def __init__(self, code: str, detail: Any):
        super().__init__(status_code=CODES[code][0], detail=detail)
        self.code = code


def code_of(exc: HTTPException) -> str:
    """一个 HTTPException 对外的错误码：显式带的优先，否则按状态码给通用值。"""
    explicit = getattr(exc, "code", None)
    if explicit:
        return explicit
    return GENERIC.get(exc.status_code, "error")
