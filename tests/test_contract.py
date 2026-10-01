"""Checks the deployment contract from brief section 7 that Assignment 2 relies on."""

import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from app import create_app
from app.config import load_config

REPO_DIR = Path(__file__).resolve().parent.parent


def free_port() -> int:
    """Ask the OS for a port nobody is using, then let it go again."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get_status(url: str) -> int | None:
    """The HTTP status code, or None if nothing answered yet."""
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return None


def test_python_app_py_starts_and_reports_healthy(tmp_path):
    port = free_port()
    data_dir = tmp_path / "does" / "not" / "exist"
    env = dict(os.environ)
    env["PORT"] = str(port)
    env["DATA_DIR"] = str(data_dir)
    env["POLL_INTERVAL_SECONDS"] = "0"
    env["PRICE_API_KEY"] = ""  # never use a real key from my shell

    log_path = tmp_path / "app.log"
    with open(log_path, "w") as log:
        process = subprocess.Popen(
            [sys.executable, "app.py"], cwd=REPO_DIR, env=env, stdout=log, stderr=log
        )
        try:
            status = None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and process.poll() is None:
                status = get_status(f"http://127.0.0.1:{port}/health")
                if status is not None:
                    break
                time.sleep(0.1)

            assert status == 200, log_path.read_text()
            assert (data_dir / "app.db").is_file()
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_health_returns_503_without_details_when_a_table_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    config = load_config()
    client = create_app(config).test_client()
    assert client.get("/health").status_code == 200

    conn = sqlite3.connect(config.db_path)
    conn.execute("DROP TABLE alert_events")
    conn.close()

    response = client.get("/health")
    assert response.status_code == 503
    assert response.get_json() == {"status": "error"}


def test_no_container_ci_or_iac_files():
    for name in ("Dockerfile", "docker-compose.yml", "compose.yaml", ".github/workflows"):
        assert not (REPO_DIR / name).exists(), f"{name} must not exist"


def test_requirements_txt_is_the_only_manifest():
    assert (REPO_DIR / "requirements.txt").is_file()
    for name in ("package.json", "pyproject.toml", "uv.lock", "Pipfile", "setup.py"):
        assert not (REPO_DIR / name).exists(), f"{name} must not exist"


def test_no_env_or_database_file_is_tracked():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_DIR, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad = [path for path in tracked if Path(path).name == ".env" or path.endswith(".db")]
    assert bad == []


def test_code_has_no_forbidden_settings():
    paths = [REPO_DIR / "app.py"] + sorted((REPO_DIR / "app").rglob("*.py"))
    problems = []
    for path in paths:
        text = path.read_text()
        for banned in ("journal_mode", "FileHandler", "debug=True", "localhost", "127.0.0.1"):
            if banned in text:
                problems.append(f"{path.relative_to(REPO_DIR)} contains {banned}")
    assert problems == [], "\n".join(problems)
