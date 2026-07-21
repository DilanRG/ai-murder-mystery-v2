"""Sanitize request evidence and compute small-sample descriptive summaries."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import json
import os
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
    ExperimentSafetyError,
    model_resolution_matches,
)


PUBLIC_REQUEST_FIELDS = (
    "schema_version",
    "experiment_revision",
    "git_sha",
    "run_id",
    "phase",
    "pair_id",
    "case_fingerprint",
    "task_role",
    "requested_model",
    "actual_model",
    "upstream_provider",
    "is_byok",
    "fallback_used",
    "provider_failover_used",
    "request_id",
    "transport_request_id",
    "generation_id",
    "started_at",
    "latency_seconds",
    "provider_latency",
    "prompt_tokens",
    "cached_prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
    "upstream_inference_cost_usd",
    "upstream_prompt_cost_usd",
    "upstream_completion_cost_usd",
    "openrouter_fee_usd",
    "openrouter_charge_usd",
    "total_external_cost_usd",
    "finish_reason",
    "native_finish_reason",
    "result",
    "accounting_status",
    "accounting_mode",
    "error_type",
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ExperimentSafetyError("Private request metrics could not be read.") from error
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExperimentSafetyError(
                f"Private request metrics line {line_number} is malformed."
            ) from error
        if not isinstance(record, dict):
            raise ExperimentSafetyError("Every request metric must be an object.")
        records.append(record)
    return records


def sanitize_request_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for record in records:
        model = record.get("requested_model")
        if model not in EXPECTED_MODELS.values():
            raise ExperimentSafetyError("Metrics contain an unapproved requested model.")
        if record.get("result") == "success" and (
            not model_resolution_matches(str(model), str(record.get("actual_model", "")))
            or str(record.get("upstream_provider", "")).casefold() != "deepseek"
            or record.get("is_byok") is not True
            or record.get("fallback_used") is not False
            or record.get("accounting_mode") != "byok"
        ):
            raise ExperimentSafetyError("Successful metrics do not prove exact DeepSeek BYOK routing.")
        sanitized.append(
            {
                field: record.get(field)
                for field in PUBLIC_REQUEST_FIELDS
                if field in record
            }
        )
    return sanitized


def export_sanitized_request_metrics(private_path: Path, public_path: Path) -> int:
    records = sanitize_request_records(_load_jsonl(private_path))
    public_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = public_path.with_suffix(public_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, public_path)
    return len(records)


def _sample(values: list[Decimal]) -> dict[str, object]:
    if not values:
        return {"sample_count": 0, "minimum": None, "median": None, "maximum": None}
    ordered = sorted(values)
    return {
        "sample_count": len(ordered),
        "minimum": format(ordered[0], "f"),
        "median": format(median(ordered), "f"),
        "maximum": format(ordered[-1], "f"),
    }


def summarize_request_metrics(records: Iterable[Mapping[str, Any]]) -> dict[str, object]:
    grouped_cost: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    grouped_latency: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    results: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in sanitize_request_records(records):
        key = (str(record["requested_model"]), str(record.get("task_role", "")))
        results[key][str(record.get("result", "unknown"))] += 1
        if record.get("total_external_cost_usd") is not None:
            grouped_cost[key].append(Decimal(str(record["total_external_cost_usd"])))
        if record.get("latency_seconds") is not None:
            grouped_latency[key].append(Decimal(str(record["latency_seconds"])))
    keys = sorted(set(results) | set(grouped_cost) | set(grouped_latency))
    return {
        "groups": [
            {
                "model": model,
                "task_role": role,
                "results": dict(sorted(results[(model, role)].items())),
                "external_cost_usd": _sample(grouped_cost[(model, role)]),
                "latency_seconds": _sample(grouped_latency[(model, role)]),
            }
            for model, role in keys
        ],
        "statistical_note": "Small samples report count, minimum, median, and maximum; no p90 is claimed.",
    }
