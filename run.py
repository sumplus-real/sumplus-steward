#!/usr/bin/env python
"""
Steward, from the command line.

    python run.py                 # the overnight review, no model, no credentials
    python run.py --receipts      # print the receipt chain
    python run.py --audit         # recompute the chain and report
    python run.py --ask "…"       # talk to the Strands agent (needs a model)

The review itself is arithmetic and a mandate, so it runs with nothing
configured. The model is what turns the result into prose, and it is optional
by design: a spending control that stops working when a model is unavailable is
not a control.
"""

from __future__ import annotations

import argparse
import sys

from steward.ledger import verify
from steward.review import render, run_review


def main() -> int:
    p = argparse.ArgumentParser(description="Steward: look after what your AI workloads cost.")
    p.add_argument("--receipts", action="store_true", help="print the receipt chain as JSON")
    p.add_argument("--audit", action="store_true", help="recompute the chain and report")
    p.add_argument("--ask", metavar="QUESTION", help="ask the Strands agent (requires a model)")
    args = p.parse_args()

    if args.ask:
        from steward.agent import build_agent

        agent = build_agent()
        print(agent(args.ask))
        return 0

    review = run_review()

    if args.receipts:
        print(review.ledger.to_json())
        return 0

    if args.audit:
        v = verify(review.receipts)
        print(f"{v.length} receipts, head {v.head}")
        print("chain intact" if v.ok else "chain broken")
        for problem in v.problems:
            print(f"  receipt {problem.seq}: {problem.detail}")
        return 0 if v.ok else 2

    print(render(review))
    return 0


if __name__ == "__main__":
    sys.exit(main())
