"""
User preferences — persisted to disk (user_config.json).
Separate from settings.py which holds app-level constants.
"""
import json
import logging
from pathlib import Path
from typing import Any

from config.settings import (
    USER_CONFIG_FILE,
    DEFAULT_MODEL, DEFAULT_TEMPERATURE, DEFAULT_TOP_P,
    DEFAULT_TOP_K, DEFAULT_MAX_TOKENS,
)

logger = logging.getLogger(__name__)

# In-memory config cache
_config: dict[str, Any] = {}

DEFAULTS: dict[str, Any] = {
    "api_key": "",
    "model": DEFAULT_MODEL,
    "temperature": DEFAULT_TEMPERATURE,
    "top_p": DEFAULT_TOP_P,
    "top_k": DEFAULT_TOP_K,
    "max_tokens": DEFAULT_MAX_TOKENS,
    "autonomy": "high",        # "low" | "high"
    "timer_mode": "event",     # "none" | "realtime" | "event"
    "timer_minutes": 30,       # only used in "realtime" mode
    "difficulty": "normal",    # "easy" | "normal" | "hard"
}


def load_user_config() -> dict[str, Any]:
    """Load user config from disk into the in-memory cache."""
    global _config
    _config = dict(DEFAULTS)
    if USER_CONFIG_FILE.exists():
        try:
            with open(USER_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                _config.update(
                    {key: value for key, value in saved.items() if key in DEFAULTS}
                )
            logger.info("Loaded user config from %s", USER_CONFIG_FILE)
        except Exception as e:
            logger.warning("Failed to load user config: %s — using defaults", e)
    return _config


def get_user_config() -> dict[str, Any]:
    """Return the current in-memory config (load from disk if not yet loaded)."""
    if not _config:
        load_user_config()
    return dict(_config)


def save_user_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge updates into config and persist to disk."""
    global _config
    if not _config:
        load_user_config()
    _config.update(updates)
    try:
        USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(_config, f, indent=2)
        logger.info("User config saved.")
    except Exception as e:
        logger.error("Failed to save user config: %s", e)
    return dict(_config)
