"""架构约束（monorepo 的分层规则），违反就是 bug，不是风格问题。

1. 包之间只能向下依赖（见 ``ALLOWED``）；
2. 跨包导入必须走对方的 index（``from speclock_core import X``），不能深入子模块，
   且 ``X`` 必须出现在对方的 ``__all__`` 里；
3. 包内同样分层：核心里的模块只能依赖更低层的模块（见 ``CORE_LAYERS``）；
4. 各包 pyproject 里声明的 speclock-* 依赖，必须和代码里真实的导入一致；
5. 各包版本号一致。

「特定的部分可以依赖」：需要例外时，在 ``DEEP_IMPORT_EXCEPTIONS`` 里登记（写明理由），
不要悄悄绕过。tests/ 不受这些规则约束。
"""

from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGES_DIR = ROOT / "packages"

# 包 -> 它允许依赖的包（自下而上：config < core < server / mcp < cli < speclock）
ALLOWED: dict[str, set[str]] = {
    "speclock_config": set(),
    "speclock_core": {"speclock_config"},
    "speclock_server": {"speclock_config", "speclock_core"},
    "speclock_mcp": {"speclock_config"},
    "speclock_cli": {"speclock_config", "speclock_core", "speclock_server", "speclock_mcp"},
    "speclock": {"speclock_config", "speclock_core", "speclock_server", "speclock_mcp", "speclock_cli"},
}

# (导入方包, 被深入导入的模块) -> 理由。目前没有例外。
DEEP_IMPORT_EXCEPTIONS: dict[tuple[str, str], str] = {}

# 核心包内的分层：每一层只能依赖更低的层。
CORE_LAYERS: list[set[str]] = [
    {"db", "events", "diffing", "schemas"},
    {"models"},
    {"auth", "migrations", "permissions"},
    {"engine", "executions"},
    {"commits"},
    {"bootstrap"},
]


def _src(pkg: str) -> Path:
    d = pkg.removeprefix("speclock_") if pkg != "speclock" else "speclock"
    return PACKAGES_DIR / d / "src" / pkg


def _imports(path: Path):
    """(模块名, 被导入的名字列表) —— 包括函数体里的延迟导入。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, []


def _py_files(pkg: str):
    return sorted(p for p in _src(pkg).rglob("*.py"))


def _top(module: str) -> str:
    return module.split(".", 1)[0]


@pytest.mark.parametrize("pkg", sorted(ALLOWED))
def test_packages_only_depend_downwards(pkg):
    bad = []
    for path in _py_files(pkg):
        for module, _ in _imports(path):
            top = _top(module)
            if top.startswith("speclock") and top != pkg and top not in ALLOWED[pkg]:
                bad.append(f"{path.relative_to(ROOT)}: import {module}")
    assert not bad, f"{pkg} 不允许依赖这些包：\n" + "\n".join(bad)


@pytest.mark.parametrize("pkg", sorted(ALLOWED))
def test_cross_package_imports_go_through_the_index(pkg):
    bad = []
    for path in _py_files(pkg):
        for module, names in _imports(path):
            top = _top(module)
            if not top.startswith("speclock") or top == pkg:
                continue
            if module != top:
                if (pkg, module) not in DEEP_IMPORT_EXCEPTIONS:
                    bad.append(f"{path.relative_to(ROOT)}: from {module} import ... （应为 from {top} import ...）")
                continue
            exported = set(importlib.import_module(top).__all__)
            for name in names:
                if name not in exported:
                    bad.append(f"{path.relative_to(ROOT)}: {name} 不在 {top}.__all__ 里")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("pkg", sorted(ALLOWED))
def test_index_exports_resolve(pkg):
    mod = importlib.import_module(pkg)
    missing = [n for n in getattr(mod, "__all__", []) if not hasattr(mod, n)]
    assert not missing, f"{pkg}.__all__ 里这些名字取不到：{missing}"


def test_core_modules_only_import_lower_layers():
    rank = {m: i for i, layer in enumerate(CORE_LAYERS) for m in layer}
    on_disk = {p.stem for p in _py_files("speclock_core")} - {"__init__"}
    assert on_disk == set(rank), f"CORE_LAYERS 与实际模块不一致：{on_disk ^ set(rank)}"
    bad = []
    for path in _py_files("speclock_core"):
        if path.stem == "__init__":
            continue
        for module, names in _imports(path):
            if module == "speclock_core":
                targets = [n for n in names if n in rank]
            elif module.startswith("speclock_core."):
                targets = [module.split(".")[1]]
            else:
                continue
            for t in targets:
                if rank[t] >= rank[path.stem]:
                    bad.append(f"{path.name}（层 {rank[path.stem]}）依赖了 {t}（层 {rank[t]}）")
    assert not bad, "核心包内只能向下依赖：\n" + "\n".join(bad)


@pytest.mark.parametrize("pkg", sorted(ALLOWED))
def test_pyproject_dependencies_match_imports(pkg):
    d = pkg.removeprefix("speclock_") if pkg != "speclock" else "speclock"
    meta = tomllib.loads((PACKAGES_DIR / d / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        dep.replace("-", "_") for dep in meta["project"]["dependencies"] if dep.startswith("speclock-")
    }
    used = {
        _top(module)
        for path in _py_files(pkg)
        for module, _ in _imports(path)
        if _top(module).startswith("speclock") and _top(module) != pkg
    }
    if pkg == "speclock":  # 总装包：自己不导入子包的逻辑，但必须把它们都装上
        assert declared == ALLOWED[pkg] - {"speclock"}
    else:
        assert declared == used, f"{pkg}: pyproject 声明 {sorted(declared)}，代码实际用到 {sorted(used)}"


def test_all_packages_share_one_version():
    from speclock_config import __version__

    for pkg in ALLOWED:
        d = pkg.removeprefix("speclock_") if pkg != "speclock" else "speclock"
        meta = tomllib.loads((PACKAGES_DIR / d / "pyproject.toml").read_text(encoding="utf-8"))
        assert meta["project"]["version"] == __version__, f"{pkg} 的版本号和 speclock_config.__version__ 不一致"
