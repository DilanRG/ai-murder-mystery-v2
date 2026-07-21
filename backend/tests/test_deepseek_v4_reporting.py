"""Sanitized public metrics and small-sample reporting tests."""

from __future__ import annotations

import json

from experiments.deepseek_v4_reporting import (
    export_sanitized_request_metrics,
    sanitize_request_records,
    summarize_request_metrics,
)
from llm.experiment import PRO_MODEL_SLUG


def _record(cost: float, latency: float) -> dict[str, object]:
    return {
        "schema_version": 1,
        "experiment_revision": 5,
        "git_sha": "e" * 40,
        "run_id": "generation-P1-pro",
        "phase": "generation",
        "pair_id": "P1",
        "task_role": "case_generation",
        "requested_model": PRO_MODEL_SLUG,
        "actual_model": PRO_MODEL_SLUG,
        "upstream_provider": "deepseek",
        "transport": "deepseek_direct",
        "is_byok": None,
        "fallback_used": False,
        "provider_failover_used": False,
        "request_id": "safe-request-id",
        "generation_id": "safe-generation-id",
        "started_at": "2026-07-21T00:00:00+00:00",
        "latency_seconds": latency,
        "total_external_cost_usd": cost,
        "openrouter_fee_usd": 0.0,
        "result": "success",
        "accounting_status": "measured",
        "accounting_mode": "direct_token_meter",
        "api_key": "must-not-survive",
        "prompt": "private truth must not survive",
        "private_overlay": {"secret": "must-not-survive"},
    }


def test_metrics_export_uses_strict_allowlist_and_never_copies_private_fields(tmp_path) -> None:
    private = tmp_path / "private.jsonl"
    public = tmp_path / "public.jsonl"
    private.write_text(json.dumps(_record(0.1, 2.0)) + "\n", encoding="utf-8")

    assert export_sanitized_request_metrics(private, public) == 1
    exported = public.read_text(encoding="utf-8")
    assert "safe-generation-id" in exported
    assert "must-not-survive" not in exported
    assert "api_key" not in exported
    assert "private_overlay" not in exported
    assert "prompt\"" not in exported


def test_summary_reports_min_median_max_without_fake_p90() -> None:
    records = [_record(0.3, 3.0), _record(0.1, 1.0), _record(0.2, 2.0)]

    summary = summarize_request_metrics(records)
    group = summary["groups"][0]
    assert group["external_cost_usd"] == {
        "sample_count": 3,
        "minimum": "0.1",
        "median": "0.2",
        "maximum": "0.3",
    }
    assert group["latency_seconds"]["median"] == "2.0"
    assert "p90" not in group
    assert len(sanitize_request_records(records)) == 3
