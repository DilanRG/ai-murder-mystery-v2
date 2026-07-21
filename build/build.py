"""
Build script — Produces a single-file executable for AI Murder Mystery v2.

Steps:
  1. Build the Vite frontend → backend/static/
  2. Run PyInstaller → dist/ai-murder-mystery[.exe]
  3. Launch the artifact headlessly and exercise both cases plus save/load

Usage:
  python build/build.py              # Build for current platform
  python build/build.py --clean      # Clean dist/ and build/ first
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
STATIC = BACKEND / "static"
SPEC_FILE = ROOT / "build" / "murder-mystery.spec"
SMOKE_SCRIPT = ROOT / "build" / "smoke_packaged.py"
BUILD_REQUIREMENTS = BACKEND / "requirements-build.lock"
DIST = ROOT / "dist"


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    """Run a command, stream output, and raise on failure."""
    print(f"  > {' '.join(cmd)}")
    merged_env = {**os.environ, **(env or {})}
    # shell=True on Windows so that .cmd scripts (npm, npx) are found
    use_shell = platform.system() == "Windows"
    result = subprocess.run(cmd, cwd=str(cwd or ROOT), env=merged_env, shell=use_shell)
    if result.returncode != 0:
        print(f"  [FAIL] Command failed with exit code {result.returncode}")
        sys.exit(1)


def step_vite_build() -> None:
    """Build the Vite frontend into backend/static/."""
    print("\n[1/3] Building frontend with Vite...")
    if not (FRONTEND / "node_modules").exists():
        run(["npm", "ci"], cwd=FRONTEND)
    run(["npx", "vite", "build"], cwd=FRONTEND)
    if not (STATIC / "index.html").exists():
        print("  [FAIL] Vite build did not produce static/index.html")
        sys.exit(1)
    print("  [OK] Frontend built -> backend/static/")


def step_pyinstaller() -> Path:
    """Package the backend into a single-file executable with PyInstaller."""
    print("\n[2/3] Packaging with PyInstaller...")

    # Ensure pyinstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("  Installing hash-locked build dependencies...")
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(BUILD_REQUIREMENTS),
            ]
        )

    exe_name = "ai-murder-mystery" + (".exe" if platform.system() == "Windows" else "")
    exe_path = DIST / exe_name
    exe_path.unlink(missing_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "work"),
    ]
    print(f"  > {' '.join(cmd)}")
    merged_env = {**os.environ}
    use_shell = platform.system() == "Windows"
    # PyInstaller writes progress to stderr; capture it to avoid confusion
    result = subprocess.run(cmd, cwd=str(ROOT), env=merged_env, shell=use_shell,
                            stderr=subprocess.PIPE)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.decode("utf-8", errors="replace")[-3000:])
        print(f"  [FAIL] PyInstaller failed with exit code {result.returncode}")
        sys.exit(1)
    if not exe_path.is_file():
        print(f"  [FAIL] Expected executable not found: {exe_path}")
        if DIST.is_dir():
            for path in DIST.iterdir():
                print(f"    - {path.name}")
        sys.exit(1)

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"  [OK] Built: {exe_path}  ({size_mb:.1f} MB)")
    return exe_path


def step_packaged_smoke(executable: Path) -> None:
    """Exercise the executable itself before calling the build complete."""

    print("\n[3/3] Smoke-testing packaged executable...")
    run(
        [
            sys.executable,
            str(SMOKE_SCRIPT),
            "--executable",
            str(executable),
        ]
    )



def clean() -> None:
    """Remove build artifacts."""
    print("Cleaning build artifacts...")
    for d in [DIST, ROOT / "build" / "work"]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  Removed: {d}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AI Murder Mystery v2")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts before building")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip Vite frontend build")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip packaged executable smoke test")
    args = parser.parse_args()

    print("=" * 60)
    print("  AI Murder Mystery v2 -- Build Script")
    print(f"  Platform: {platform.system()} {platform.machine()}")
    print(f"  Python:   {sys.version.split()[0]}")
    print("=" * 60)

    if args.clean:
        clean()

    if not args.skip_frontend:
        step_vite_build()

    executable = step_pyinstaller()
    if not args.skip_smoke:
        step_packaged_smoke(executable)

    print("\n" + "=" * 60)
    print("  BUILD COMPLETE")
    print(f"  Output: {DIST}")
    print("=" * 60)


if __name__ == "__main__":
    main()
