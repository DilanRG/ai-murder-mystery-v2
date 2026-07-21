"""Explicit opt-in DeepSeek V4 OpenRouter preflight; makes two tiny calls."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from config.user_settings import get_user_config, load_user_config
from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
    PRIVATE_ARTIFACT_ROOT,
    load_manifest,
    resolve_clean_git_sha,
    verify_preflights,
)
from experiments.deepseek_v4_runtime import (
    DeepSeekRequestObserver,
    RunContext,
    build_measured_client,
    run_tiny_openrouter_preflight,
)
from llm.experiment import DeepSeekExperimentLedger


def _atomic_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


async def main() -> int:
    if os.environ.get("AI_MYSTERY_ENABLE_DEEPSEEK_PREFLIGHT") != "1":
        raise RuntimeError("Set the explicit preflight enable flag to run provider traffic.")
    manifest = load_manifest()
    load_user_config()
    api_key = str(get_user_config().get("api_key", ""))
    if not api_key:
        raise RuntimeError("Configure the OpenRouter credential locally before preflight.")
    git_sha = resolve_clean_git_sha()

    artifact_root = PRIVATE_ARTIFACT_ROOT
    ledger = DeepSeekExperimentLedger(artifact_root / "cost_ledger.jsonl")
    baseline_client = build_measured_client(
        api_key=api_key,
        model=EXPECTED_MODELS["flash"],
        observer=DeepSeekRequestObserver(
            ledger=ledger,
            metrics_path=artifact_root / "requests.jsonl",
            context=RunContext(
                int(manifest["manifest_revision"]),
                git_sha,
                "preflight-baseline",
                "baseline",
            ),
        ),
    )
    baseline = await baseline_client.fetch_current_key_usage()
    _atomic_json(artifact_root / "key_usage_baseline.json", baseline)

    evidence: dict[str, object] = {}
    for model_key in ("flash", "pro"):
        observer = DeepSeekRequestObserver(
            ledger=ledger,
            metrics_path=artifact_root / "requests.jsonl",
            context=RunContext(
                int(manifest["manifest_revision"]),
                git_sha,
                f"preflight-{model_key}",
                "preflight",
            ),
        )
        client = build_measured_client(
            api_key=api_key,
            model=EXPECTED_MODELS[model_key],
            observer=observer,
        )
        await run_tiny_openrouter_preflight(client)
        record = observer.last_record
        if not isinstance(record, dict) or record.get("result") != "success":
            raise RuntimeError(f"{model_key} preflight did not produce verified evidence.")
        evidence[model_key] = {
            "experiment_revision": int(manifest["manifest_revision"]),
            "git_sha": git_sha,
            "model": record["actual_model"],
            "upstream_provider": record["upstream_provider"],
            "is_byok": record["is_byok"],
            "fallback_used": record["fallback_used"],
            "provider_failover_used": record["provider_failover_used"],
            "accounting_mode": record["accounting_mode"],
            "generation_id": record["generation_id"],
            "prompt_tokens": record["prompt_tokens"],
            "completion_tokens": record["completion_tokens"],
            "reasoning_tokens": record["reasoning_tokens"],
            "upstream_inference_cost_usd": record["upstream_inference_cost_usd"],
            "openrouter_fee_usd": record["openrouter_fee_usd"],
            "openrouter_charge_usd": record["openrouter_charge_usd"],
            "total_external_cost_usd": record["total_external_cost_usd"],
        }
    verify_preflights(evidence, manifest, expected_git_sha=git_sha)
    _atomic_json(artifact_root / "verified_preflights.json", evidence)
    snapshot = ledger.snapshot()
    print(
        json.dumps(
            {
                "verified": True,
                "models": {
                    key: {
                        "model": value["model"],
                        "provider": value["upstream_provider"],
                        "is_byok": value["is_byok"],
                        "fallback_used": value["fallback_used"],
                        "accounting_mode": value["accounting_mode"],
                    }
                    for key, value in evidence.items()
                },
                "settled_external_cost_usd": str(snapshot["settled_usd"]),
                "open_reservations": snapshot["open_reservations"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
