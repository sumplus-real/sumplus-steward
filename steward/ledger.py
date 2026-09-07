"""
The record Steward leaves behind.

Every action the agent takes, and every decision it declines to take alone,
becomes a receipt. Receipts are chained, so the record can be checked from the
receipts themselves rather than taken on trust.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Literal

GENESIS = "0" * 64

Decision = Literal["applied", "refused", "escalated"]


@dataclass
class Receipt:
    seq: int
    at: str
    action: str
    subject: str
    #: Monthly dollars this action saves, in micro-dollars. Integers only.
    saving_micro_usd: int
    decision: Decision
    #: A sentence, always. "Refused" with no reason is what makes people switch
    #: these controls off.
    reason: str
    payload_hash: str
    prev_hash: str
    hash: str = ""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_payload(payload: object) -> str:
    return _sha256(json.dumps(payload, sort_keys=True, default=str))


def receipt_preimage(r: Receipt) -> str:
    """The bytes a receipt commits to. Field order is part of the format."""
    return "\n".join(
        [
            str(r.seq),
            r.at,
            r.action,
            r.subject,
            str(r.saving_micro_usd),
            r.decision,
            r.reason,
            r.payload_hash,
            r.prev_hash,
        ]
    )


class Ledger:
    def __init__(self) -> None:
        self.receipts: list[Receipt] = []

    @property
    def head(self) -> str:
        return self.receipts[-1].hash if self.receipts else GENESIS

    def append(
        self,
        *,
        action: str,
        subject: str,
        decision: Decision,
        reason: str,
        payload: object,
        saving_micro_usd: int = 0,
    ) -> Receipt:
        r = Receipt(
            seq=len(self.receipts),
            at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            action=action,
            subject=subject,
            saving_micro_usd=saving_micro_usd,
            decision=decision,
            reason=reason,
            payload_hash=hash_payload(payload),
            prev_hash=self.head,
        )
        r.hash = _sha256(receipt_preimage(r))
        self.receipts.append(r)
        return r

    def to_json(self) -> str:
        return json.dumps([asdict(r) for r in self.receipts], indent=2)


@dataclass
class Problem:
    seq: int
    kind: str
    detail: str


@dataclass
class Verification:
    ok: bool
    length: int
    head: str
    problems: list[Problem] = field(default_factory=list)


def verify(receipts: Iterable[Receipt]) -> Verification:
    """
    Recompute the chain from the receipts alone, trusting none of the stored
    hashes. This is what someone auditing the run actually runs.
    """
    problems: list[Problem] = []
    expected_prev = GENESIS
    last = GENESIS
    count = 0

    for index, r in enumerate(receipts):
        count += 1
        if r.seq != index:
            problems.append(
                Problem(r.seq, "bad-sequence", f"numbered {r.seq} but sits at position {index}")
            )
        if r.prev_hash != expected_prev:
            problems.append(
                Problem(
                    r.seq,
                    "broken-link",
                    f"points at {short(r.prev_hash)} but the receipt before it hashes to {short(expected_prev)}",
                )
            )
        recomputed = _sha256(receipt_preimage(r))
        if recomputed != r.hash:
            problems.append(
                Problem(
                    r.seq,
                    "hash-mismatch",
                    f"contents hash to {short(recomputed)}, receipt claims {short(r.hash)}",
                )
            )
        # Carry the recomputed hash, never the stored one. Trusting the stored
        # value here would stop an edit from reaching the next receipt, and a
        # chain where tampering does not propagate is just a list.
        expected_prev = recomputed
        last = r.hash

    return Verification(ok=not problems, length=count, head=last, problems=problems)


def short(h: str, n: int = 10) -> str:
    return h if len(h) <= n * 2 else f"{h[:n]}…{h[-4:]}"


def usd(micro: int) -> str:
    """
    Widen the decimals until the printed figure reads back as the same number,
    so a saving is never shown as larger than it is.
    """
    dollars = micro / 1_000_000
    for places in range(2, 7):
        shown = f"{dollars:.{places}f}"
        if float(shown) == dollars:
            return f"${shown}"
    return f"${dollars:.6f}"


def usd_saving(micro: int) -> str:
    """
    A saving is rounded down to cents. Costs round up and savings round down, so
    neither number is ever flattering by accident.
    """
    cents = int(micro // 10_000)
    return f"${cents // 100}.{cents % 100:02d}"
