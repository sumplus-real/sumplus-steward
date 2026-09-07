"""
The review Steward runs on its own. No model is needed to decide anything here:
the arithmetic is arithmetic and the mandate is the mandate. The language model
is what turns the result into something a person wants to read, and it is
optional.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .catalogue import (
    Model,
    Workload,
    cheapest_viable,
    fetch_models,
    find,
    monthly_cost_micro_usd,
)
from .ledger import Ledger, Receipt, usd_saving
from .mandate import Mandate, judge

WORKLOADS = Path(__file__).with_name("workloads.json")


def load_workloads(path: Path = WORKLOADS) -> list[Workload]:
    rows = json.loads(path.read_text())
    return [Workload(**row) for row in rows]


@dataclass
class Finding:
    workload: str
    from_model: str
    to_model: str | None
    monthly_now_micro_usd: int
    monthly_after_micro_usd: int
    saving_micro_usd: int
    decision: str
    reason: str


@dataclass
class Review:
    models_seen: int
    findings: list[Finding]
    ledger: Ledger

    @property
    def applied(self) -> list[Finding]:
        return [f for f in self.findings if f.decision == "applied"]

    @property
    def escalated(self) -> list[Finding]:
        return [f for f in self.findings if f.decision == "escalated"]

    @property
    def monthly_saving_micro_usd(self) -> int:
        return sum(f.saving_micro_usd for f in self.applied)

    @property
    def receipts(self) -> list[Receipt]:
        return self.ledger.receipts


def run_review(
    mandate: Mandate | None = None,
    workloads: list[Workload] | None = None,
    models: list[Model] | None = None,
) -> Review:
    mandate = mandate or Mandate()
    workloads = workloads if workloads is not None else load_workloads()
    models = models if models is not None else fetch_models()

    ledger = Ledger()
    findings: list[Finding] = []

    ledger.append(
        action="catalogue.read",
        subject="router.sumplus.xyz/v1/models",
        decision="applied",
        reason=f"Read {len(models)} live models and their prices before deciding anything.",
        payload=[m.id for m in models],
    )

    for w in workloads:
        current = find(models, w.model)
        if current is None:
            ledger.append(
                action="workload.skip",
                subject=w.name,
                decision="refused",
                reason=f"{w.model} is not in the catalogue, so Steward cannot price it.",
                payload={"workload": w.name, "model": w.model},
            )
            continue

        now = monthly_cost_micro_usd(current, w)
        candidate = cheapest_viable(models, w, current)
        if candidate is None:
            findings.append(
                Finding(w.name, w.model, None, now, now, 0, "refused", "No other live model fits this workload's context.")
            )
            ledger.append(
                action="workload.review",
                subject=w.name,
                decision="refused",
                reason="No other live model fits this workload's context.",
                payload={"workload": w.name, "monthly": now},
            )
            continue

        after = monthly_cost_micro_usd(candidate, w)
        saving = now - after

        verdict = judge(
            mandate,
            workload=w.name,
            from_model=current.id,
            to_model=candidate.id,
            monthly_saving_micro_usd=saving,
            to_context=candidate.context,
            needs_context=w.needs_context,
            to_availability=candidate.availability,
            quality_sensitive=w.quality_sensitive,
        )

        findings.append(
            Finding(w.name, current.id, candidate.id, now, after, saving, verdict.decision, verdict.reason)
        )
        ledger.append(
            action="workload.review",
            subject=w.name,
            decision=verdict.decision,  # type: ignore[arg-type]
            reason=verdict.reason,
            saving_micro_usd=saving if verdict.decision == "applied" else 0,
            payload={
                "workload": w.name,
                "from": current.id,
                "to": candidate.id,
                "monthly_now": now,
                "monthly_after": after,
            },
        )

    return Review(models_seen=len(models), findings=findings, ledger=ledger)


def render(review: Review) -> str:
    """What a person reads in the morning. Decisions first, work second."""
    lines: list[str] = []
    esc = review.escalated
    app = review.applied

    if esc:
        lines.append(f"{len(esc)} decision{'s' if len(esc) > 1 else ''} for you")
        for f in esc:
            lines.append(f"  {f.workload}: {f.reason}")
        lines.append("")

    lines.append(
        f"Steward handled {len(app)} switch{'es' if len(app) != 1 else ''} on its own, "
        f"saving {usd_saving(review.monthly_saving_micro_usd)} a month."
    )
    for f in app:
        lines.append(f"  {f.workload}: {f.from_model} to {f.to_model}, {usd_saving(f.saving_micro_usd)} a month")

    left = [f for f in review.findings if f.decision == "refused"]
    if left:
        lines.append("")
        lines.append(f"Left alone ({len(left)}):")
        for f in left:
            lines.append(f"  {f.workload}: {f.reason}")

    lines.append("")
    lines.append(f"{len(review.receipts)} receipts, chain head {review.ledger.head[:16]}…")
    return "\n".join(lines)
