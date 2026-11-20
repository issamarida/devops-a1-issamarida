"""Checks the import rules inside the watchlist service by reading the source with ast."""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
DOMAINS = ("app.watchlist", "app.market")


def module_name(path: Path) -> str:
    """app/alerts/service.py -> app.alerts.service, app/alerts/__init__.py -> app.alerts"""
    parts = list(path.relative_to(APP_DIR.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def resolve(package: str, level: int, module: str | None) -> str:
    """Turn "from ..x import y" inside package into an absolute name like app.x."""
    if level == 0:
        return module
    parts = package.split(".")
    parts = parts[: len(parts) - (level - 1)]
    if module:
        parts.append(module)
    return ".".join(parts)


def imports_of(path: Path) -> list[str]:
    """Every module the file imports, as absolute names."""
    module = module_name(path)
    # The package that "from . import x" is relative to.
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]

    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve(package, node.level, node.module)
            found.append(base)
            # "from app import watchlist" imports app.watchlist itself.
            found.extend(f"{base}.{alias.name}" for alias in node.names)
    return found


def is_within(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def all_modules() -> list[tuple[Path, str, list[str]]]:
    return [
        (path, module_name(path), imports_of(path))
        for path in sorted(APP_DIR.rglob("*.py"))
    ]


def check_forbidden(owner: str, forbidden: tuple[str, ...]) -> list[str]:
    problems = []
    for path, module, imports in all_modules():
        if not is_within(module, owner):
            continue
        for name in imports:
            if any(is_within(name, banned) for banned in forbidden):
                problems.append(f"{path.relative_to(APP_DIR.parent)} imports {name}")
    return sorted(set(problems))


def test_watchlist_does_not_import_market_or_ports():
    problems = check_forbidden("app.watchlist", ("app.market", "app.ports"))
    assert problems == [], "\n".join(problems)


def test_market_does_not_import_watchlist():
    problems = check_forbidden("app.market", ("app.watchlist",))
    assert problems == [], "\n".join(problems)


def test_nothing_here_imports_the_alerts_service():
    # The two services only meet over HTTP. Neither holds the other's code.
    problems = [
        f"{path.relative_to(APP_DIR.parent)} imports {name}"
        for path, _, imports in all_modules()
        for name in imports
        if is_within(name, "app.alerts") or "services" in name.split(".")
    ]
    assert problems == [], "\n".join(problems)


def test_only_create_app_imports_from_more_than_one_domain():
    problems = []
    for path, module, imports in all_modules():
        if module == "app":  # app/__init__.py, the composition root
            continue
        hits = sorted(
            {name for name in imports if any(is_within(name, d) for d in DOMAINS)}
        )
        domains = {d for d in DOMAINS if any(is_within(name, d) for name in hits)}
        if len(domains) >= 2:
            problems.append(
                f"{path.relative_to(APP_DIR.parent)} imports {', '.join(hits)}"
            )
    assert problems == [], "\n".join(problems)


def test_resolve_turns_relative_imports_into_absolute_names():
    # "from .repository import X" inside app.watchlist
    assert resolve("app.watchlist", 1, "repository") == "app.watchlist.repository"
    # "from ..market import cache" inside app.watchlist
    assert resolve("app.watchlist", 2, "market") == "app.market"
    # "from .. import market" inside app.watchlist
    assert resolve("app.watchlist", 2, None) == "app"
    assert resolve("app.watchlist", 0, "app.ports") == "app.ports"


def test_module_name_maps_files_to_modules():
    assert module_name(APP_DIR / "watchlist" / "service.py") == "app.watchlist.service"
    assert module_name(APP_DIR / "watchlist" / "__init__.py") == "app.watchlist"
    assert module_name(APP_DIR / "__init__.py") == "app"


def test_access_control_has_no_business_domain_imports():
    imports = imports_of(APP_DIR / "security.py")
    assert not any(is_within(name, domain) for name in imports for domain in DOMAINS)
