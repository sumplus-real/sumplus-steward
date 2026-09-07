"""
What Steward is allowed to do on its own, and what it has to bring to a person.

The whole product turns on this file. An agent that asks about everything is a
worse inbox; an agent that asks about nothing is a liability. The mandate is the
line between the two, written down.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ledger import usd, usd_saving


@dataclass
class Mandate:
    #: Steward may switch a workload on its own only if the new model saves at
    #: least this much per month. Below it, churn is not worth the disruption.
    min_monthly_saving_micro_usd: int = 2_000_000
    #: Steward will not move a workload onto a model whose context window is
    #: smaller than the workload needs.
    respect_context: bool = True
    #: Workloads a person has pinned. Steward reports on them and changes nothing.
    pinned: list[str] = field(default_factory=lambda: ["board-pack"])
    #: Model availability Steward is willing to move production onto.
    allowed_availability: list[str] = field(default_factory=lambda: ["live"])


@dataclass
class Verdict:
    decision: str  # "applied" | "refused" | "escalated"
    reason: str


def judge(
    mandate: Mandate,
    *,
    workload: str,
    from_model: str,
    to_model: str,
    monthly_saving_micro_usd: int,
    to_context: int,
    needs_context: int,
    to_availability: str,
    quality_sensitive: bool,
) -> Verdict:
    """
    Decide who owns this change. Order matters: the reasons a change is simply
    wrong come before the reasons it merely needs a person.
    """
    if workload in mandate.pinned:
        return Verdict(
            "refused",
            f"{workload} is pinned, so Steward reports on it and changes nothing.",
        )

    if to_availability not in mandate.allowed_availability:
        return Verdict(
            "refused",
            f"{to_model} is marked {to_availability}, and Steward only moves production onto {' or '.join(mandate.allowed_availability)} models.",
        )

    if mandate.respect_context and to_context < needs_context:
        return Verdict(
            "refused",
            f"{workload} needs {needs_context:,} tokens of context and {to_model} offers {to_context:,}.",
        )

    if monthly_saving_micro_usd <= 0:
        return Verdict("refused", f"{to_model} would cost more than {from_model} for this workload.")

    if monthly_saving_micro_usd < mandate.min_monthly_saving_micro_usd:
        return Verdict(
            "refused",
            f"Saving is {usd(monthly_saving_micro_usd)} a month, below the {usd(mandate.min_monthly_saving_micro_usd)} that makes a switch worth the churn.",
        )

    if quality_sensitive:
        return Verdict(
            "escalated",
            f"{workload} is marked quality sensitive. Moving it to {to_model} saves {usd_saving(monthly_saving_micro_usd)} a month and that trade is yours to make.",
        )

    return Verdict(
        "applied",
        f"Moved {workload} from {from_model} to {to_model}, saving {usd_saving(monthly_saving_micro_usd)} a month within the mandate.",
    )
