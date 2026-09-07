"""
Steward as a Strands agent.

The tools below are the whole surface. Each one is deterministic and each one
writes a receipt, so the model chooses what to look at and how to say it, and
never gets to decide on its own that a change was within mandate.
"""

from __future__ import annotations

import json

from strands import Agent, tool

from .catalogue import Workload, cheapest_viable, fetch_models, find, monthly_cost_micro_usd
from .ledger import usd, verify
from .mandate import Mandate
from .review import Review, load_workloads, render, run_review

SYSTEM_PROMPT = """\
You are Steward. You look after what a team's AI workloads cost, in the
background, and you bring a person exactly the decisions that are theirs.

Rules you do not get to bend:
- The mandate decides what you may change alone. You never argue with a refusal
  or an escalation; you report it.
- Every number you state comes from a tool. You do not estimate prices.
- Say what you did before you say what you found, and put the decisions a person
  owns at the very top.
- Write plainly, in short sentences. No preamble, no summary of your own
  reasoning, no offers to help further.
"""

_state: dict[str, object] = {}


def _review() -> Review:
    if "review" not in _state:
        _state["review"] = run_review()
    return _state["review"]  # type: ignore[return-value]


@tool
def review_spend() -> str:
    """Run the monthly review of every workload against the live model catalogue.

    Returns a plain-text report of what was changed within mandate, what needs a
    person, and what was left alone.
    """
    _state.pop("review", None)
    return render(_review())


@tool
def decisions_for_the_human() -> str:
    """List only the items the mandate says a person must decide, and why."""
    esc = _review().escalated
    if not esc:
        return "Nothing needs you. Every change this run was inside the mandate."
    return "\n".join(f"{f.workload}: {f.reason}" for f in esc)


@tool
def price_workload(workload_name: str, model_id: str) -> str:
    """Price one named workload against one named model, per month."""
    models = fetch_models()
    model = find(models, model_id)
    if model is None:
        return f"{model_id} is not in the catalogue."
    w = next((x for x in load_workloads() if x.name == workload_name), None)
    if w is None:
        return f"{workload_name} is not a known workload."
    if model.context < w.needs_context:
        return (
            f"{model_id} offers {model.context:,} tokens of context and {workload_name} "
            f"needs {w.needs_context:,}, so this pairing does not work."
        )
    return f"{workload_name} on {model_id} costs {usd(monthly_cost_micro_usd(model, w))} a month."


@tool
def cheapest_option(workload_name: str) -> str:
    """Find the cheapest live model that still fits a workload's context."""
    models = fetch_models()
    w = next((x for x in load_workloads() if x.name == workload_name), None)
    if w is None:
        return f"{workload_name} is not a known workload."
    current = find(models, w.model)
    if current is None:
        return f"{w.model} is not in the catalogue, so there is nothing to compare against."
    candidate = cheapest_viable(models, w, current)
    if candidate is None:
        return f"No other live model fits {workload_name}."
    now = monthly_cost_micro_usd(current, w)
    after = monthly_cost_micro_usd(candidate, w)
    return (
        f"{workload_name} runs on {current.id} at {usd(now)} a month. "
        f"{candidate.id} fits and costs {usd(after)}, a difference of {usd(now - after)}."
    )


@tool
def audit_receipts() -> str:
    """Recompute the receipt chain for this run and report whether it holds."""
    review = _review()
    v = verify(review.receipts)
    if v.ok:
        return f"{v.length} receipts verify. Head {v.head[:16]}…"
    return "\n".join([f"{v.length} receipts, chain broken:"] + [f"  {p.seq}: {p.detail}" for p in v.problems])


@tool
def show_mandate() -> str:
    """State the limits Steward is operating under."""
    m = Mandate()
    return json.dumps(
        {
            "switch_alone_above": usd(m.min_monthly_saving_micro_usd) + " a month",
            "bring_to_a_person_above": usd(m.max_unattended_saving_micro_usd) + " a month",
            "quality_sensitive_workloads": "always a person's call",
            "pinned": m.pinned or "none",
            "will_move_onto": ", ".join(m.allowed_availability) + " models only",
        },
        indent=2,
    )


TOOLS = [review_spend, decisions_for_the_human, price_workload, cheapest_option, audit_receipts, show_mandate]


def build_agent(model: object | None = None) -> Agent:
    """
    A Strands agent over the tools above. `model` is passed through, so the same
    Steward runs on Bedrock, on a local runtime, or on anything else Strands
    supports.
    """
    kwargs: dict[str, object] = {"tools": TOOLS, "system_prompt": SYSTEM_PROMPT}
    if model is not None:
        kwargs["model"] = model
    return Agent(**kwargs)  # type: ignore[arg-type]
