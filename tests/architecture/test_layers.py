"""The layer rules of ADR-0001, checked on the imports of every source file."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "masar"

# A package may import only the packages listed for it. A package that is not listed fails the test,
# so a new package cannot be added without deciding where it belongs.
ALLOWED: dict[str, set[str]] = {
    "domain": set(),
    "ports": {"domain"},
    "agent": {"domain", "ports"},
    "app": {"domain", "ports", "agent"},
    "adapters": {"domain", "ports", "agent", "app"},
    "cli": {"domain", "ports", "agent", "app", "adapters"},
    "mcp_server": {"domain", "ports", "agent", "app", "adapters"},
    "templates": set(),  # data files only
}

# Third-party packages with a home. Anywhere else they are a mistake.
ONLY_IN: dict[str, set[str]] = {
    "langgraph": {"agent", "adapters"},  # adapters: the SQLite checkpointer
    "sqlite3": {"adapters"},
    "httpx": {"adapters"},
    "yaml": {"adapters"},
    "typer": {"cli"},
    "mcp": {"mcp_server"},
}

# The domain is pure: these would bring I/O, a clock or randomness into it.
FORBIDDEN_IN_DOMAIN = {
    "os",
    "pathlib",
    "socket",
    "subprocess",
    "time",
    "random",
    "uuid",
    "logging",
    "io",
    "shutil",
    "tempfile",
}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
        elif isinstance(node, ast.ImportFrom) and node.level > 0:
            # A relative import stays inside its own package; resolve it to check that.
            base = path.relative_to(SOURCE.parent).with_suffix("").parts[: -node.level]
            found.add(".".join((*base, *(node.module.split(".") if node.module else ()))))
    return found


def _files() -> list[tuple[str, Path]]:
    return [(path.relative_to(SOURCE).parts[0], path) for path in SOURCE.rglob("*.py") if path.parent != SOURCE]


def test_every_package_has_a_place_in_the_layers() -> None:
    packages = {package for package, _ in _files()}

    assert packages <= ALLOWED.keys(), f"add these packages to the layer table: {packages - ALLOWED.keys()}"


def test_a_package_imports_only_the_layers_below_it() -> None:
    problems = []
    for package, path in _files():
        for name in _imports(path):
            parts = name.split(".")
            if parts[0] == "masar" and len(parts) > 1 and parts[1] != package and parts[1] not in ALLOWED[package]:
                problems.append(f"{path.relative_to(SOURCE)} imports masar.{parts[1]}")

    assert not problems, "; ".join(sorted(problems))


def test_third_party_packages_stay_in_their_layer() -> None:
    problems = []
    for package, path in _files():
        for name in _imports(path):
            root = name.split(".")[0]
            if root in ONLY_IN and package not in ONLY_IN[root]:
                problems.append(f"{path.relative_to(SOURCE)} imports {root}")

    assert not problems, "; ".join(sorted(problems))


def test_the_domain_is_pure() -> None:
    problems = []
    for package, path in _files():
        if package != "domain":
            continue
        for name in _imports(path):
            root = name.split(".")[0]
            if root in FORBIDDEN_IN_DOMAIN or root in ONLY_IN:
                problems.append(f"{path.relative_to(SOURCE)} imports {root}")

    assert not problems, "; ".join(sorted(problems))


# Masar reads and prepares. It never acts on the outside world (ADR-0003): these modules would let it.
FORBIDDEN_EVERYWHERE = {
    "subprocess",
    "smtplib",
    "webbrowser",
    "ftplib",
    "telnetlib",
    "socket",
    "requests",
    "urllib.request",
}

# The use cases only a person may start. An assistant has no tool for them.
DECIDING_USE_CASES = ("decide", "approved_document", "move_application", "fetch")


def test_no_module_can_act_on_the_outside_world() -> None:
    problems = []
    for _, path in _files():
        for name in _imports(path):
            if name in FORBIDDEN_EVERYWHERE or name.split(".")[0] in FORBIDDEN_EVERYWHERE:
                problems.append(f"{path.relative_to(SOURCE)} imports {name}")

    assert not problems, "; ".join(sorted(problems))


def test_the_only_network_calls_are_a_get_to_a_job_board_and_a_post_to_a_model() -> None:
    calls = []
    for package, path in _files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = ast.unparse(node.func.value)
                if owner.endswith("_client") and node.func.attr not in ("close",):
                    method = ast.unparse(node.args[0]) if node.func.attr in ("stream", "request") else node.func.attr
                    calls.append((package, path.name, method))

    assert sorted(calls) == [("adapters", "boards.py", "'GET'"), ("adapters", "llm.py", "post")]


def test_the_mcp_server_never_calls_a_use_case_that_decides() -> None:
    called = set()
    for package, path in _files():
        if package != "mcp_server":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)

    assert called.isdisjoint(DECIDING_USE_CASES), called & set(DECIDING_USE_CASES)
    assert {"assess", "draft", "check_claims"} <= called  # and the test does see what the server calls
