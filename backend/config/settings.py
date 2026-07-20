"""
Global application settings.
Runtime constants and paths — not user preferences (see user_settings.py).
"""
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
CHARACTERS_DIR = BASE_DIR / "characters"
STATIC_DIR = BASE_DIR / "static"          # Vite-built frontend (production)
USER_CONFIG_FILE = BASE_DIR / "user_config.json"
SAVE_ROOT = BASE_DIR / "saves"

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
DEFAULT_CONTEXT_TOKENS = 8192

# ── Game ─────────────────────────────────────────────────────────────────────
CAST_SIZE = 8              # Total characters per game (1 killer + 1 victim + 6 innocents)
MIN_LOCATIONS = 5
MAX_LOCATIONS = 8
MIN_CLUES = 6
MAX_CLUES = 10
MIN_RED_HERRINGS = 2
MAX_RED_HERRINGS = 4
