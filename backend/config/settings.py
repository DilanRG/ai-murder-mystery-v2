"""
Global application settings.
Runtime constants and paths — not user preferences (see user_settings.py).
"""
import os
import sys
from pathlib import Path
from typing import Mapping

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_app_data_root(
    *,
    frozen: bool | None = None,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return a durable writable root for config, saves, and card drafts.

    Source checkouts retain their repo-local paths for developer convenience.
    A one-file PyInstaller build extracts bundled files to a temporary directory,
    so frozen apps instead use the operating system's per-user data location.
    ``ASHWICK_TRUST_DATA_DIR`` provides an explicit portable/test override.
    """

    environment = os.environ if environ is None else environ
    override = environment.get("ASHWICK_TRUST_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen:
        return BASE_DIR

    platform_id = sys.platform if platform_name is None else platform_name
    user_home = Path.home() if home is None else home
    if platform_id == "win32":
        local_app_data = environment.get("LOCALAPPDATA", "").strip()
        root = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return root / "AshwickTrust"
    if platform_id == "darwin":
        return user_home / "Library" / "Application Support" / "Ashwick Trust"

    xdg_data_home = environment.get("XDG_DATA_HOME", "").strip()
    root = Path(xdg_data_home) if xdg_data_home else user_home / ".local" / "share"
    return root / "ashwick-trust"


APP_DATA_ROOT = resolve_app_data_root()
CHARACTERS_DIR = BASE_DIR / "characters"
STATIC_DIR = BASE_DIR / "static"          # Vite-built frontend (production)
USER_CONFIG_FILE = APP_DATA_ROOT / "user_config.json"
SAVE_ROOT = APP_DATA_ROOT / "saves"
CARD_DRAFT_ROOT = APP_DATA_ROOT / "card_drafts"

# ── Server ───────────────────────────────────────────────────────────────────
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# ── LLM ─────────────────────────────────────────────────────────────────────
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-r1:free"  # Free default; user can change
DEFAULT_TEMPERATURE = 0.8
DEFAULT_TOP_P = 0.95
DEFAULT_TOP_K = 40
DEFAULT_MAX_TOKENS = 1024

# ── Game ─────────────────────────────────────────────────────────────────────
CAST_SIZE = 8              # Total characters per game (1 killer + 1 victim + 6 innocents)
MIN_LOCATIONS = 5
MAX_LOCATIONS = 8
MIN_CLUES = 6
MAX_CLUES = 10
MIN_RED_HERRINGS = 2
MAX_RED_HERRINGS = 4
