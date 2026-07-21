"""Safety boundary for the capped DeepSeek V4 evaluation.

This module deliberately contains no HTTP client and makes no provider calls.
It freezes the request configuration, validates the manifest in dry-run mode,
and exposes execution gates for a later production-adapter integration.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


EXPERIMENT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = EXPERIMENT_DIR / "deepseek_v4_manifest.json"
REPOSITORY_ROOT = EXPERIMENT_DIR.parents[1]
PRIVATE_ARTIFACT_ROOT = REPOSITORY_ROOT / ".private" / "deepseek_v4"
EXPECTED_MODELS = {
    "pro": "deepseek/deepseek-v4-pro",
    "flash": "deepseek/deepseek-v4-flash",
}
EXPECTED_RESOLVED_MODELS = {
    "pro": "deepseek/deepseek-v4-pro-20260423",
    "flash": "deepseek/deepseek-v4-flash-20260423",
}
EXPECTED_MANIFEST_REVISION = 3
EXPECTED_GIT_CHECKPOINT = "7aee11513c70eee562a0b606731afb2ae24ccaac"
EXPECTED_ROUTING = {
    "only": ["deepseek"],
    "allow_fallbacks": False,
    "require_parameters": True,
}


class ExperimentSafetyError(RuntimeError):
    """Raised before an unsafe, unverified, or over-budget request can start."""


@dataclass(frozen=True)
class ProviderRequest:
    """A sanitized, bounded request contract for a future adapter."""

    model: str
    provider: Mapping[str, Any]
    reasoning_effort: str
    max_tokens: int
    temperature: float
    sampler_defaults: Mapping[str, Any]
    json_mode: bool
    prompt_revision: str
    schema_revision: str


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Load and fully validate the committed, credential-free manifest."""

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSafetyError("Experiment manifest could not be read.") from error
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Reject changes that would make the paired measurement unfair or unsafe."""

    if manifest.get("manifest_revision") != EXPECTED_MANIFEST_REVISION:
        raise ExperimentSafetyError("Only frozen manifest revision 3 is accepted.")
    if manifest.get("git_checkpoint") != EXPECTED_GIT_CHECKPOINT:
        raise ExperimentSafetyError("Manifest must retain the revision-2 evaluator checkpoint.")
    if (
        manifest.get("supersedes_revision") != 2
        or manifest.get("gateway") != "openrouter"
        or manifest.get("model_fallbacks") != []
    ):
        raise ExperimentSafetyError("Manifest revision 3 must retain OpenRouter/DeepSeek routing provenance.")
    if manifest.get("models") != EXPECTED_MODELS:
        raise ExperimentSafetyError("Manifest model slugs must be the exact DeepSeek V4 pair.")
    if manifest.get("resolved_models") != EXPECTED_RESOLVED_MODELS:
        raise ExperimentSafetyError("Manifest must freeze OpenRouter's dated model resolutions.")
    if manifest.get("provider_routing") != EXPECTED_ROUTING:
        raise ExperimentSafetyError("Provider routing must match the frozen OpenRouter policy.")

    settings = manifest.get("runtime_settings")
    if not isinstance(settings, Mapping) or settings.get("reasoning_effort") != "high":
        raise ExperimentSafetyError("Both model cells require reasoning_effort=high.")
    if settings.get("generation_attempt_limit") != 3 or settings.get("concurrency") != 1:
        raise ExperimentSafetyError("Generation is limited to three attempts and sequential calls.")
    if dict(settings.get("sampler_defaults", {})) != {"top_p": 0.95, "top_k": None}:
        raise ExperimentSafetyError("Identical sampler defaults are required.")
    expected_roles = {
        "case_generation": (16_384, 0.55),
        "private_npc_action": (80, 0.0),
        "private_interview_selection": (80, 0.0),
        "portrayal": (220, 0.2),
    }
    roles = settings.get("roles")
    if not isinstance(roles, Mapping):
        raise ExperimentSafetyError("Every measured production role must be frozen.")
    for role, (max_tokens, temperature) in expected_roles.items():
        role_settings = roles.get(role)
        if not isinstance(role_settings, Mapping) or (
            role_settings.get("max_tokens"),
            role_settings.get("temperature"),
            role_settings.get("json_mode"),
        ) != (max_tokens, temperature, True):
            raise ExperimentSafetyError(
                f"Manifest settings for {role} differ from the production boundary."
            )

    budget = manifest.get("budget")
    if not isinstance(budget, Mapping) or (
        budget.get("total_external_api_usd"), budget.get("soft_stop_usd"),
        budget.get("hard_operational_stop_usd"), budget.get("reserved_uncertainty_usd"),
    ) != (10.0, 8.5, 9.5, 0.5):
        raise ExperimentSafetyError("Manifest budget thresholds differ from the approved cap.")
    if manifest.get("reservation_pricing_ceiling_usd_per_million") != {
        "pro": {"input": 5.0, "output": 10.0},
        "flash": {"input": 5.0, "output": 10.0},
    }:
        raise ExperimentSafetyError("Reservation price ceilings must remain conservative and frozen.")

    pairs = manifest.get("generation_pairs")
    if not isinstance(pairs, list) or [pair.get("pair_id") for pair in pairs] != ["P1", "P2", "P3"]:
        raise ExperimentSafetyError("Manifest must declare P1, P2, and P3 in frozen order.")
    all_seeds: set[int] = set()
    for pair in [*pairs, manifest.get("reserve_pair")]:
        _validate_pair(pair, all_seeds)
    reserve = manifest["reserve_pair"]
    if reserve.get("pair_id") != "R1":
        raise ExperimentSafetyError("Manifest reserve pair must be R1.")
    if [pair.get("model_order") for pair in pairs] != [["flash", "pro"], ["pro", "flash"], ["flash", "pro"]]:
        raise ExperimentSafetyError("Manifest must retain the declared alternating model order.")


def _validate_pair(pair: Any, all_seeds: set[int]) -> None:
    if not isinstance(pair, Mapping):
        raise ExperimentSafetyError("Each experiment pair must be an object.")
    seed = pair.get("seed")
    cast = pair.get("cast_ids")
    order = pair.get("model_order")
    if not isinstance(seed, int) or seed in all_seeds:
        raise ExperimentSafetyError("Each experiment pair needs a unique deterministic seed.")
    all_seeds.add(seed)
    if not isinstance(cast, list) or len(cast) != 8 or len(set(cast)) != 8:
        raise ExperimentSafetyError("Each experiment pair must contain eight distinct cards.")
    if sorted(order) != ["flash", "pro"]:
        raise ExperimentSafetyError("Each pair must measure both DeepSeek models exactly once.")


def build_request(manifest: Mapping[str, Any], model_key: str, *, task_role: str) -> ProviderRequest:
    """Build the bounded route for a case-generation or NPC-action request."""

    validate_manifest(manifest)
    if model_key not in EXPECTED_MODELS:
        raise ExperimentSafetyError("Only the manifest's Pro or Flash model may be selected.")
    settings = manifest["runtime_settings"]
    role_settings = settings["roles"].get(task_role)
    if not isinstance(role_settings, Mapping):
        raise ExperimentSafetyError("Experiment task role is not authorized.")
    return ProviderRequest(
        model=EXPECTED_MODELS[model_key],
        provider=dict(EXPECTED_ROUTING),
        reasoning_effort="high",
        max_tokens=int(role_settings["max_tokens"]),
        temperature=float(role_settings["temperature"]),
        sampler_defaults=dict(settings["sampler_defaults"]),
        json_mode=bool(role_settings["json_mode"]),
        prompt_revision=str(manifest["prompt_revision"]),
        schema_revision=str(manifest["schema_revision"]),
    )


def verify_preflights(
    evidence: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    expected_git_sha: str | None = None,
) -> None:
    """Require verified OpenRouter evidence for both exact models.

    The evidence format is intentionally small and sanitized: one entry under
    each model key with revision, model, serving provider, accounting mode,
    and model-fallback status.
    Generation IDs and costs may be retained in the ignored private artifact.
    """

    validate_manifest(manifest)
    for model_key, slug in EXPECTED_MODELS.items():
        record = evidence.get(model_key)
        if not isinstance(record, Mapping):
            raise ExperimentSafetyError("Both model preflights must be recorded before execution.")
        if record.get("experiment_revision") != EXPECTED_MANIFEST_REVISION:
            raise ExperimentSafetyError("Preflight belongs to a superseded experiment revision.")
        if record.get("model") != slug or not model_resolution_matches(
            slug, str(record.get("actual_model", ""))
        ) or str(record.get("upstream_provider", "")).casefold() != "deepseek":
            raise ExperimentSafetyError("Preflight did not verify the exact DeepSeek upstream model.")
        if record.get("is_byok") is not True or record.get("fallback_used") is not False:
            raise ExperimentSafetyError("Preflight did not verify DeepSeek BYOK without fallback.")
        if record.get("accounting_mode") != "byok":
            raise ExperimentSafetyError("Preflight did not verify BYOK accounting.")
        if not str(record.get("generation_id", "")):
            raise ExperimentSafetyError("Preflight did not retain a generation ID.")
        total_cost = record.get("total_external_cost_usd")
        if isinstance(total_cost, bool) or not isinstance(total_cost, (int, float)) or total_cost < 0:
            raise ExperimentSafetyError("Preflight did not retain trusted external cost.")
        if expected_git_sha is not None and record.get("git_sha") != expected_git_sha:
            raise ExperimentSafetyError("Preflight evidence belongs to a different code revision.")


def model_resolution_matches(requested_model: str, actual_model: str) -> bool:
    """Accept only an exact alias or its frozen dated OpenRouter resolution."""

    if requested_model not in EXPECTED_MODELS.values():
        return False
    model_key = next(key for key, value in EXPECTED_MODELS.items() if value == requested_model)
    return actual_model in {requested_model, EXPECTED_RESOLVED_MODELS[model_key]}


def load_private_preflights(path: Path) -> dict[str, Any]:
    """Read sensitive provider evidence only from the ignored private tree."""

    resolved_root = PRIVATE_ARTIFACT_ROOT.resolve()
    try:
        resolved_path = path.resolve()
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise ExperimentSafetyError("Preflight evidence must stay under .private/deepseek_v4.") from error
    try:
        return json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSafetyError("Private preflight evidence could not be read.") from error


def execute_with_verified_preflights(
    *,
    manifest: Mapping[str, Any],
    preflight_evidence: Mapping[str, Any],
    explicitly_enabled: bool,
    provider_call: Callable[[ProviderRequest], Any],
    request: ProviderRequest,
) -> Any:
    """Call an injected adapter only after all safety gates have passed.

    This is deliberately adapter-injected so this module cannot accidentally
    make network traffic.  A future integration must supply the production
    adapter and an explicit user-controlled opt-in.
    """

    if not explicitly_enabled:
        raise ExperimentSafetyError("Provider traffic requires an explicit opt-in.")
    verify_preflights(preflight_evidence, manifest)
    if request.model not in EXPECTED_MODELS.values() or dict(request.provider) != EXPECTED_ROUTING:
        raise ExperimentSafetyError("Request is not pinned to the approved OpenRouter route.")
    return provider_call(request)


def configured_openrouter_credential_present() -> bool:
    """Check only whether the normal environment config is present; never return it."""

    return bool(os.environ.get("OPENROUTER_API_KEY"))


def resolve_clean_git_sha(repository_root: Path = REPOSITORY_ROOT) -> str:
    """Return the measured revision, refusing a dirty or detached work product.

    The manifest intentionally retains the earlier technical-gate checkpoint.
    Runtime evidence must additionally identify the exact committed evaluator
    revision so a paid result cannot be attributed to uncommitted code.
    """

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            raise ExperimentSafetyError(
                "Provider traffic requires a clean committed experiment revision."
            )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ExperimentSafetyError("The committed experiment revision could not be resolved.") from error
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise ExperimentSafetyError("The committed experiment revision is not a full Git SHA.")
    return revision


def dry_run_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return a safe summary suitable for a console or committed test output."""

    validate_manifest(manifest)
    return {
        "experiment_id": manifest["experiment_id"],
        "manifest_revision": manifest["manifest_revision"],
        "pairs": [pair["pair_id"] for pair in manifest["generation_pairs"]],
        "reserve_pair": manifest["reserve_pair"]["pair_id"],
        "models": manifest["models"],
        "provider_routing": manifest["provider_routing"],
        "provider_calls_made": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the frozen DeepSeek V4 experiment manifest.")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; this is the default and makes no provider calls.")
    args = parser.parse_args(argv)
    del args  # Deliberately no key, endpoint, or execution CLI arguments exist.
    print(json.dumps(dry_run_summary(load_manifest()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
