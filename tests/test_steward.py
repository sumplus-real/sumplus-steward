"""
Tests for the parts that decide things. The mandate and the ledger are the two
places where a bug costs money or hides a change, so both are pinned down here
against fixed model data rather than against the live catalogue.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from steward.catalogue import Model, Workload, cheapest_viable, monthly_cost_micro_usd, tier_of
from steward.ledger import Ledger, usd, usd_saving, verify
from steward.mandate import Mandate, judge
from steward.review import run_review

FLAGSHIP = Model("flagship-1", 5.0, 15.0, 400_000, "live", "")
MID = Model("mid-1", 1.0, 3.0, 200_000, "live", "")
LIGHT = Model("light-1", 0.1, 0.4, 1_000_000, "live", "")
SMALL_CONTEXT = Model("light-tiny", 0.05, 0.2, 8_000, "live", "")
PREVIEW = Model("preview-1", 0.05, 0.1, 400_000, "preview", "")
MODELS = [FLAGSHIP, MID, LIGHT, SMALL_CONTEXT, PREVIEW]

BULK = Workload("bulk", "flagship-1", 100_000_000, 10_000_000, 32_000, False, "", "light")


def test_cost_uses_both_input_and_output_prices():
    # 100M in at $5 and 10M out at $15 is $500 + $150.
    assert monthly_cost_micro_usd(FLAGSHIP, BULK) == 650_000_000


def test_cost_rounds_up_never_down():
    tiny = Workload("tiny", "light-1", 1, 0, 1_000, False, "", "light")
    # A tenth of a micro-dollar must not be billed as zero.
    assert monthly_cost_micro_usd(LIGHT, tiny) == 1


def test_saving_rounds_down_to_cents():
    assert usd_saving(825_599_999) == "$825.59"
    assert usd(6_000) == "$0.006"


def test_cheapest_respects_the_context_a_workload_needs():
    needs_long = Workload("long", "flagship-1", 1_000_000, 0, 300_000, False, "", "light")
    pick = cheapest_viable(MODELS, needs_long, FLAGSHIP)
    assert pick is not None and pick.context >= 300_000
    assert pick.id != "light-tiny"


def test_cheapest_will_not_drop_below_the_owners_floor():
    guarded = Workload("guarded", "flagship-1", 100_000_000, 0, 32_000, False, "", "mid")
    pick = cheapest_viable(MODELS, guarded, FLAGSHIP)
    assert pick is not None
    assert tier_of(pick) != "light"


def test_cheapest_ignores_models_that_are_not_live():
    pick = cheapest_viable(MODELS, BULK, FLAGSHIP)
    assert pick is not None and pick.availability == "live"


def test_quality_sensitive_work_is_always_a_persons_call():
    v = judge(
        Mandate(pinned=[]),
        workload="w",
        from_model="a",
        to_model="b",
        monthly_saving_micro_usd=500_000_000,
        to_context=400_000,
        needs_context=1_000,
        to_availability="live",
        quality_sensitive=True,
    )
    assert v.decision == "escalated"


def test_pinned_work_is_left_alone_even_when_it_would_save():
    v = judge(
        Mandate(pinned=["w"]),
        workload="w",
        from_model="a",
        to_model="b",
        monthly_saving_micro_usd=500_000_000,
        to_context=400_000,
        needs_context=1_000,
        to_availability="live",
        quality_sensitive=False,
    )
    assert v.decision == "refused" and "pinned" in v.reason


def test_a_saving_too_small_to_be_worth_churn_is_refused():
    v = judge(
        Mandate(pinned=[]),
        workload="w",
        from_model="a",
        to_model="b",
        monthly_saving_micro_usd=1,
        to_context=400_000,
        needs_context=1_000,
        to_availability="live",
        quality_sensitive=False,
    )
    assert v.decision == "refused"


def test_every_refusal_carries_a_sentence():
    review = run_review(models=MODELS, workloads=[
        Workload("pinned-one", "flagship-1", 100_000_000, 0, 1_000, False, "", "light"),
    ], mandate=Mandate(pinned=["pinned-one"]))
    for r in review.receipts:
        if r.decision != "applied":
            assert r.reason.endswith(".") and len(r.reason.split()) > 4


def test_the_chain_verifies_and_an_edit_breaks_it():
    ledger = Ledger()
    for i in range(4):
        ledger.append(
            action="workload.review",
            subject=f"w{i}",
            decision="applied",
            reason="Moved it.",
            payload={"i": i},
            saving_micro_usd=1_000_000,
        )

    assert verify(ledger.receipts).ok

    ledger.receipts[1].saving_micro_usd += 1
    broken = verify(ledger.receipts)
    assert not broken.ok
    kinds = {p.kind for p in broken.problems}
    seqs = {p.seq for p in broken.problems}
    # The edit has to surface twice: the receipt's own hash, and the link held
    # by the receipt after it. Catching only the first would pass even if links
    # were never checked at all.
    assert "hash-mismatch" in kinds
    assert "broken-link" in kinds
    assert {1, 2} <= seqs


def test_receipts_exist_for_work_that_was_not_done():
    review = run_review(models=MODELS, workloads=[
        Workload("sensitive", "flagship-1", 100_000_000, 0, 1_000, True, "", "light"),
    ], mandate=Mandate(pinned=[]))
    decisions = [r.decision for r in review.receipts]
    assert "escalated" in decisions, "an escalation must leave a receipt, not just a message"
