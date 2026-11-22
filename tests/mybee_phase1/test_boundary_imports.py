from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "domains/mybee/mybee_ax"
FORBIDDEN_IMPORTS = {
    "nex_ae_api",
    "nex_ag",
    "nex_cx",
    "nex_eos",
    "nex_mo",
    "nex_oa",
    "nex_wa",
    "nex_wc",
    "psycopg",
    "sqlalchemy",
}
FORBIDDEN_TEXT = (
    "DATABASE_URL",
    "postgresql://",
    "postgresql+psycopg://",
)


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_mb0_01_domain_has_no_service_private_or_database_imports() -> None:
    sources = sorted(PACKAGE_ROOT.rglob("*.py"))
    assert sources

    violations = {
        path.relative_to(ROOT).as_posix(): sorted(_import_roots(path) & FORBIDDEN_IMPORTS)
        for path in sources
        if _import_roots(path) & FORBIDDEN_IMPORTS
    }
    assert violations == {}


def test_mb0_01_domain_has_no_embedded_database_connection() -> None:
    violations = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in FORBIDDEN_TEXT):
            violations.append(path.relative_to(ROOT).as_posix())
    assert violations == []


def test_mb0_01_does_not_create_a_second_service_or_runtime_tree() -> None:
    forbidden_paths = (
        ROOT / "domains/mybee/services",
        ROOT / "domains/mybee/runtime",
        ROOT / "domains/mybee/database",
        ROOT / "domains/mybee/migrations",
    )
    assert all(not path.exists() for path in forbidden_paths)
