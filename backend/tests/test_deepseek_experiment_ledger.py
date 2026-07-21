"""Provider-free tests for the DeepSeek evaluation cost guardrail."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json

import pytest

from llm.experiment import (
    BudgetStop,
    DeepSeekExperimentLedger,
    ExperimentPolicy,
    ExperimentPolicyError,
    HardBudgetStop,
    LedgerIntegrityError,
    ModelPricing,
    SoftBudgetStop,
    PRO_MODEL_SLUG,
    FLASH_MODEL_SLUG,
)


def _policy(*, soft: str = "8.50", hard: str = "9.50", reserve: str = "0.50") -> ExperimentPolicy:
    return ExperimentPolicy(
        soft_stop_usd=Decimal(soft),
        hard_stop_usd=Decimal(hard),
        uncertainty_reserve_usd=Decimal(reserve),
        pricing={
            PRO_MODEL_SLUG: ModelPricing(Decimal("100"), Decimal("100")),
            FLASH_MODEL_SLUG: ModelPricing(Decimal("10"), Decimal("10")),
        },
        openrouter_fee_rate=Decimal("0"),
    )


def _reserve(ledger: DeepSeekExperimentLedger, **extra: object):
    request = {
        "provider": "openrouter",
        "model": PRO_MODEL_SLUG,
        "prompt_tokens_upper_bound": 10_000,
        "max_output_tokens": 10_000,
        "parameters": {"temperature": 0},
        "reasoning": "high",
        "allow_fallbacks": True,
    }
    request.update(extra)
    return ledger.reserve(**request)  # type: ignore[arg-type]


def test_policy_is_exact_and_rejects_unbounded_or_fallback_requests(tmp_path):
    ledger = DeepSeekExperimentLedger(tmp_path / "ledger.jsonl", _policy())
    with pytest.raises(ExperimentPolicyError, match="exact approved"):
        _reserve(ledger, model="deepseek-v4-pro")
    with pytest.raises(ExperimentPolicyError, match="failover"):
        _reserve(ledger, allow_fallbacks=False)
    with pytest.raises(ExperimentPolicyError, match="parameters"):
        _reserve(ledger, parameters={})
    with pytest.raises(ExperimentPolicyError, match="reasoning"):
        _reserve(ledger, reasoning="medium")


def test_soft_and_hard_stops_are_conservative(tmp_path):
    # Pro estimate is $2.00 (20k tokens at $100/M) plus $0.50 reserve.
    soft = DeepSeekExperimentLedger(tmp_path / "soft.jsonl", _policy(soft="2.50", hard="9.50"))
    with pytest.raises(SoftBudgetStop):
        _reserve(soft)

    hard = DeepSeekExperimentLedger(tmp_path / "hard.jsonl", _policy(soft="1.00", hard="2.50"))
    with pytest.raises(HardBudgetStop):
        _reserve(hard)


def test_settlement_uses_separate_trusted_components_without_double_counting(tmp_path):
    ledger = DeepSeekExperimentLedger(tmp_path / "ledger.jsonl", _policy())
    reservation = _reserve(ledger)
    settlement = ledger.settle(
        reservation,
        upstream_cost_usd="0.210000001",
        openrouter_fee_usd="0.020000001",
        accounting_trusted=True,
    )
    assert settlement.total_cost_usd == Decimal("0.23000002")
    assert ledger.snapshot()["settled_usd"] == Decimal("0.23000002")
    assert ledger.snapshot()["reserved_usd"] == Decimal("0")
    with pytest.raises(LedgerIntegrityError, match="already"):
        ledger.settle(reservation, upstream_cost_usd="0", openrouter_fee_usd="0", accounting_trusted=True)
    with pytest.raises(ExperimentPolicyError, match="untrusted"):
        ledger.settle("f" * 32, upstream_cost_usd="0", openrouter_fee_usd="0", accounting_trusted=False)


def test_standard_openrouter_charge_is_not_double_counted(tmp_path):
    ledger = DeepSeekExperimentLedger(tmp_path / "ledger.jsonl", _policy())
    reservation = _reserve(ledger)

    settlement = ledger.settle_openrouter_charge(
        reservation,
        openrouter_charge_usd="0.123456789",
        accounting_trusted=True,
    )

    assert settlement.upstream_cost_usd == Decimal("0E-8")
    assert settlement.total_cost_usd == Decimal("0.12345679")
    assert ledger.snapshot()["settled_usd"] == Decimal("0.12345679")


def test_concurrent_reservations_cannot_oversubscribe_soft_ceiling(tmp_path):
    # Each reservation costs $2; reserve leaves $4.50 before a $5 soft stop,
    # so exactly two win even when many independent instances race.
    path = tmp_path / "ledger.jsonl"
    policy = _policy(soft="5.00", hard="9.50")

    def reserve_once(_: int) -> bool:
        try:
            _reserve(DeepSeekExperimentLedger(path, policy))
        except BudgetStop:
            return False
        return True

    with ThreadPoolExecutor(max_workers=12) as executor:
        outcomes = list(executor.map(reserve_once, range(24)))
    assert outcomes.count(True) == 2
    assert DeepSeekExperimentLedger(path, policy).snapshot()["reserved_usd"] == Decimal("4.00000000")


def test_malformed_or_inconsistent_persistent_ledger_is_rejected(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match="malformed"):
        DeepSeekExperimentLedger(path, _policy())

    request_id = "a" * 32
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "schema_version": 1, "kind": "reservation", "request_id": request_id,
                    "provider": "deepseek", "model": PRO_MODEL_SLUG, "prompt_tokens_upper_bound": 1,
                    "max_output_tokens": 1, "reserved_usd": "0.00000001",
                },
                {
                    "schema_version": 1, "kind": "settlement", "request_id": request_id,
                    "upstream_cost_usd": "0.1", "openrouter_fee_usd": "0.2", "total_cost_usd": "0.4",
                },
            )
        ) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LedgerIntegrityError, match="double-counted"):
        DeepSeekExperimentLedger(path, _policy())


def test_metrics_are_append_only_one_per_request_and_never_include_parameters(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = DeepSeekExperimentLedger(path, _policy())
    secret = "sk-private-prompt-and-npc-overlay"
    reservation = ledger.reserve(
        provider="openrouter",
        model=FLASH_MODEL_SLUG,
        prompt_tokens_upper_bound=4,
        max_output_tokens=5,
        parameters={"api_key": secret, "prompt": secret, "private_state": secret},
        reasoning="high",
        allow_fallbacks=True,
    )
    ledger.settle(reservation, upstream_cost_usd="0.01", openrouter_fee_usd="0.002", accounting_trusted=True)
    metric_rows = [json.loads(line) for line in ledger.metrics_path.read_text(encoding="utf-8").splitlines()]
    assert len(metric_rows) == 1
    assert metric_rows[0]["model"] == FLASH_MODEL_SLUG
    assert secret not in ledger.metrics_path.read_text(encoding="utf-8")
    assert set(metric_rows[0]) == {
        "schema_version", "kind", "request_id", "provider", "model", "prompt_tokens_upper_bound",
        "max_output_tokens", "reserved_usd", "upstream_cost_usd", "openrouter_fee_usd", "total_cost_usd", "settled_at",
    }
