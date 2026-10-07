#!/usr/bin/env python3
"""Tests for state.py against the bundled SAMPLE data. Runs on any machine: no network, no credentials,
no MCP dependency. The broker path is exercised end to end through sample_data/fake_broker.py.

    python test_state.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.pop("QUANT_STATE_CONFIG", None)          # always test the bundled sample, never a live config
sys.path.insert(0, str(HERE))
import state  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def case(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


case("config and data-source labelling")
b = state.books()
check("default config is the bundled sample, labelled SAMPLE", b["data_source"]["label"] == "SAMPLE", b["data_source"]["config"])
check("three books, every ledger present", set(b["books"]) == {"LONG", "ST", "ROTATION"} and all(v["ledger_exists"] for v in b["books"].values()))
check("every book has both graph snapshots and a broker", all(v["graphs_available"] == ["tech", "macro"] and v["broker_configured"] for v in b["books"].values()))
check("ledger_summary carries the label", state.ledger_summary("LONG")["data_source"]["label"] == "SAMPLE")
try:
    state.get_theme("NOPE", "x")
    check("unknown book rejected", False)
except state.BookError:
    check("unknown book rejected", True)
try:
    state.load_config("/nonexistent/config.json")
    check("missing config raises a clear error", False)
except state.ConfigError as e:
    check("missing config raises a clear error", "QUANT_STATE_CONFIG" in str(e))
with tempfile.TemporaryDirectory() as tmp:          # QUANT_STATE_CONFIG really switches the data source
    shutil.copytree(HERE / "sample_data", Path(tmp) / "data")
    cfg = Path(tmp) / "data" / "config.json"
    raw = json.loads(cfg.read_text())
    raw["label"] = "OVERRIDE-TEST"
    cfg.write_text(json.dumps(raw))
    out = subprocess.run([sys.executable, "-c", "import state, json; print(json.dumps(state.ledger_summary('ST')))"],
                         cwd=HERE, capture_output=True, text=True, env={**os.environ, "QUANT_STATE_CONFIG": str(cfg)})
    s = json.loads(out.stdout) if out.returncode == 0 else {}
    check("QUANT_STATE_CONFIG switches data source and label", s.get("data_source", {}).get("label") == "OVERRIDE-TEST"
          and s.get("open_positions") == 2, out.stderr[-200:] if out.returncode else s.get("data_source"))

case("resolve_entity: aliases to canonical hub names")
r = state.resolve_entity("LONG", "Micron")
check("'Micron' -> MU via alias", r["resolved"] and r["canonical"] == "MU" and r["match"].startswith("alias"), str(r))
check("'$mu' -> MU by name, case-insensitive", state.resolve_entity("LONG", "$mu")["canonical"] == "MU")
check("'AI infra' -> AI Infrastructure", state.resolve_entity("LONG", "AI infra")["canonical"] == "AI Infrastructure")
r = state.resolve_entity("LONG", "Gold")
check("'Gold' -> 'GLD — Gold' in the macro domain", r["canonical"] == "GLD — Gold" and r["domain"] == "macro", str(r))
check("'dxy' -> DXY by the short name before the dash", state.resolve_entity("LONG", "dxy")["canonical"] == "DXY — US Dollar Index")
r = state.resolve_entity("LONG", "no-such-thing")
check("unknown mention is not guessed", r["resolved"] is False and "new-hub" in r["note"])

case("graph: themes, tickers, fading theses")
t = state.get_theme("LONG", "AI Infrastructure")
check("theme found with direction and strength from its note", t["found"] and t["direction"] == "accelerating" and t["strength"] == "high")
check("realized track record: 3 outcomes, hit rate 0.67", t["realized"]["n"] == 3 and t["realized"]["hit_rate"] == 0.67, str(t["realized"]))
check("evidence sorted strongest first, quotes capped at 160 chars",
      [e["weight"] for e in t["evidence"]] == sorted([e["weight"] for e in t["evidence"]], reverse=True)
      and all(len(e["quote"]) <= 160 for e in t["evidence"]) and t["evidence_count"] == 5)
check("narrative stage reported", t["narrative_stage"] == "diffusing" and t["stage_transition"] == "emerging->diffusing")
check("evidence_limit respected", len(state.get_theme("LONG", "AI Infrastructure", evidence_limit=2)["evidence"]) == 2)
t = state.get_theme("LONG", "Micron")
check("get_theme resolves an alias first ('Micron' -> MU ticker)", t["found"] and t["hub"] == "MU" and t["type"] == "ticker")
tc = state.get_ticker_context("LONG", "MU")
check("ticker context includes the open MU position", [p["shares"] for p in tc["ledger"]["open"]] == [10])
tc = state.get_ticker_context("LONG", "KLAC")
check("ticker context includes KLAC's last close", tc["ledger"]["last_close"]["verdict"] == "closed-loser")
f = state.fading_theses("LONG")
check("4 fading hubs, worst first (Global Liquidity)", f["count"] == 4 and f["hubs"][0]["hub"] == "Global Liquidity",
      str([(h["hub"], len(h["reasons"])) for h in f["hubs"]]))
check("ST has its own graph (2 fading hubs)", state.fading_theses("ST")["count"] == 2)
gm = state.graph_meta("LONG")
check("graph_meta reports both domains and the contradiction flag", set(gm["domains"]) == {"tech", "macro"}
      and gm["domains"]["macro"]["contradiction_flags"] == 1)

case("ledgers and outcomes")
s = state.ledger_summary("LONG")
check("LONG summary: 3 open, 5 closed, equity and version", s["open_positions"] == 3 and s["closed_positions"] == 5
      and s["equity"] == 101234.56 and s["strategy_version"] == "LONG-v1.0")
p = state.get_positions("ROTATION")
check("rotation positions keep rank and weights", len(p["positions"]) == 3 and all("rank" in x and "target_weight" in x for x in p["positions"]))
po = state.get_pick_outcomes("LONG", since="2026-09-20")
check("4 closes since 2026-09-20", po["count"] == 4 and {c["ticker"] for c in po["closes"]} == {"VLO", "KLAC", "FXY", "XLE"})
check("ticker filter", state.get_pick_outcomes("LONG", ticker="amat")["count"] == 1)
hr = state.hit_rate("LONG", strategy_version="LONG-v1.0")
check("v1.0 cohort: 4 graded, 2 wins, 1 flat, hit rate 0.5", (hr["n"], hr["wins"], hr["flats"], hr["hit_rate"]) == (4, 2, 1, 0.5), str(hr))
check("all cohorts: 5 graded, hit rate 0.4 (cohorts kept apart)", state.hit_rate("LONG")["hit_rate"] == 0.4)
check("rotation outcomes graded from rotation P&L", state.hit_rate("ROTATION")["n"] == 2 and state.hit_rate("ROTATION")["wins"] == 1)
sr = state.score_run("LONG", "2026-08-01")
check("score_run 2026-08-01: closed VLO/KLAC/FXY, still holds MU and TLT",
      {c["ticker"] for c in sr["closed"]} == {"VLO", "KLAC", "FXY"} and {o["ticker"] for o in sr["still_open"]} == {"MU", "TLT"}
      and (sr["wins"], sr["losses"], sr["flats"]) == (1, 1, 1) and sr["realized_pnl"] == 418.95 and sr["run_note_exists"], str(sr["realized_pnl"]))
check("list_runs (ST): latest 2026-10-01", state.list_runs("ST")["latest"][-1] == "2026-10-01")
check("run_note returns markdown", state.run_note("ST", "2026-10-01").startswith("---"))

case("forecast ledger, source registry, ingest marker")
fr = state.forecast_rows(book="LONG", ticker="MU")
check("forecast rows for LONG MU: 2, half positive", fr["count"] == 2 and fr["positive_adj_ret_share"] == 0.5)
check("filter by cited source", state.forecast_rows(author="sample-bank-desk")["count"] == 2)
r = state.resolve_source("@ExampleAnalyst")
check("'@ExampleAnalyst' -> example-analyst (alias, @ ignored)", r["resolved"] and r["slug"] == "example-analyst" and r["platform"] == "x")
check("'Sample Bank' -> sample-bank-desk", state.resolve_source("Sample Bank")["slug"] == "sample-bank-desk")
r = state.resolve_source("someone-new")
check("unregistered handle -> unattributed, never guessed", not r["resolved"] and r["attributed_to"] == "unattributed")
check("ingest marker readable", state.ingest_status()["date"] == "2026-10-01")

case("broker: read-only, end to end through the sample adapter")
for sub in ("submit", "rebalance"):
    try:
        state.broker_snapshot("ST", sub)
        check(f"'{sub}' refused before any process starts", False)
    except PermissionError:
        check(f"'{sub}' refused before any process starts", True)
snap = state.broker_snapshot("ST")
check("ST snapshot parsed from the JSON block", snap["rc"] == 0 and len(snap["data"]["positions"]) == 2 and snap["data"]["equity"] == 98500.0)
snap = state.broker_snapshot("ROTATION")
check("ROTATION snapshot parsed from the text table (4 positions)", len(snap["data"]["positions"]) == 4
      and snap["data"]["positions"][0] == {"symbol": "XLK", "side": "long", "qty": 40.0, "avg_entry_price": 230.0}, str(snap["data"]["positions"][:1]))
d = state.reconcile_diff("ST")
check("ST ledger and broker are in sync", d["in_sync"] is True, str(d))
d = state.reconcile_diff("ROTATION")
check("ROTATION diff finds the extra XLU at the broker", d["in_sync"] is False and d["only_at_broker"] == ["XLU"] and not d["only_in_ledger"])
d = state.reconcile_diff("LONG")
check("LONG (simulated, no mirror) reports every ledger position as ledger-only", d["only_in_ledger"] == ["GLD", "MU", "TLT"])
out = subprocess.run([sys.executable, str(HERE / "sample_data" / "fake_broker.py"), "--book", "ST", "submit"], capture_output=True, text=True)
check("the sample adapter itself also refuses 'submit'", out.returncode == 2 and "REFUSED" in out.stderr)

n = sum(results)
print(f"\n{'=' * 78}\n{n}/{len(results)} checks passed")
sys.exit(0 if n == len(results) else 1)
