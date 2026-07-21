"""Release packaging and writable-path contract tests."""

from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from config.settings import BASE_DIR, resolve_app_data_root
from launcher import parse_launcher_args


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_build_script():
    spec = importlib.util.spec_from_file_location(
        "ashwick_build_script",
        REPO_ROOT / "build" / "build.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_mode_keeps_repo_local_data_unless_overridden() -> None:
    assert resolve_app_data_root(frozen=False, environ={}) == BASE_DIR
    assert resolve_app_data_root(
        frozen=False,
        environ={"ASHWICK_TRUST_DATA_DIR": "D:/portable-ashwick"},
    ) == Path("D:/portable-ashwick")


def test_frozen_build_uses_platform_user_data_directories() -> None:
    assert resolve_app_data_root(
        frozen=True,
        platform_name="win32",
        environ={"LOCALAPPDATA": "C:/Users/Ada/AppData/Local"},
        home=Path("C:/Users/Ada"),
    ) == Path("C:/Users/Ada/AppData/Local/AshwickTrust")
    assert resolve_app_data_root(
        frozen=True,
        platform_name="linux",
        environ={"XDG_DATA_HOME": "/var/lib/ada"},
        home=Path("/home/ada"),
    ) == Path("/var/lib/ada/ashwick-trust")
    assert resolve_app_data_root(
        frozen=True,
        platform_name="darwin",
        environ={},
        home=Path("/Users/ada"),
    ) == Path("/Users/ada/Library/Application Support/Ashwick Trust")


def test_pyinstaller_spec_bundles_current_authored_content() -> None:
    spec = (REPO_ROOT / "build" / "murder-mystery.spec").read_text(
        encoding="utf-8"
    )
    assert "CONTENT = BACKEND / 'content'" in spec
    assert "(str(CONTENT), 'content')" in spec


def test_release_and_local_build_use_reproducible_node_install() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    build_script = (REPO_ROOT / "build" / "build.py").read_text(encoding="utf-8")
    assert "run: npm ci" in workflow
    assert 'run(["npm", "ci"]' in build_script
    assert "PyInstaller failed with exit code" in build_script
    assert "step_packaged_smoke(executable)" in build_script
    assert "python build/build.py --skip-frontend" in workflow


def test_packaged_launcher_supports_headless_smoke_mode_and_validates_ports() -> None:
    options = parse_launcher_args(["--no-browser", "--port", "8790"])
    assert options.no_browser is True
    assert options.port == 8790

    for invalid_port in ("-1", "0", "65536", "a-million"):
        with pytest.raises(SystemExit):
            parse_launcher_args(["--port", invalid_port])


def test_failed_packager_cannot_reuse_a_stale_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_script = _load_build_script()
    executable = tmp_path / (
        "ai-murder-mystery.exe" if platform.system() == "Windows" else "ai-murder-mystery"
    )
    executable.write_bytes(b"stale")
    monkeypatch.setattr(build_script, "DIST", tmp_path)
    monkeypatch.setattr(build_script, "SPEC_FILE", tmp_path / "missing.spec")
    monkeypatch.setitem(sys.modules, "PyInstaller", object())
    monkeypatch.setattr(
        build_script.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr=b"failed"),
    )

    with pytest.raises(SystemExit):
        build_script.step_pyinstaller()
    assert not executable.exists()


def test_nonzero_packager_exit_rejects_even_a_new_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_script = _load_build_script()
    executable = tmp_path / (
        "ai-murder-mystery.exe" if platform.system() == "Windows" else "ai-murder-mystery"
    )
    monkeypatch.setattr(build_script, "DIST", tmp_path)
    monkeypatch.setattr(build_script, "SPEC_FILE", tmp_path / "broken.spec")
    monkeypatch.setitem(sys.modules, "PyInstaller", object())

    def fail_after_writing(*args, **kwargs):
        executable.write_bytes(b"partial")
        return SimpleNamespace(returncode=7, stderr=b"failed after writing")

    monkeypatch.setattr(build_script.subprocess, "run", fail_after_writing)
    with pytest.raises(SystemExit):
        build_script.step_pyinstaller()
