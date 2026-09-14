# Submission — Agents for Humans

**Project:** Sumplus Steward
**Track:** Professional Agents
**Built with:** Strands Agents SDK
**Live demo:** https://sumplus-steward-production.up.railway.app
**Repository:** https://github.com/sumplus-real/sumplus-steward
**Deadline:** 2026-09-14, 17:00 Pacific

## Elevator

A team runs a handful of AI workloads. Each was put on a model once and nobody
re-checks, because re-checking means pricing five workloads against ninety
models. Steward does that review in the background, applies what is plainly
inside its mandate, and brings a person only the calls that are genuinely
theirs. It is for the engineering leads and small-business owners who run AI
workloads in production and pay that bill every month.

## The one-minute demo

```bash
python run.py
```

One decision comes back for the human. Three switches were already made, worth
$4,019.60 a month. One workload is pinned and was left alone with a sentence
saying so. Six receipts, chained.

Prices are live from a public catalogue that needs no key:

```bash
curl -s https://router.sumplus.xyz/v1/models | head
```

## Why it fits the brief

The brief asks for an agent that runs routine work in the background and
surfaces only when there is a real decision to make. That line is the whole
design here, not a description of it:

- The mandate in `steward/mandate.py` decides who owns each change.
- Quality-sensitive workloads always come to a person, however large the saving.
- A pinned workload is reported on and never touched.
- Everything else Steward does itself and tells you afterwards.

## Judging notes

- **It works with no credentials.** The review is arithmetic plus a mandate, so
  a judge can run it immediately. The Strands agent adds conversation on top and
  takes any model provider, Bedrock included.
- **Every decision leaves a receipt**, including the decisions not to act.
  `python run.py --audit` recomputes the chain from the receipts and trusts none
  of the stored hashes.
- **The tests have teeth.** Twelve of them. The chain test asserts both halves
  of a tampering break; weakening the verifier on purpose turns it red.
- Costs round up and savings round down, so neither figure flatters itself.

## Files

| Path | What it is |
|---|---|
| `steward/mandate.py` | Who owns which change. The product. |
| `steward/catalogue.py` | Live prices, capability bands, per-workload costing. |
| `steward/ledger.py` | Receipts and the chain verifier. |
| `steward/review.py` | The unattended review. |
| `steward/agent.py` | Strands agent and its six tools. |
| `run.py` | CLI. |
| `tests/` | Twelve tests. |
