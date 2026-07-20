"""Authoritative turn-based murder-mystery domain.

This package is the replacement domain described by ``docs/project_brief.md``.
It intentionally lives beside the v2.0 prototype until the new engine has a
complete, tested vertical slice.
"""

from game.content import load_case, load_location
from game.models import CaseDefinition, LocationPackage, WorldRuntimeState

__all__ = [
    "CaseDefinition",
    "LocationPackage",
    "WorldRuntimeState",
    "load_case",
    "load_location",
]
