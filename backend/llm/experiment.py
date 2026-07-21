"""DeepSeek real-provider experiment guardrails.

This module intentionally has no HTTP client and no knowledge of credentials.
Callers must reserve a bounded request *before* sending it, then settle that
reservation from trusted upstream accounting.  The append-only journal makes a
crash between those steps conservative: an un-settled reservation still counts
against the budget on the next process start.

The companion ``*.metrics.jsonl`` file is deliberately narrow.  It contains
one sanitised record per settled provider request and never stores prompt text,
API keys, card data, private NPC state, or arbitrary caller metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
from pathlib import Path
import re
import threading
from typing import Any, Literal, Mapping
from uuid import uuid4


PRO_MODEL_SLUG = "deepseek-v4-pro"
FLASH_MODEL_SLUG = "deepseek-v4-flash"
AllowedModelSlug = Literal[
    "deepseek-v4-pro",
    "deepseek-v4-flash",
]
_ALLOWED_MODELS = frozenset((PRO_MODEL_SLUG, FLASH_MODEL_SLUG))
_HISTORICAL_MODEL_SLUGS = frozenset(
    ("deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash")
)
_JOURNAL_MODEL_SLUGS = _ALLOWED_MODELS | _HISTORICAL_MODEL_SLUGS
_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_AMOUNT_QUANTUM = Decimal("0.00000001")
_MAX_PROMPT_TOKENS = 1_000_000
_MAX_OUTPUT_TOKENS = 65_536


class ExperimentPolicyError(ValueError):
    """The request does not comply with the tightly scoped experiment policy."""


class LedgerIntegrityError(RuntimeError):
    """The persistent journal is malformed, incomplete, or internally inconsistent."""


class BudgetStop(RuntimeError):
    """Base class for a conservative experiment-budget refusal."""


class SoftBudgetStop(BudgetStop):
    """The soft evaluation ceiling would be reached by this reservation."""


class HardBudgetStop(BudgetStop):
    """The hard operational ceiling would be reached by this reservation."""


@dataclass(frozen=True)
class ModelPricing:
    """USD price card expressed per million input/output tokens."""

    input_usd_per_million: Decimal
    output_usd_per_million: Decimal

    def __post_init__(self) -> None:
        if self.input_usd_per_million < 0 or self.output_usd_per_million < 0:
            raise ValueError("model prices must be non-negative")


# These are deliberately conservative direct-provider reservation ceilings,
# not permanent product prices. Actual successful requests settle from trusted
# response accounting, so the ceiling only decides whether a bounded request
# may safely start under the experiment cap.
DEFAULT_MODEL_PRICING: Mapping[AllowedModelSlug, ModelPricing] = {
    PRO_MODEL_SLUG: ModelPricing(Decimal("5.00"), Decimal("10.00")),
    FLASH_MODEL_SLUG: ModelPricing(Decimal("5.00"), Decimal("10.00")),
}


@dataclass(frozen=True)
class ExperimentPolicy:
    """Non-negotiable constraints for the DeepSeek V4 evaluation."""

    provider: str = "deepseek"
    allow_fallbacks: bool = False
    require_parameters: bool = True
    reasoning: str = "high"
    soft_stop_usd: Decimal = Decimal("8.50")
    hard_stop_usd: Decimal = Decimal("9.50")
    uncertainty_reserve_usd: Decimal = Decimal("0.50")
    openrouter_fee_rate: Decimal = Decimal("0")
    pricing: Mapping[AllowedModelSlug, ModelPricing] = field(
        default_factory=lambda: DEFAULT_MODEL_PRICING
    )

    def __post_init__(self) -> None:
        if self.provider != "deepseek":
            raise ValueError("the experiment upstream provider must be exactly 'deepseek'")
        if self.allow_fallbacks:
            raise ValueError("DeepSeek upstream fallbacks must stay disabled")
        if not self.require_parameters:
            raise ValueError("DeepSeek experiment parameters must be required")
        if self.reasoning != "high":
            raise ValueError("DeepSeek experiment reasoning must be exactly 'high'")
        if self.soft_stop_usd <= 0 or self.hard_stop_usd <= self.soft_stop_usd:
            raise ValueError("budget stops must be positive and hard must exceed soft")
        if self.uncertainty_reserve_usd < 0:
            raise ValueError("uncertainty reserve must be non-negative")
        if self.openrouter_fee_rate < 0:
            raise ValueError("OpenRouter fee rate must be non-negative")
        if set(self.pricing) != _ALLOWED_MODELS:
            raise ValueError("pricing must contain exactly the Pro and Flash slugs")

    def validate_request(
        self,
        *,
        provider: str,
        model: str,
        allow_fallbacks: bool,
        parameters: Mapping[str, Any] | None,
        reasoning: str,
    ) -> None:
        if provider != self.provider:
            raise ExperimentPolicyError("only the DeepSeek upstream provider is permitted")
        if model not in _ALLOWED_MODELS:
            raise ExperimentPolicyError("model must be an exact approved DeepSeek V4 slug")
        if allow_fallbacks:
            raise ExperimentPolicyError("provider fallbacks are forbidden")
        if self.require_parameters and not parameters:
            raise ExperimentPolicyError("explicit provider parameters are required")
        if reasoning != self.reasoning:
            raise ExperimentPolicyError("reasoning must be exactly high")


@dataclass(frozen=True)
class Reservation:
    request_id: str
    provider: str
    model: AllowedModelSlug
    prompt_tokens_upper_bound: int
    max_output_tokens: int
    reserved_usd: Decimal


@dataclass(frozen=True)
class Settlement:
    request_id: str
    upstream_cost_usd: Decimal
    openrouter_fee_usd: Decimal
    total_cost_usd: Decimal


_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    resolved = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


def _money(value: object, *, name: str) -> Decimal:
    """Parse an accounting amount without accepting NaN, infinity, or negatives."""

    if isinstance(value, bool):
        raise ValueError(f"{name} must be a decimal USD amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{name} must be a decimal USD amount") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} must be a finite non-negative USD amount")
    return amount.quantize(_AMOUNT_QUANTUM, rounding=ROUND_CEILING)


def _amount_text(amount: Decimal) -> str:
    return format(amount.quantize(_AMOUNT_QUANTUM, rounding=ROUND_CEILING), "f")


class DeepSeekExperimentLedger:
    """Thread-safe append-only budget journal for a bounded provider experiment.

    ``path`` is the durable reservation/settlement journal.  ``metrics_path``
    is a sibling append-only, sanitised metrics stream.  Both are reopened and
    revalidated under a path-wide lock for each mutation, so separate ledger
    instances in the same Python process cannot oversubscribe the budget.
    """

    def __init__(self, path: str | Path, policy: ExperimentPolicy | None = None) -> None:
        self.path = Path(path)
        self.metrics_path = self.path.with_name(f"{self.path.stem}.metrics.jsonl")
        self.policy = policy or ExperimentPolicy()
        self._lock = _lock_for(self.path)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                self._read_state()

    def reserve(
        self,
        *,
        provider: str,
        model: AllowedModelSlug,
        prompt_tokens_upper_bound: int,
        max_output_tokens: int,
        parameters: Mapping[str, Any] | None,
        reasoning: str = "high",
        allow_fallbacks: bool = False,
    ) -> Reservation:
        """Persist a worst-case reservation before the caller contacts a provider."""

        self.policy.validate_request(
            provider=provider,
            model=model,
            allow_fallbacks=allow_fallbacks,
            parameters=parameters,
            reasoning=reasoning,
        )
        self._validate_bounds(prompt_tokens_upper_bound, max_output_tokens)
        pricing = self.policy.pricing[model]
        reserved = self._estimate(pricing, prompt_tokens_upper_bound, max_output_tokens)
        reserved = (reserved * (Decimal("1") + self.policy.openrouter_fee_rate)).quantize(
            _AMOUNT_QUANTUM,
            rounding=ROUND_CEILING,
        )
        with self._lock:
            state = self._read_state()
            projected = state["settled"] + state["reserved"] + reserved + self.policy.uncertainty_reserve_usd
            if projected >= self.policy.hard_stop_usd:
                raise HardBudgetStop("hard DeepSeek experiment budget stop reached")
            if projected >= self.policy.soft_stop_usd:
                raise SoftBudgetStop("soft DeepSeek experiment budget stop reached")
            request_id = uuid4().hex
            record = {
                "schema_version": 1,
                "kind": "reservation",
                "request_id": request_id,
                "provider": provider,
                "model": model,
                "prompt_tokens_upper_bound": prompt_tokens_upper_bound,
                "max_output_tokens": max_output_tokens,
                "reserved_usd": _amount_text(reserved),
                "created_at": datetime.now(UTC).isoformat(),
            }
            self._append_jsonl(self.path, record)
        return Reservation(request_id, provider, model, prompt_tokens_upper_bound, max_output_tokens, reserved)

    def settle(
        self,
        reservation: Reservation | str,
        *,
        upstream_cost_usd: object,
        openrouter_fee_usd: object,
        accounting_trusted: bool,
    ) -> Settlement:
        """Release a reservation using separately reported upstream and router costs.

        A combined or inferred total is deliberately not accepted: the caller
        must provide both trusted components.  This prevents accidentally
        adding an OpenRouter fee twice to a provider amount that already
        includes it.
        """

        if not accounting_trusted:
            raise ExperimentPolicyError("untrusted provider accounting cannot settle a reservation")
        request_id = reservation.request_id if isinstance(reservation, Reservation) else reservation
        if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
            raise ExperimentPolicyError("settlement requires a ledger-issued request id")
        upstream = _money(upstream_cost_usd, name="upstream_cost_usd")
        fee = _money(openrouter_fee_usd, name="openrouter_fee_usd")
        total = (upstream + fee).quantize(_AMOUNT_QUANTUM, rounding=ROUND_CEILING)
        with self._lock:
            state = self._read_state()
            reserved = state["open"].get(request_id)
            if reserved is None:
                if request_id in state["settled_ids"]:
                    raise LedgerIntegrityError("reservation has already been settled")
                raise LedgerIntegrityError("unknown reservation cannot be settled")
            # A bill arrives after the provider work is already done.  It must
            # be recorded even if it exceeds a stop threshold; withholding it
            # would make the persistent total less trustworthy.  Subsequent
            # reservations see the settled amount and are then refused by the
            # hard/soft pre-call checks.
            settlement_record = {
                "schema_version": 1,
                "kind": "settlement",
                "request_id": request_id,
                "upstream_cost_usd": _amount_text(upstream),
                "openrouter_fee_usd": _amount_text(fee),
                "total_cost_usd": _amount_text(total),
                "settled_at": datetime.now(UTC).isoformat(),
            }
            self._append_jsonl(self.path, settlement_record)
            # Fixed schema only: never copy arbitrary request parameters or
            # caller-supplied metadata into observability storage.
            metric = {
                "schema_version": 1,
                "kind": "provider_request",
                "request_id": request_id,
                "provider": reserved["provider"],
                "model": reserved["model"],
                "prompt_tokens_upper_bound": reserved["prompt_tokens_upper_bound"],
                "max_output_tokens": reserved["max_output_tokens"],
                "reserved_usd": _amount_text(reserved["reserved_usd"]),
                "upstream_cost_usd": _amount_text(upstream),
                "openrouter_fee_usd": _amount_text(fee),
                "total_cost_usd": _amount_text(total),
                "settled_at": settlement_record["settled_at"],
            }
            self._append_jsonl(self.metrics_path, metric)
        return Settlement(request_id, upstream, fee, total)

    def settle_openrouter_charge(
        self,
        reservation: Reservation | str,
        *,
        openrouter_charge_usd: object,
        accounting_trusted: bool,
    ) -> Settlement:
        """Settle a standard OpenRouter request from its inclusive charge.

        For non-BYOK traffic ``usage.cost`` is the external charge. The legacy
        two-component journal stores that inclusive amount in its router-cost
        component and zero in the separately billed upstream component, which
        prevents double-counting informational upstream pricing metadata.
        """

        return self.settle(
            reservation,
            upstream_cost_usd="0",
            openrouter_fee_usd=openrouter_charge_usd,
            accounting_trusted=accounting_trusted,
        )

    def snapshot(self) -> dict[str, Decimal | int]:
        """Return budget state without exposing any request content."""

        with self._lock:
            state = self._read_state()
            return {
                "settled_usd": state["settled"],
                "reserved_usd": state["reserved"],
                "available_before_soft_stop_usd": max(
                    Decimal("0"), self.policy.soft_stop_usd - self.policy.uncertainty_reserve_usd - state["settled"] - state["reserved"]
                ),
                "open_reservations": len(state["open"]),
            }

    @staticmethod
    def _validate_bounds(prompt_tokens: int, output_tokens: int) -> None:
        if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or not 0 < prompt_tokens <= _MAX_PROMPT_TOKENS:
            raise ExperimentPolicyError("prompt token upper bound is invalid")
        if isinstance(output_tokens, bool) or not isinstance(output_tokens, int) or not 0 < output_tokens <= _MAX_OUTPUT_TOKENS:
            raise ExperimentPolicyError("max output tokens is invalid")

    @staticmethod
    def _estimate(pricing: ModelPricing, prompt_tokens: int, output_tokens: int) -> Decimal:
        estimate = (
            (Decimal(prompt_tokens) / Decimal(1_000_000)) * pricing.input_usd_per_million
            + (Decimal(output_tokens) / Decimal(1_000_000)) * pricing.output_usd_per_million
        )
        return estimate.quantize(_AMOUNT_QUANTUM, rounding=ROUND_CEILING)

    @staticmethod
    def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
        encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        with path.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            # A reservation must survive an ordinary process crash before a
            # caller sends the network request.
            try:
                import os
                os.fsync(handle.fileno())
            except OSError:
                # Filesystems without fsync support retain append semantics;
                # do not pretend a failed sync is a successful provider call.
                raise LedgerIntegrityError("could not durably append experiment ledger")

    def _read_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"settled": Decimal("0"), "reserved": Decimal("0"), "open": {}, "settled_ids": set()}
        open_reservations: dict[str, dict[str, Any]] = {}
        settled_ids: set[str] = set()
        settled = Decimal("0")
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise LedgerIntegrityError("could not read experiment ledger") from error
        for number, line in enumerate(lines, start=1):
            if not line:
                raise LedgerIntegrityError(f"empty journal row at line {number}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise LedgerIntegrityError(f"malformed journal row at line {number}") from error
            if not isinstance(record, dict) or record.get("schema_version") != 1:
                raise LedgerIntegrityError(f"unrecognised journal row at line {number}")
            kind = record.get("kind")
            request_id = record.get("request_id")
            if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
                raise LedgerIntegrityError(f"invalid request id at line {number}")
            if kind == "reservation":
                if request_id in open_reservations or request_id in settled_ids:
                    raise LedgerIntegrityError(f"duplicate reservation at line {number}")
                model = record.get("model")
                prompt = record.get("prompt_tokens_upper_bound")
                output = record.get("max_output_tokens")
                provider = record.get("provider")
                if provider not in {"deepseek", "openrouter"} or model not in _JOURNAL_MODEL_SLUGS:
                    raise LedgerIntegrityError(f"invalid reservation policy at line {number}")
                try:
                    self._validate_bounds(prompt, output)
                    amount = _money(record.get("reserved_usd"), name="reserved_usd")
                except (ExperimentPolicyError, ValueError) as error:
                    raise LedgerIntegrityError(f"invalid reservation amount at line {number}") from error
                open_reservations[request_id] = {
                    "provider": provider,
                    "model": model,
                    "prompt_tokens_upper_bound": prompt,
                    "max_output_tokens": output,
                    "reserved_usd": amount,
                }
            elif kind == "settlement":
                reservation = open_reservations.pop(request_id, None)
                if reservation is None:
                    raise LedgerIntegrityError(f"unknown or duplicate settlement at line {number}")
                try:
                    upstream = _money(record.get("upstream_cost_usd"), name="upstream_cost_usd")
                    fee = _money(record.get("openrouter_fee_usd"), name="openrouter_fee_usd")
                    total = _money(record.get("total_cost_usd"), name="total_cost_usd")
                except ValueError as error:
                    raise LedgerIntegrityError(f"invalid settlement amount at line {number}") from error
                if total != upstream + fee:
                    raise LedgerIntegrityError(f"double-counted or inconsistent settlement at line {number}")
                settled += total
                settled_ids.add(request_id)
            else:
                raise LedgerIntegrityError(f"unrecognised journal kind at line {number}")
        reserved = sum((item["reserved_usd"] for item in open_reservations.values()), Decimal("0"))
        return {"settled": settled, "reserved": reserved, "open": open_reservations, "settled_ids": settled_ids}
