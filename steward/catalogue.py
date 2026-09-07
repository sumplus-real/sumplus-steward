"""
The live model catalogue and what each workload costs against it.

Prices come from the Sumplus gateway's public catalogue. Nothing here is
hard-coded pricing, because a saving computed against a stale price list is not
a saving.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

CATALOGUE_URL = "https://router.sumplus.xyz/v1/models"


@dataclass(frozen=True)
class Model:
    id: str
    input_per_million: float
    output_per_million: float
    context: int
    availability: str
    description: str


def _get(url: str, tries: int = 4, timeout: int = 20) -> bytes:
    """
    The local network drops TLS connections at around five seconds, so one
    failure says nothing about whether the endpoint is healthy.
    """
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            last = err
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"could not read {url}: {last}")


def fetch_models() -> list[Model]:
    body = json.loads(_get(CATALOGUE_URL))
    rows = body.get("data", body) if isinstance(body, dict) else body
    models: list[Model] = []
    for row in rows:
        # Some rows price only input; treat a missing output price as equal to
        # input rather than as free, so a saving is never overstated.
        input_price = float(row.get("input_per_million", 0) or 0)
        output_price = float(row.get("output_per_million", input_price) or input_price)
        models.append(
            Model(
                id=str(row.get("id", "")),
                input_per_million=input_price,
                output_per_million=output_price,
                context=int(row.get("context", 0) or 0),
                availability=str(row.get("availability", "unknown")),
                description=str(row.get("description", "")),
            )
        )
    return [m for m in models if m.id and m.input_per_million > 0]


#: Capability bands. The owner of a workload sets the band it may not drop
#: below, which is the judgement a person should make once rather than every
#: month. The boundaries are fixed dollars per million input tokens, not
#: quantiles of whatever happens to be in the catalogue today: a band that moves
#: with the candidate list is not a promise anyone can rely on. They were
#: calibrated against the live catalogue on 2026-09-07, where the lower quartile
#: sat at $0.60 and the upper at $3.00 across 80 models.
TIERS = ("light", "mid", "flagship")
LIGHT_CEILING_PER_MILLION = 0.60
MID_CEILING_PER_MILLION = 3.00


def tier_of(model: "Model") -> str:
    if model.input_per_million <= LIGHT_CEILING_PER_MILLION:
        return "light"
    if model.input_per_million <= MID_CEILING_PER_MILLION:
        return "mid"
    return "flagship"


def price_quartiles(models: list["Model"]) -> tuple[float, float]:
    """Reported so the fixed bands above can be re-checked against the catalogue."""
    prices = sorted(m.input_per_million for m in models)
    if not prices:
        return (0.0, 0.0)
    return (prices[len(prices) // 4], prices[3 * len(prices) // 4])


def tier_rank(tier: str) -> int:
    return TIERS.index(tier) if tier in TIERS else 0


@dataclass(frozen=True)
class Workload:
    name: str
    model: str
    monthly_input_tokens: int
    monthly_output_tokens: int
    needs_context: int
    quality_sensitive: bool
    note: str
    #: The capability band this workload may not drop below.
    min_tier: str = "light"


def monthly_cost_micro_usd(model: Model, w: Workload) -> int:
    dollars = (
        w.monthly_input_tokens / 1_000_000 * model.input_per_million
        + w.monthly_output_tokens / 1_000_000 * model.output_per_million
    )
    # Round the bill up. A cost rounded down understates what the month costs.
    return int(-(-dollars * 1_000_000 // 1))


def find(models: list[Model], model_id: str) -> Model | None:
    return next((m for m in models if m.id == model_id), None)


def cheapest_viable(models: list[Model], w: Workload, current: Model) -> Model | None:
    """
    The cheapest model that fits the workload's context and stays at or above
    the capability band its owner set. Ordering is by what this workload would
    actually pay, not by headline input price: a cheap input price with an
    expensive output price is not cheap for a workload that mostly writes.
    """
    floor = tier_rank(w.min_tier)
    candidates = [
        m
        for m in models
        if m.id != current.id
        and m.context >= w.needs_context
        and m.availability == "live"
        and tier_rank(tier_of(m)) >= floor
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: monthly_cost_micro_usd(m, w))
