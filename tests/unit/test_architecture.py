"""Layering and safety rules, checked against the source tree.

These read the code rather than run it, so a rule cannot be satisfied by a
test double. Known exceptions are listed exactly: a new violation fails, and so
does an exception that no longer exists, so the lists only shrink.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOTS = ("apps", "libs", "connectors")
APPS = {
    "aeropulse_api",
    "aeropulse_citizen_analyzer",
    "aeropulse_connector_app",
    "aeropulse_cycle",
    "aeropulse_worker",
}
LANGUAGE_MODEL_MODULES = ("google.genai", "google.generativeai", "openai", "anthropic")
LLM_LIBS = {"aeropulse_copilot", "aeropulse_vision"}
# Detection, anomaly, likelihood, forecast, plume, graph and events.
EVENT_PATH = {
    "aeropulse_contracts",
    "aeropulse_cycle",
    "aeropulse_geospatial",
    "aeropulse_intelligence",
    "aeropulse_ml",
    "aeropulse_regions",
    "aeropulse_storage",
}

# The legacy worker and connector app; both go when the worker is retired.
APP_IMPORT_EXCEPTIONS = {
    ("apps/api/aeropulse_api/routers/sources.py", "aeropulse_connector_app.registry"),
    ("apps/api/aeropulse_api/routers/sources.py", "aeropulse_connector_app.runner"),
    ("apps/api/aeropulse_api/source_registry.py", "aeropulse_connector_app.registry"),
    ("apps/connector/aeropulse_connector_app/runner.py", "aeropulse_worker.db"),
}
GEMINI_ADAPTERS = {
    "libs/copilot/aeropulse_copilot/gemini.py",
    "libs/vision/aeropulse_vision/gemini.py",
}


def _python_files() -> Iterator[Path]:
    for root in PYTHON_ROOTS:
        for path in sorted((ROOT / root).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def _package(path: Path) -> str:
    return next((p for p in path.parts if p.startswith("aeropulse_")), "")


def _imports(path: Path) -> Iterator[str]:
    """Absolute modules a file imports, at any depth (lazy imports count)."""
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def test_apps_do_not_import_each_other() -> None:
    found = set()
    for path in _python_files():
        own = _package(path)
        for module in _imports(path):
            top = module.split(".")[0]
            if top in APPS and top != own and module.count(".") <= 1:
                found.add((_rel(path), module))

    assert found - APP_IMPORT_EXCEPTIONS == set(), "new import of another app"
    assert APP_IMPORT_EXCEPTIONS - found == set(), "exception no longer needed: remove it"


def test_only_the_copilot_and_vision_adapters_import_a_language_model() -> None:
    importers = {
        _rel(path)
        for path in _python_files()
        if any(_is_under(m, llm) for m in _imports(path) for llm in LANGUAGE_MODEL_MODULES)
    }

    assert importers == GEMINI_ADAPTERS


def test_the_event_path_imports_no_language_model_code() -> None:
    offenders = sorted(
        f"{_rel(path)} -> {module}"
        for path in _python_files()
        if _package(path) in EVENT_PATH or _package(path).startswith("aeropulse_connector_")
        for module in _imports(path)
        if module.split(".")[0] in LLM_LIBS
        or any(_is_under(module, llm) for llm in LANGUAGE_MODEL_MODULES)
    )

    assert offenders == []


def test_running_a_cycle_loads_no_language_model_module() -> None:
    probe = (
        "import json, sys\n"
        "import aeropulse_cycle.main, aeropulse_cycle.cycle\n"
        f"bad = {sorted(LLM_LIBS | set(LANGUAGE_MODEL_MODULES))!r}\n"
        "print(json.dumps(sorted(m for m in sys.modules\n"
        "    if any(m == b or m.startswith(b + '.') for b in bad))))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=ROOT
    )

    assert json.loads(out.stdout) == []


def test_no_broad_exception_is_silently_swallowed() -> None:
    swallowed = []
    for path in [*_python_files(), *sorted((ROOT / "scripts").rglob("*.py"))]:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or ast.unparse(node.type) in {"Exception", "BaseException"}
            silent = all(
                isinstance(s, ast.Pass)
                or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                for s in node.body
            )
            if broad and silent:
                swallowed.append(f"{_rel(path)}:{node.lineno}")

    assert swallowed == []


WEB = ROOT / "frontend" / "web" / "src"
# Requests that are not to the AeroPulse API, and so must not carry its token.
FOREIGN_FETCHES = {
    "api/regions.ts",  # PUT to a signed Cloud Storage URL
    "components/map/basemapStyle.ts",  # the CARTO basemap style
}


def _web_files() -> Iterator[tuple[str, str]]:
    for path in sorted(WEB.rglob("*")):
        if path.suffix in {".ts", ".tsx"}:
            yield path.relative_to(WEB).as_posix(), path.read_text()


def test_the_frontend_has_one_http_client() -> None:
    callers = {name for name, text in _web_files() if re.search(r"\bfetch\(", text)}

    assert callers == {"api/client.ts", *FOREIGN_FETCHES}
    assert not any(re.search(r"XMLHttpRequest|from 'axios'", t) for _, t in _web_files())


def test_the_frontend_has_one_demo_live_branch() -> None:
    choosers = {
        name
        for name, text in _web_files()
        if re.search(r"\b(recordingTransport|httpTransport)\b", text)
    }

    assert choosers == {"api/transport.ts", "services/resolve.ts"}


SECRET_SHAPES = re.compile(
    r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[0-9A-Za-z]{20,}|"
    r"eyJ[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\.|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"sk_(live|test)_[0-9A-Za-z]{10,}"
)


def _strings(node: object) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                yield str(key), value
            else:
                yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


def test_config_holds_secret_references_never_values() -> None:
    findings = []
    for path in sorted((ROOT / "config").rglob("*.yaml")):
        text = path.read_text()
        if SECRET_SHAPES.search(text):
            findings.append(f"{_rel(path)}: credential-shaped value")
        for key, value in _strings(yaml.safe_load(text)):
            if re.search(r"(secret|token|password|api_key)", key, re.I) and not re.fullmatch(
                r"(secret_ref|auth_ref)", key
            ):
                findings.append(f"{_rel(path)}: {key} holds a value")
            if key in {"secret_ref", "auth_ref"} and not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*|env:[A-Z0-9_]+|projects/[^/]+/secrets/[^/]+", value
            ):
                findings.append(f"{_rel(path)}: {key} is not a reference")

    assert findings == []


SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".json", ".yaml", ".yml", ".sql", ".toml", ".md"}


@pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout"
)
def test_no_source_file_is_hidden_by_gitignore() -> None:
    roots = ["apps", "libs", "connectors", "config", "tests", "scripts", "frontend/web/src"]
    out = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--", *roots],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    hidden = [
        line
        for line in out.stdout.splitlines()
        if Path(line).suffix in SOURCE_SUFFIXES
        and "__pycache__" not in line
        and ".egg-info" not in line
    ]

    assert hidden == []
