"""
Build script — Produces a single-file executable for AI Murder Mystery v2.

Steps:
  1. Build the Vite frontend → backend/static/
  2. Run PyInstaller → dist/ai-murder-mystery[.exe]

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
    print("\n[1/2] Building frontend with Vite...")
    if not (FRONTEND / "node_modules").exists():
        run(["npm", "install"], cwd=FRONTEND)
    run(["npx", "vite", "build"], cwd=FRONTEND)
    if not (STATIC / "index.html").exists():
        print("  [FAIL] Vite build did not produce static/index.html")
        sys.exit(1)
    print("  [OK] Frontend built -> backend/static/")


def step_pyinstaller() -> None:
    """Package the backend into a single-file executable with PyInstaller."""
    import io
    print("\n[2/2] Packaging with PyInstaller...")

    # Ensure pyinstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("  Installing PyInstaller...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])

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
    # Don't trust the return code — check the file instead
    exe_name = "ai-murder-mystery" + (".exe" if platform.system() == "Windows" else "")
    exe_path = DIST / exe_name

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"  [OK] Built: {exe_path}  ({size_mb:.1f} MB)")
    else:
        # Something went wrong — print PyInstaller's stderr for diagnostics
        if result.stderr:
            print(result.stderr.decode("utf-8", errors="replace")[-3000:])
        print(f"  [FAIL] Expected executable not found: {exe_path}")
        for p in DIST.iterdir():
            print(f"    - {p.name}")
        sys.exit(1)



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

    step_pyinstaller()

    print("\n" + "=" * 60)
    print("  BUILD COMPLETE")
    print(f"  Output: {DIST}")
    print("=" * 60)


if __name__ == "__main__":
    main()
