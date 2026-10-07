#!/usr/bin/env python3
"""Read-only tests for state.py against the LIVE system files (no writes, no broker, no network).
The broker path is exercised only through its refusal guard and a stubbed subprocess.

Run:  .venv/bin/python test_state.py   (or plain python3 — state.py has no MCP dependency)
"""
import json, sys, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import state

results = []
def check(name, cond, detail=""):
    results.append(cond); print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))
def case(t): print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")

case("books / graph meta")
b = state.books()
check("three books, all ledgers exist", set(b) == {"LONG", "ST", "ROTATION"} and all(v["ledger_exists"] for v in b.values()))
gm = state.graph_meta("LONG")
check("LONG graph meta has both vaults with counts", all("counts" in gm[v] for v in ("Research Mind", "Macro Mind")), str({v: gm[v].get("as_of") for v in gm}))
try:
    state.get_theme("NOPE", "x"); check("unknown book rejected", False)
except state.BookError:
    check("unknown book rejected", True)

case("resolve_entity (aliases -> canonical)")
r = state.resolve_entity("LONG", "Micron")
check("'Micron' -> MU via alias", r["resolved"] and r["canonical"] == "MU", str(r))
r = state.resolve_entity("LONG", "$mu")
check("'$mu' -> MU (cashtag, case-insensitive)", r["resolved"] and r["canonical"] == "MU")
r = state.resolve_entity("LONG", "AI infra")
check("'AI infra' -> AI Infrastructure", r["resolved"] and r["canonical"] == "AI Infrastructure", str(r))
r = state.resolve_entity("LONG", "Gold")
check("'Gold' resolves into the macro vault (GLD — Gold)", r["resolved"] and r["vault"] == "Macro Mind" and r["canonical"].startswith("GLD"), str(r))
r = state.resolve_entity("LONG", "no-such-thing-xyz")
check("miss -> resolved False, no guess", r["resolved"] is False and "new-hub" in r["note"])

case("get_theme / get_ticker_context / fading_theses")
t = state.get_theme("LONG", "AI Infrastructure")
check("AI Infrastructure found, direction accelerating, strength high", t["found"] and t["direction"] == "accelerating" and t["strength"] == "high", f"{t.get('direction')}/{t.get('strength')}")
check("realized track record surfaced (n=9 after today's write-backs)", t["realized"]["n"] == 9 and t["realized"]["hit_rate"] == 0.22, str(t["realized"]))
check("pagerank + evidence edges present", isinstance(t["pagerank"], float) and t["evidence_count"] > 0 and len(t["evidence"]) <= 8)
check("evidence rows are compact (quote <= 160 chars)", all(len(e["quote"]) <= 160 for e in t["evidence"]))
t2 = state.get_theme("LONG", "Micron")
check("get_theme resolves an alias first ('Micron' -> MU ticker hub)", t2["found"] and t2["hub"] == "MU" and t2["type"] == "ticker")
tc = state.get_ticker_context("LONG", "MU")
check("ticker context carries the open MU position (8 sh, interim-reviewed today)", any(p["ticker"] == "MU" and p["shares"] == 8 for p in tc["ledger"]["open"]), str(tc["ledger"]["open"]))
tc2 = state.get_ticker_context("LONG", "VLO")
check("ticker context: VLO last close is today's sweep (+29.34%)", tc2["ledger"]["last_close"]["closed_date"] == "2026-09-22" and tc2["ledger"]["last_close"]["verdict"] == "closed-winner", str(tc2["ledger"]["last_close"]))
f = state.fading_theses("LONG", limit=5)
check("fading_theses returns reasons, worst-first", f["count"] > 0 and all(h["reasons"] for h in f["hubs"]) and len(f["hubs"]) <= 5, f"{f['count']} hubs; top={f['hubs'][0]['hub']} {f['hubs'][0]['reasons']}")

case("ledgers")
s = state.ledger_summary("LONG")
check("LONG summary reflects today's sweep (9 open, equity 97,672.15, cash 50,589.08)", s["open_positions"] == 9 and s["equity"] == 97672.15 and s["cash"] == 50589.08, str({k: s[k] for k in ('open_positions', 'equity', 'cash')}))
check("LONG last equity mark is 2026-09-22", s["last_equity_mark"]["date"] == "2026-09-22")
st = state.ledger_summary("ST")
check("ST summary: flat book, 68 closes, ST-v1.1", st["open_positions"] == 0 and st["closed_positions"] == 68 and st["strategy_version"] == "ST-v1.1")
ro = state.ledger_summary("ROTATION")
check("ROTATION summary: 5 open, ROTATION-v1.0", ro["open_positions"] == 5 and ro["strategy_version"] == "ROTATION-v1.0")
p = state.get_positions("ROTATION")
check("rotation positions carry rank/target_weight (book-specific fields survive slimming)", all("rank" in x and "target_weight" in x for x in p["positions"]))
po = state.get_pick_outcomes("LONG", since="2026-09-22")
check("today's 8 closes via get_pick_outcomes(since)", po["count"] == 8 and {c["ticker"] for c in po["closes"]} == {"MOS", "XLE", "VLO", "BESIY", "LITE", "FXY", "RSP", "KLAC"}, str(po["count"]))
hr = state.hit_rate("LONG", strategy_version="LONG-v1.0")
check("LONG-v1.0 hit rate 4/13 = 0.308 (matches the rebuilt scorecard)", hr["n"] == 13 and hr["wins"] == 4 and hr["hit_rate"] == 0.308, str(hr))
hr0 = state.hit_rate("LONG")
check("all-cohort hit rate grades legacy closes from verdict/pct (n > 13)", hr0["n"] > 13 and hr0["hit_rate"] is not None, str({k: hr0[k] for k in ('n', 'wins', 'hit_rate')}))
sr = state.score_run("LONG", "2026-08-03")
check("score_run 2026-08-03: LITE/FXY/RSP closed today, AMD still open, run note exists",
      {c["ticker"] for c in sr["closed"]} >= {"LITE", "FXY", "RSP"} and any(o["ticker"] == "AMD" for o in sr["still_open"]) and sr["run_note_exists"], str({k: sr[k] for k in ('wins', 'losses', 'flats', 'realized_pnl')}))
lr = state.list_runs("ST", limit=3)
check("ST run notes listed, latest 2026-09-15", lr["latest"][-1] == "2026-09-15", str(lr["latest"]))
check("run_note returns the markdown", state.run_note("ST", "2026-09-15").startswith("---"))

case("forecast ledger / registry / ingest")
fr = state.forecast_rows(book="LONG", ticker="MU", limit=5)
check("forecast rows for LONG MU exist with adj_ret share", fr["count"] > 0 and fr["positive_adj_ret_share"] is not None, str({k: fr[k] for k in ('count', 'positive_adj_ret_share')}))
rs = state.resolve_source("@GavinSBaker")
check("'@GavinSBaker' -> gavinbaker (alias, @ stripped)", rs["resolved"] and rs["slug"] == "gavinbaker" and rs["platform"] == "x", str(rs.get("slug")))
rs2 = state.resolve_source("firesidealpha")
check("unregistered handle -> unattributed, flagged as registry candidate", not rs2["resolved"] and rs2["attributed_to"] == "unattributed")
ig = state.ingest_status()
check("ingest_status is the 2026-09-20 manual run, all six routines ok", ig["date"] == "2026-09-20" and all(v["status"] == "ok" for v in ig["routines"].values()), str(ig["date"]))

case("broker guard (no real call)")
try:
    state.broker_snapshot("ST", "submit"); check("'submit' refused by construction", False)
except PermissionError:
    check("'submit' refused by construction", True)
try:
    state.broker_snapshot("ROTATION", "rebalance"); check("'rebalance' refused by construction", False)
except PermissionError:
    check("'rebalance' refused by construction", True)
calls = []
class _P:
    def __init__(self, out): self.stdout, self.stderr, self.returncode = out, "", 0
def fake_run(cmd, **kw):
    calls.append(cmd)
    if "--json" in cmd:
        return _P('PAPER account PA31… | ACTIVE | equity $86721.96 | cash $86721.96\n===JSON===\n' + json.dumps({"positions": [], "equity": 86721.96, "cash": 86721.96}))
    return _P("PAPER account PA3I… | equity $102,471.65 | cash $57,442.99\npositions (2):\n  NVDA   long  qty       10 avg $  120.5 \n  GEV    long  qty        3 avg $  950.0 \n")
state.subprocess.run = fake_run
snap = state.broker_snapshot("ST")
check("ST snapshot parses the ===JSON=== block; never passes --live/--auto/--allow-live", snap["data"]["equity"] == 86721.96 and not any(f in calls[-1] for f in ("--live", "--auto", "--allow-live")))
d = state.reconcile_diff("ROTATION")
check("ROTATION diff parses the text table and compares to the ledger", set(d) >= {"only_in_ledger", "only_at_broker", "qty_or_side_mismatch"} and d["broker_equity"] == 102471.65, str({k: d[k] for k in ('in_sync', 'only_at_broker')}))
check("every broker call used an allowed subcommand", all(any(c in cmd for c in ("account", "reconcile")) for cmd in calls))

n = sum(results); print(f"\n{'=' * 78}\n{n}/{len(results)} checks passed"); sys.exit(0 if n == len(results) else 1)
