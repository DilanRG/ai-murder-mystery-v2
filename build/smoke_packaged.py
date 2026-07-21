"""Launch the built executable and exercise its real bundled HTTP surface."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXECUTABLE = ROOT / "dist" / (
    "ai-murder-mystery.exe" if sys.platform == "win32" else "ai-murder-mystery"
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request_json(
    base_url: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    body = None
    headers: dict[str, str] = {}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {error.code}: {detail}") from error


def _wait_for_health(base_url: str, process: subprocess.Popen[object]) -> None:
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"packaged server exited with code {process.returncode}")
        try:
            health = _request_json(base_url, "/api/health")
            if health.get("status") == "ok":
                return
        except (OSError, RuntimeError) as error:
            last_error = error
        time.sleep(0.2)
    raise RuntimeError(f"packaged server did not become healthy: {last_error}")


def smoke(executable: Path) -> None:
    if not executable.is_file():
        raise FileNotFoundError(f"packaged executable was not found: {executable}")

    with tempfile.TemporaryDirectory(prefix="ashwick-packaged-smoke-") as data_dir:
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        environment = dict(os.environ)
        environment["ASHWICK_TRUST_DATA_DIR"] = data_dir
        log_path = Path(data_dir) / "server.log"
        creation_flags = (
            subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        with log_path.open("w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(executable), "--no-browser", "--port", str(port)],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
            try:
                _wait_for_health(base_url, process)
                catalog = _request_json(base_url, "/api/game/catalog")
                if len(catalog.get("characters", [])) != 8:
                    raise RuntimeError("packaged catalog did not load all eight CCv3 cards")
                if catalog.get("recipes", [{}])[0].get("variation_count") != 2:
                    raise RuntimeError("packaged catalog did not load both case spines")

                for case_id in ("ashwick_sample", "ashwick_quiet_vow"):
                    started = _request_json(
                        base_url,
                        "/api/game/new",
                        {"case_id": case_id, "location_id": "ashwick_manor"},
                    )
                    if started.get("game", {}).get("phase") != "discovery":
                        raise RuntimeError(f"packaged case failed to start: {case_id}")

                action = _request_json(
                    base_url,
                    "/api/game/action",
                    {"kind": "advance_opening"},
                )
                if not action.get("accepted"):
                    raise RuntimeError("packaged game rejected its opening action")
                saved = _request_json(
                    base_url,
                    "/api/game/saves/v2",
                    {"filename": "packaged-smoke.json"},
                )
                if saved.get("schema_version") != 2:
                    raise RuntimeError("packaged game did not write a v2 save")
                save_path = Path(data_dir) / "saves" / "packaged-smoke.json"
                if not save_path.is_file():
                    raise RuntimeError("packaged save was not written to user data")
                loaded = _request_json(
                    base_url,
                    "/api/game/saves/v2/packaged-smoke.json/load",
                    {},
                )
                if loaded.get("status") != "loaded":
                    raise RuntimeError("packaged v2 save did not reload")
            except Exception:
                log.flush()
                log.seek(0)
                output = log.read()[-4_000:]
                if output:
                    print(output, file=sys.stderr)
                raise
            finally:
                if sys.platform == "win32" and process.poll() is None:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                elif process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--executable",
        type=Path,
        default=DEFAULT_EXECUTABLE,
        help="Path to the packaged executable to exercise.",
    )
    options = parser.parse_args()
    smoke(options.executable.resolve())
    print(f"[OK] Packaged smoke passed: {options.executable}")


if __name__ == "__main__":
    main()
