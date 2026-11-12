"""speclock_core —— 规格库的核心：模型、版本 / diff、发布引擎、Commit、执行记录、权限目录。

只依赖 speclock_config。上层包（server / cli）只能通过这里导出的名字使用它
（``from speclock_core import ...``），不要深入子模块。

包内的依赖顺序（只能向下依赖，由 tests/test_architecture.py 检查）：

    models → db → auth → permissions / diffing / schemas / events
           → engine / executions → commits → bootstrap
"""

# 先导入 executions：它在模块加载时订阅发布事件，必须在任何发布发生之前就位
from speclock_core import executions  # noqa: I001
from speclock_core import diffing, events, permissions
from speclock_core.auth import audit, hash_key, key_hint, new_key
from speclock_core.bootstrap import (
    ensure_web_key, ensure_web_keys, find_web_key, init_db, init_home, retire_legacy_web_keys,
)
from speclock_core.commits import apply_commit
from speclock_core.errors import CODES as ERROR_CODES, GENERIC as GENERIC_ERROR_CODES, ApiError, code_of
from speclock_core.db import Base, SessionLocal, configure, get_db, get_engine
from speclock_core.migrations import create_schema
from speclock_core.engine import published_version, publish_block
from speclock_core.permissions import (
    HUMAN_ONLY,
    PERMISSIONS,
    PRESET_ROLES,
    get_role,
    role_permissions,
    seed_roles,
    validate_role,
)
from speclock_core.models import (
    Project,
    Business,
    Capability,
    Block,
    BlockVersion,
    CapabilityVersion,
    ChangeRequest,
    Commit,
    ExecutionRecord,
    ExecutionEvent,
    Role,
    ApiKey,
    MigrationMark,
    AuditLog,
    utcnow,
)
from speclock_core.schemas import (
    StrictModel,
    ApiField,
    ApiEntry,
    ItemEntry,
    RenameRequest,
    ProjectCreate,
    KeyCreate,
    RoleCreate,
    RoleUpdate,
    CRCreate,
    CRUpdate,
    CRApprove,
    CRReject,
    CommitCreate,
    AcResult,
    WorkResults,
    WorkReason,
    ApiOp,
    ItemOp,
    IndexBlock,
    IndexCapability,
    IndexBusiness,
    Delta,
    BlockOut,
    PublishResult,
    CapabilityIndexEntry,
    CapabilityOut,
)

__all__ = [
    "executions",
    "diffing",
    "events",
    "permissions",
    "audit",
    "ApiError",
    "ERROR_CODES",
    "GENERIC_ERROR_CODES",
    "code_of",
    "hash_key",
    "key_hint",
    "new_key",
    "ensure_web_key",
    "ensure_web_keys",
    "find_web_key",
    "retire_legacy_web_keys",
    "init_db",
    "init_home",
    "apply_commit",
    "Base",
    "SessionLocal",
    "configure",
    "create_schema",
    "get_db",
    "get_engine",
    "published_version",
    "publish_block",
    "HUMAN_ONLY",
    "PERMISSIONS",
    "PRESET_ROLES",
    "get_role",
    "role_permissions",
    "seed_roles",
    "validate_role",
    "Project",
    "Business",
    "Capability",
    "Block",
    "BlockVersion",
    "CapabilityVersion",
    "ChangeRequest",
    "Commit",
    "ExecutionRecord",
    "ExecutionEvent",
    "Role",
    "ApiKey",
    "MigrationMark",
    "AuditLog",
    "utcnow",
    "StrictModel",
    "ApiField",
    "ApiEntry",
    "ItemEntry",
    "RenameRequest",
    "ProjectCreate",
    "KeyCreate",
    "RoleCreate",
    "RoleUpdate",
    "CRCreate",
    "CRUpdate",
    "CRApprove",
    "CRReject",
    "CommitCreate",
    "AcResult",
    "WorkResults",
    "WorkReason",
    "ApiOp",
    "ItemOp",
    "IndexBlock",
    "IndexCapability",
    "IndexBusiness",
    "Delta",
    "BlockOut",
    "PublishResult",
    "CapabilityIndexEntry",
    "CapabilityOut",
]
