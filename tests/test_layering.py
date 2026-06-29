"""ISC-0.2: core 레이어가 adapters/langgraph를 import하지 않음을 정적 검증."""

from __future__ import annotations

import ast
import os
from pathlib import Path


_PROJECT_ROOT = Path(__file__).parent.parent
_CORE_DIR = _PROJECT_ROOT / "stateful_guardrails" / "core"

# core가 절대 import해서는 안 되는 모듈 접두사 목록
_FORBIDDEN_PREFIXES = (
    "stateful_guardrails.adapters",
    "stateful_guardrails.pipeline",
    "stateful_guardrails.interfaces",
    "langgraph",
    "langchain",
)


def _collect_imports(source: str) -> list[str]:
    """AST로 파이썬 소스에서 import된 모듈명 목록을 반환한다."""
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def _check_file(path: Path) -> list[str]:
    """단일 파일에서 금지 import를 찾아 위반 메시지 목록을 반환한다."""
    source = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for module in _collect_imports(source):
        for prefix in _FORBIDDEN_PREFIXES:
            if module == prefix or module.startswith(prefix + "."):
                violations.append(f"{path.relative_to(_PROJECT_ROOT)}: '{module}' import 금지")
    return violations


def test_core_does_not_import_adapters_or_langgraph() -> None:
    """core/ 하위 모든 .py 파일이 adapters/pipeline/interfaces/langgraph를 import하지 않는다."""
    py_files = list(_CORE_DIR.rglob("*.py"))
    assert py_files, f"core 디렉토리에 파이썬 파일이 없음: {_CORE_DIR}"

    all_violations: list[str] = []
    for py_file in py_files:
        all_violations.extend(_check_file(py_file))

    assert not all_violations, (
        "core 레이어 의존성 위반 발견:\n" + "\n".join(f"  - {v}" for v in all_violations)
    )
