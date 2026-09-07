"""
A read-only window onto what Steward did.

The command line is the product; this is the same review rendered for someone
who has been sent a link. It runs the real review against live prices, so a
visitor sees today's catalogue rather than a recording. Nothing here can change
a mandate or apply a switch: the page has no writes at all.
"""

from __future__ import annotations

import html
import json
import os
import threading
import time
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from steward.ledger import Receipt, short, usd, usd_saving, verify
from steward.mandate import Mandate
from steward.review import Review, load_workloads, run_review

CACHE_SECONDS = 120

_lock = threading.Lock()
_cached: tuple[float, Review] | None = None


def current_review() -> Review:
    """
    One shared review, refreshed a couple of minutes at a time. Every visitor
    hitting the live catalogue would be rude to it and would also mean two
    people reading the same link see different numbers.
    """
    global _cached
    with _lock:
        if _cached and time.time() - _cached[0] < CACHE_SECONDS:
            return _cached[1]
        review = run_review()
        _cached = (time.time(), review)
        return review


# ---------------------------------------------------------------- presentation

CSS = """
:root {
  --ink:#0a0b0d; --panel:#121418; --panel-2:#171a1f; --line:#23272e;
  --text:#e9ecf1; --muted:#8d95a3; --accent:#7cf5c4; --accent-ink:#05231a;
  --warn:#ffb454; --bad:#ff6b6b; --radius:14px;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--ink);color:var(--text);
  font-family:ui-sans-serif,-apple-system,"SF Pro Text","Helvetica Neue",Arial,
  "PingFang SC","Microsoft YaHei",sans-serif;font-size:15px;line-height:1.6;
  -webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.mono{font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
  font-size:12.5px;word-break:break-all}
.shell{max-width:1000px;margin:0 auto;padding:0 20px 80px}
header.top{position:sticky;top:0;z-index:20;background:rgba(10,11,13,.86);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
header.top .row{max-width:1000px;margin:0 auto;padding:14px 20px;display:flex;
  align-items:center;justify-content:space-between;gap:10px 16px;flex-wrap:wrap}
.brand{display:flex;align-items:baseline;gap:10px;flex-shrink:0}
.brand b{font-size:16px;letter-spacing:.2px}
.brand span{color:var(--muted);font-size:12.5px}
nav{display:flex;gap:16px;flex-wrap:wrap}
nav a{color:var(--muted);font-size:13.5px}
nav a.on{color:var(--text)}
h1{font-size:26px;line-height:1.25;margin:34px 0 8px;letter-spacing:-.2px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.9px;color:var(--muted);
  margin:36px 0 12px;font-weight:600}
p.lede{color:var(--muted);margin:0 0 8px;max-width:66ch}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;margin:10px 0}
.card.escalated{border-color:#4a3d1c;background:linear-gradient(180deg,#1b1710,var(--panel))}
.card h3{margin:0 0 4px;font-size:15.5px}
.card .why{color:var(--muted);margin:0}
.meta{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:10px;font-size:12.5px;
  color:var(--muted)}
.meta b{color:var(--text);font-weight:600}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;
  border:1px solid var(--line);color:var(--muted);vertical-align:2px}
.tag.applied{color:var(--accent);border-color:#1f4a3b}
.tag.escalated{color:var(--warn);border-color:#4a3d1c}
.tag.refused{color:var(--muted)}
.headline{display:flex;flex-wrap:wrap;gap:10px 26px;align-items:baseline;
  border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;
  background:var(--panel-2);margin:10px 0 4px}
.headline div{min-width:110px}
.headline b{display:block;font-size:22px;letter-spacing:-.3px}
.headline span{color:var(--muted);font-size:12.5px}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:13.5px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);
  vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;
  letter-spacing:.6px}
.scroll{overflow-x:auto}
.ok{color:var(--accent)}
.bad{color:var(--bad)}
footer{color:var(--muted);font-size:12.5px;margin-top:48px;
  border-top:1px solid var(--line);padding-top:16px}
code{background:var(--panel-2);border:1px solid var(--line);border-radius:6px;
  padding:1px 6px;font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
pre{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:14px 16px;overflow-x:auto;font-size:12.5px;line-height:1.55}
"""

NAV = (
    ("/", "Morning report"),
    ("/mandate", "Mandate"),
    ("/receipts", "Receipts"),
    ("/verify", "Verify"),
)


def e(text: object) -> str:
    return html.escape(str(text))


def page(path: str, title: str, body: str) -> bytes:
    links = "".join(
        f'<a href="{href}" class="{"on" if href == path else ""}">{e(label)}</a>'
        for href, label in NAV
    )
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} — Sumplus Steward</title>
<style>{CSS}</style></head><body>
<header class="top"><div class="row">
  <div class="brand"><b>Sumplus Steward</b><span>spend review, on a mandate</span></div>
  <nav>{links}</nav>
</div></header>
<main class="shell">{body}
<footer>
  Prices read live from <a href="https://router.sumplus.xyz/v1/models">router.sumplus.xyz/v1/models</a>,
  refreshed every {CACHE_SECONDS} seconds. This page is read-only: it applies nothing and changes no mandate.
  Source: <a href="https://github.com/sumplus-real/sumplus-steward">github.com/sumplus-real/sumplus-steward</a>.
</footer>
</main></body></html>"""
    return doc.encode("utf-8")


def finding_card(f, kind: str) -> str:
    move = f"{e(f.from_model)} → {e(f.to_model)}" if f.to_model else e(f.from_model)
    # Only an applied change has actually saved anything. On the others the
    # figure is what the move would be worth, and calling it a saving would
    # book money that is still being spent.
    if f.decision == "applied":
        money = (
            f"<span>was <b>{e(usd(f.monthly_now_micro_usd))}</b> a month</span>"
            f"<span>now <b>{e(usd(f.monthly_after_micro_usd))}</b> a month</span>"
            f"<span>saving <b>{e(usd_saving(f.saving_micro_usd))}</b></span>"
        )
    elif f.saving_micro_usd > 0:
        money = (
            f"<span>costs <b>{e(usd(f.monthly_now_micro_usd))}</b> a month</span>"
            f"<span>the move would cost <b>{e(usd(f.monthly_after_micro_usd))}</b></span>"
            f"<span>on the table <b>{e(usd_saving(f.saving_micro_usd))}</b></span>"
        )
    else:
        money = f"<span>costs <b>{e(usd(f.monthly_now_micro_usd))}</b> a month</span><span>nothing cheaper fits</span>"
    return f"""<div class="card {kind}">
  <h3>{e(f.workload)} <span class="tag {kind}">{e(f.decision)}</span></h3>
  <p class="why">{e(f.reason)}</p>
  <div class="meta">
    <span class="mono">{move}</span>
    {money}
  </div>
</div>"""


def report_page(review: Review) -> str:
    esc = review.escalated
    app = review.applied
    left = [f for f in review.findings if f.decision == "refused"]

    parts = [
        "<h1>The review Steward just ran</h1>",
        "<p class=\"lede\">Loading this page ran the review for real: five "
        "workloads priced against every live model in the catalogue, a few "
        "minutes of cache at most. Steward applied what its mandate plainly "
        "covers and left the rest for a person, with a sentence for each.</p>",
        f"""<div class="headline">
          <div><b>{len(esc)}</b><span>for you to decide</span></div>
          <div><b>{len(app)}</b><span>done on its own</span></div>
          <div><b>{e(usd_saving(review.monthly_saving_micro_usd))}</b><span>saved per month</span></div>
          <div><b>{review.models_seen}</b><span>models priced</span></div>
          <div><b>{len(review.receipts)}</b><span>receipts</span></div>
        </div>""",
    ]

    if esc:
        parts.append("<h2>Yours to decide</h2>")
        parts += [finding_card(f, "escalated") for f in esc]
    if app:
        parts.append("<h2>Steward handled these</h2>")
        parts += [finding_card(f, "applied") for f in app]
    if left:
        parts.append("<h2>Left alone</h2>")
        parts += [finding_card(f, "refused") for f in left]

    parts.append(
        f'<h2>Chain head</h2><p class="mono">{e(review.ledger.head)}</p>'
        '<p class="lede">Every line above has a receipt behind it, including the '
        'lines where the decision was to do nothing. <a href="/verify">Check the chain</a>.</p>'
    )
    return "\n".join(parts)


def mandate_page() -> str:
    m = Mandate()
    workloads = load_workloads()
    rows = "".join(
        f"<tr><td><b>{e(w.name)}</b><br><span class='mono'>{e(w.model)}</span></td>"
        f"<td>{e(w.note)}</td>"
        f"<td>{w.needs_context:,}</td>"
        f"<td>{e(w.min_tier)}</td>"
        f"<td>{'yes' if w.quality_sensitive else 'no'}</td>"
        f"<td>{'yes' if w.name in m.pinned else 'no'}</td></tr>"
        for w in workloads
    )
    return f"""<h1>The mandate is the product</h1>
<p class="lede">An agent that asks about everything is a worse inbox. An agent
that asks about nothing is a liability. The line between them is written down,
and Steward never argues with it.</p>
<h2>Who owns which change</h2>
<div class="scroll"><table>
<tr><th>Situation</th><th>Who owns it</th></tr>
<tr><td>Workload is pinned</td><td>Nobody touches it. Steward reports and stops.</td></tr>
<tr><td>Destination is not <code>live</code></td><td>Refused. Production does not move onto a preview model.</td></tr>
<tr><td>Destination has less context than the workload needs</td><td>Refused.</td></tr>
<tr><td>Saving under {e(usd(m.min_monthly_saving_micro_usd))} a month</td><td>Refused. Churn is not worth it.</td></tr>
<tr><td>Workload marked quality sensitive</td><td><b>Yours.</b> Steward states the saving and waits.</td></tr>
<tr><td>Everything else</td><td>Steward's, and it does it.</td></tr>
</table></div>
<h2>The workloads it looks after</h2>
<div class="scroll"><table>
<tr><th>Workload</th><th>What it does</th><th>Context needed</th><th>Capability floor</th><th>Quality sensitive</th><th>Pinned</th></tr>
{rows}
</table></div>
<p class="lede">The capability floor is an absolute band, not a quantile of
whatever is in the catalogue today, because a floor that moves with the
candidate list is not a promise anyone can rely on.</p>"""


def receipts_page(review: Review) -> str:
    rows = "".join(
        f"<tr><td>{r.seq}</td><td class='mono'>{e(r.at)}</td>"
        f"<td><b>{e(r.action)}</b><br><span class='mono'>{e(r.subject)}</span></td>"
        f"<td><span class='tag {e(r.decision)}'>{e(r.decision)}</span></td>"
        f"<td>{e(r.reason)}</td>"
        f"<td class='mono'>{e(short(r.hash))}</td></tr>"
        for r in review.receipts
    )
    return f"""<h1>Receipts</h1>
<p class="lede">Including the decisions not to act. A record with the refusals
removed is not a record of the run.</p>
<div class="scroll"><table>
<tr><th>#</th><th>At</th><th>Action</th><th>Decision</th><th>Reason</th><th>Hash</th></tr>
{rows}
</table></div>
<p class="lede">Machine-readable at <a href="/api/receipts.json">/api/receipts.json</a>.
Each receipt commits to its own fields and to the hash of the one before it:</p>
<pre>hash = sha256(seq, at, action, subject, saving, decision, reason, payload_hash, prev_hash)</pre>"""


def verify_page(review: Review) -> str:
    genuine = verify(review.receipts)

    # Edit one receipt and show what the same check says about it. The copy is
    # rebuilt from the originals every request, so nothing on this page mutates
    # the chain the other pages read.
    victim = min(1, len(review.receipts) - 1)
    edited: list[Receipt] = [replace(r) for r in review.receipts]
    edited[victim] = replace(edited[victim], saving_micro_usd=edited[victim].saving_micro_usd + 5_000_000)
    broken = verify(edited)

    def block(v, title: str, note: str) -> str:
        state = (
            '<span class="ok">accepted</span>' if v.ok else '<span class="bad">rejected</span>'
        )
        problems = "".join(
            f"<tr><td>{p.seq}</td><td class='mono'>{e(p.kind)}</td><td>{e(p.detail)}</td></tr>"
            for p in v.problems
        )
        table = (
            f"<div class='scroll'><table><tr><th>#</th><th>Kind</th><th>Detail</th></tr>{problems}</table></div>"
            if problems
            else ""
        )
        return f"""<div class="card">
  <h3>{e(title)} — {state}</h3>
  <p class="why">{e(note)}</p>
  <div class="meta"><span>{v.length} receipts</span>
    <span>claimed head <span class="mono">{e(short(v.head))}</span></span></div>
  {table}
</div>"""

    return f"""<h1>Check the chain</h1>
<p class="lede">The verifier recomputes every receipt from its own contents and
carries the recomputed hash forward. It trusts none of the stored hashes, which
is the whole point: a chain where tampering does not propagate is just a list.</p>
{block(genuine, "The genuine chain", "Recomputed from the receipts alone.")}
{block(broken, f"The same chain with receipt {victim} edited", "One number changed. The check catches it twice: the edited receipt no longer hashes to what it carries, and the receipt after it points at a hash nothing produces.")}
<p class="lede">Notice that the claimed head is the same in both. It would be:
it is a number stored on the last receipt, and an editor has no reason to
change it. A stored head proves nothing on its own, which is exactly why the
check recomputes rather than compares.</p>
<h2>Run it yourself</h2>
<pre>git clone https://github.com/sumplus-real/sumplus-steward
cd sumplus-steward &amp;&amp; python run.py --audit</pre>
<p class="lede">A verifier that always says yes is worth nothing, so the test
suite asserts both halves of the break. Weakening the verifier on purpose turns
it red; that was checked rather than assumed.</p>"""


# ---------------------------------------------------------------------- server


class Handler(BaseHTTPRequestHandler):
    server_version = "SumplusSteward"

    def log_message(self, fmt: str, *args: object) -> None:  # quieter logs
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/healthz":
            self._send(b'{"ok":true}', "application/json")
            return

        try:
            if path == "/mandate":
                self._send(page(path, "Mandate", mandate_page()), "text/html; charset=utf-8")
                return

            review = current_review()

            if path == "/":
                self._send(page(path, "Morning report", report_page(review)), "text/html; charset=utf-8")
            elif path == "/receipts":
                self._send(page(path, "Receipts", receipts_page(review)), "text/html; charset=utf-8")
            elif path == "/verify":
                self._send(page(path, "Verify", verify_page(review)), "text/html; charset=utf-8")
            elif path == "/api/receipts.json":
                body = json.dumps([asdict(r) for r in review.receipts], indent=2).encode()
                self._send(body, "application/json")
            elif path == "/api/review.json":
                body = json.dumps(
                    {
                        "models_seen": review.models_seen,
                        "monthly_saving_micro_usd": review.monthly_saving_micro_usd,
                        "chain_head": review.ledger.head,
                        "findings": [asdict(f) for f in review.findings],
                    },
                    indent=2,
                ).encode()
                self._send(body, "application/json")
            else:
                self._send(
                    page(path, "Not here", "<h1>Not here</h1><p class='lede'>"
                         "Try the <a href='/'>morning report</a>.</p>"),
                    "text/html; charset=utf-8",
                    404,
                )
        except Exception as err:  # a live catalogue can be unreachable
            body = page(
                path,
                "Catalogue unreachable",
                "<h1>The catalogue did not answer</h1>"
                "<p class='lede'>Steward prices against live rates and will not "
                "show a saving computed from a stale price list. Refresh in a "
                f"moment.</p><p class='mono'>{e(err)}</p>",
            )
            self._send(body, "text/html; charset=utf-8", 503)


def main() -> None:
    port = int(os.environ.get("PORT", "4400"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Steward on http://0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
