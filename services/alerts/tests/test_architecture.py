"""Checks the import rules inside the alerts service by reading the source with ast."""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
DOMAINS = ("app.alerts",)


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


def test_nothing_here_imports_the_watchlist_service():
    # The two services only meet over HTTP. Neither holds the other's code.
    problems = [
        f"{path.relative_to(APP_DIR.parent)} imports {name}"
        for path, _, imports in all_modules()
        for name in imports
        if is_within(name, "app.watchlist")
        or is_within(name, "app.market")
        or "services" in name.split(".")
    ]
    assert problems == [], "\n".join(problems)


def test_the_http_client_is_the_only_module_that_talks_to_the_network():
    # One place to read to see every call that leaves this service.
    users = [
        module
        for _, module, imports in all_modules()
        if any(is_within(name, "requests") for name in imports)
    ]
    assert users == ["app.alerts.watchlist_client"]


def test_the_alerts_domain_reaches_the_watchlist_only_through_ports():
    # service.py knows the interfaces. Only the client knows there is HTTP behind them.
    problems = check_forbidden("app.alerts.service", ("app.alerts.watchlist_client", "requests"))
    problems += check_forbidden("app.alerts.rules", ("app.alerts.watchlist_client", "requests"))
    assert problems == [], "\n".join(problems)


def test_resolve_turns_relative_imports_into_absolute_names():
    # "from .repository import X" inside app.alerts
    assert resolve("app.alerts", 1, "repository") == "app.alerts.repository"
    # "from ..ports import X" inside app.alerts
    assert resolve("app.alerts", 2, "ports") == "app.ports"
    # "from .. import ports" inside app.alerts
    assert resolve("app.alerts", 2, None) == "app"
    assert resolve("app.alerts", 0, "app.ports") == "app.ports"


def test_module_name_maps_files_to_modules():
    assert module_name(APP_DIR / "alerts" / "service.py") == "app.alerts.service"
    assert module_name(APP_DIR / "alerts" / "__init__.py") == "app.alerts"
    assert module_name(APP_DIR / "__init__.py") == "app"


def test_access_control_has_no_business_domain_imports():
    imports = imports_of(APP_DIR / "security.py")
    assert not any(is_within(name, domain) for name in imports for domain in DOMAINS)
