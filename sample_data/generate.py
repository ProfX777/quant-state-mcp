#!/usr/bin/env python3
"""Regenerate the bundled SAMPLE dataset.

Every number, name, quote and source in this folder is invented for demonstration. It has the same
shape as a real deployment (three books, two research domains per book, hub notes with front-matter,
a graph snapshot per domain, ledgers, run notes, a forecast ledger, a source registry and an ingest
marker) so the server, the tests and CI run on any machine without access to real data.

    python sample_data/generate.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def write(rel, text):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def write_json(rel, obj):
    write(rel, json.dumps(obj, indent=1) + "\n")


def hub(rel, aliases, direction, strength, last_assessed, outcomes=(), body=""):
    """A theme or company page: YAML-style front-matter + a short body."""
    fm = ["source: Hub", "aliases:"] + [f"- {a}" for a in aliases]
    fm += [f"direction: {direction}", f"strength: {strength}", f"last_assessed: {last_assessed}"]
    if outcomes:
        fm.append("realized_outcomes:")
        for o in outcomes:
            fm.append(f"- date_closed: {o['date_closed']}")
            for k in ("ticker", "direction", "outcome", "pnl_pct", "horizon"):
                fm.append(f"  {k}: {o[k]}")
        wins = sum(1 for o in outcomes if o["outcome"] == "win")
        fm += [f"realized_n: {len(outcomes)}", f"realized_hit_rate: {round(wins / len(outcomes), 2)}"]
    write(rel, "---\n" + "\n".join(fm) + "\n---\n\n" + (body or "Sample hub note. Invented content.") + "\n")


def row(name, kind, direction, strength, age, velocity, pagerank, in_degree, stale=None):
    stale = (age is not None and age > 30) if stale is None else stale
    momentum = 1.5 if direction in ("accelerating", "decelerating") else 1.0
    return {"name": name, "type": kind, "direction": direction, "strength": strength, "age_days": age,
            "stale": stale, "pagerank": pagerank, "betweenness": round(pagerank / 2, 4), "community": 1,
            "velocity": velocity, "momentum": momentum,
            "deep_read_score": round(pagerank * (1 + max(velocity, 0)) * momentum, 4),
            "egonet_density": 0.3, "in_degree": in_degree, "out_degree": 2}


def evidence(source, weight, age, stance, conf, quote):
    return {"source_note": source, "etype": "trend_fit", "conf": conf, "weight": weight, "age_days": age,
            "source_type": "x-bookmark", "quote": quote, "stance": stance}


def graph(today, rows, hub_evidence, stages, contradictions=()):
    sources = [{"name": f"Sample note {i}", "type": "source", "direction": None, "strength": None,
                "age_days": i, "stale": False, "pagerank": 0.003, "betweenness": 0.0, "community": 1,
                "velocity": 0, "momentum": 1.0, "deep_read_score": 0.003, "egonet_density": 0.0,
                "in_degree": 0, "out_degree": 2} for i in range(1, 6)]
    hubs = [r for r in rows if r["type"] in ("trend", "ticker")]
    return {"vault": "sample", "generated": f"{today}T07:30:00", "today": today, "recent_window_days": 14,
            "edge_half_life_days": 45, "edge_weight_floor": 0.05, "stale_assessment_days": 30,
            "counts": {"nodes": len(rows) + len(sources), "edges": 6 * len(hubs),
                       "trends": sum(r["type"] == "trend" for r in hubs),
                       "tickers": sum(r["type"] == "ticker" for r in hubs),
                       "sources": len(sources), "stale_hubs": sum(bool(r["stale"]) for r in hubs)},
            "connectivity": {"post": {"n_components": 2, "largest": len(rows) + len(sources) - 1}},
            "rows": rows + sources, "edges": [], "hub_evidence": hub_evidence,
            "narrative_stages": stages, "contradictions": list(contradictions)}


def stage(now, prior, diversity):
    return {"narrative_stage": now, "source_diversity_count": diversity, "sell_side_tag": "none",
            "prior_stage": prior, "stage_transition": f"{prior}->{now}"}


def run_note(rel, date, book, body):
    write(rel, f"---\ndate: {date}\nbook: {book}\ndata: SAMPLE\n---\n\n# {book} run {date} (sample)\n\n{body}\n")


def main():
    # ------------------------------------------------------------------ LONG book: hubs + graphs
    hub("long/tech/trends/AI Infrastructure.md", ["AI infra", "AI infrastructure buildout"], "accelerating",
        "high", "2026-09-17", outcomes=[
            {"date_closed": "2026-08-15", "ticker": "NVDA", "direction": "LONG", "outcome": "win", "pnl_pct": 9.5, "horizon": "Medium"},
            {"date_closed": "2026-08-29", "ticker": "SMH", "direction": "LONG", "outcome": "win", "pnl_pct": 4.1, "horizon": "Medium"},
            {"date_closed": "2026-09-20", "ticker": "KLAC", "direction": "LONG", "outcome": "loss", "pnl_pct": -6.0, "horizon": "Medium"}])
    hub("long/tech/trends/Memory Supercycle.md", ["HBM cycle", "memory upcycle"], "stable", "med", "2026-08-10")
    hub("long/tech/tickers/MU.md", ["Micron", "Micron Technology", "$MU"], "accelerating", "high", "2026-09-15")
    hub("long/tech/tickers/KLAC.md", ["KLA", "KLA Corp"], "decelerating", "low", "2026-09-10")
    hub("long/macro/trends/Global Liquidity.md", ["liquidity", "central bank liquidity"], "decelerating", "med", "2026-09-08")
    hub("long/macro/trends/Sticky Inflation.md", ["inflation", "sticky CPI"], "stable", "low", "2026-09-12")
    hub("long/macro/tickers/GLD — Gold.md", ["Gold", "gold bullion", "$GLD"], "accelerating", "high", "2026-09-18")
    hub("long/macro/tickers/DXY — US Dollar Index.md", ["US dollar", "dollar index"], "stable", "med", "2026-08-31")

    write_json("long/tech/graph.json", graph("2026-09-20", [
        row("AI Infrastructure", "trend", "accelerating", "high", 3, 4, 0.081, 12),
        row("Memory Supercycle", "trend", "stable", "med", 41, 0, 0.044, 6),
        row("MU", "ticker", "accelerating", "high", 5, 2, 0.052, 8),
        row("KLAC", "ticker", "decelerating", "low", 10, -1, 0.021, 3),
    ], {
        "AI Infrastructure": [
            evidence("Sample note 1", 0.71, 2, "bullish", 0.9, "hyperscaler capex guides were raised again this quarter"),
            evidence("Sample note 2", 0.62, 4, "bullish", 0.8, "power, not chips, is now the binding constraint"),
            evidence("Sample note 3", 0.55, 6, "neutral", 0.7, "order books look full into next year"),
            evidence("Sample note 4", 0.41, 9, "bearish", 0.6, "rental rates for older GPUs are starting to slip"),
            evidence("Sample note 5", 0.30, 12, "bullish", 0.5, "inference demand keeps surprising to the upside"),
        ],
        "MU": [
            evidence("Sample note 1", 0.66, 2, "bullish", 0.85, "contract memory prices rose again in the latest check"),
            evidence("Sample note 3", 0.40, 6, "neutral", 0.6, "inventory at module makers is back to normal"),
        ],
    }, {"AI Infrastructure": stage("diffusing", "emerging", 5), "MU": stage("diffusing", "diffusing", 3)}))

    write_json("long/macro/graph.json", graph("2026-09-20", [
        row("Global Liquidity", "trend", "decelerating", "med", 12, -2, 0.061, 9),
        row("Sticky Inflation", "trend", "stable", "low", 8, 1, 0.035, 5),
        row("GLD — Gold", "ticker", "accelerating", "high", 2, 3, 0.048, 7),
        row("DXY — US Dollar Index", "ticker", "stable", "med", 20, 0, 0.030, 4),
    ], {
        "Global Liquidity": [evidence("Sample note 2", 0.58, 3, "bearish", 0.8, "balance-sheet runoff is draining reserves faster than expected")],
        "GLD — Gold": [evidence("Sample note 4", 0.63, 1, "bullish", 0.9, "official-sector buying set another record")],
    }, {"Global Liquidity": stage("crowded", "diffusing", 4), "GLD — Gold": stage("diffusing", "emerging", 4)},
        contradictions=[{"rule": "R2", "hub": "DXY — US Dollar Index", "detail": "sample contradiction flag"}]))

    # ------------------------------------------------------------------ LONG ledger + runs
    def close(t, d, opened, closed, basis, px, sh, pnl, pct, verdict, outcome, sv, origin, horizon="Medium"):
        return {"ticker": t, "direction": d, "opened_date": opened, "closed_date": closed, "cost_basis": basis,
                "close_price": px, "shares": sh, "realized_pnl": pnl, "realized_pct": pct, "verdict": verdict,
                "outcome": outcome, "horizon": horizon, "strategy_version": sv, "originating_synthesis": origin,
                "price_basis": "sample"}

    write_json("long/ledger.json", {
        "meta": {"strategy_version": "LONG-v1.0", "as_of": "2026-09-20 (SAMPLE)", "starting_capital": 100000},
        "open_positions": [
            {"ticker": "MU", "direction": "LONG", "shares": 10, "cost_basis": 900.0, "opened_date": "2026-08-01",
             "stop": 760.0, "review_date": "2026-10-15", "horizon": "Medium", "entry_verdict": "enter",
             "size_factor": 1.0, "current_price_asof": 1000.0, "unrealized_pnl": 1000.0, "unrealized_pct": 11.11,
             "strategy_version": "LONG-v1.0", "originating_synthesis": "run 2026-08-01"},
            {"ticker": "GLD", "direction": "LONG", "shares": 15, "cost_basis": 380.0, "opened_date": "2026-08-08",
             "stop": 360.0, "review_date": "2026-12-01", "horizon": "Long", "entry_verdict": "enter",
             "size_factor": 1.0, "current_price_asof": 395.0, "unrealized_pnl": 225.0, "unrealized_pct": 3.95,
             "strategy_version": "LONG-v1.0", "originating_synthesis": "run 2026-08-08"},
            {"ticker": "TLT", "direction": "SHORT", "shares": 30, "cost_basis": 84.0, "opened_date": "2026-08-01",
             "stop": 86.0, "review_date": "2026-10-15", "horizon": "Medium", "entry_verdict": "scale",
             "size_factor": 0.5, "current_price_asof": 82.0, "unrealized_pnl": 60.0, "unrealized_pct": 2.38,
             "strategy_version": "LONG-v1.0", "originating_synthesis": "run 2026-08-01"},
        ],
        "closed_positions": [
            close("AMAT", "LONG", "2026-06-12", "2026-07-10", 600.0, 534.0, 5, -330.0, -11.0, "closed-stopped", "loss", "LONG-v0", "run 2026-06-12"),
            close("VLO", "LONG", "2026-08-01", "2026-09-20", 300.0, 360.0, 10, 600.0, 20.0, "closed-winner", "win", "LONG-v1.0", "run 2026-08-01"),
            close("KLAC", "LONG", "2026-08-01", "2026-09-20", 200.0, 188.0, 14, -168.0, -6.0, "closed-loser", "loss", "LONG-v1.0", "run 2026-08-01"),
            close("FXY", "LONG", "2026-08-01", "2026-09-20", 58.0, 57.71, 45, -13.05, -0.5, "closed-mixed", "flat", "LONG-v1.0", "run 2026-08-01"),
            close("XLE", "LONG", "2026-08-08", "2026-09-20", 58.0, 62.64, 100, 464.0, 8.0, "closed-winner", "win", "LONG-v1.0", "run 2026-08-08"),
        ],
        "transactions": [], "cash": 62000.0, "equity_asof": 101234.56, "gross_exposure_pct": 38.5,
        "realized_pnl_total": 552.95, "unrealized_pnl_total": 1285.0, "total_pnl": 1837.95, "total_return_pct": 1.84,
        "equity_history": [{"date": "2026-08-01", "equity": 100000.0, "note": "sample"},
                           {"date": "2026-09-20", "equity": 101234.56, "note": "sample"}],
        "flags": [],
    })
    run_note("long/runs/2026-08-01.md", "2026-08-01", "LONG", "Opened MU, TLT short, VLO, KLAC, FXY. All prices invented.")
    run_note("long/runs/2026-08-08.md", "2026-08-08", "LONG", "Opened GLD and XLE. All prices invented.")
    run_note("long/runs/2026-09-20.md", "2026-09-20", "LONG", "Review sweep: closed VLO, KLAC, FXY, XLE. All prices invented.")

    # ------------------------------------------------------------------ ST book
    hub("st/tech/trends/Semicap.md", ["semicap equipment", "WFE"], "stable", "med", "2026-08-26")
    hub("st/macro/trends/Energy Shock.md", ["oil shock", "energy supply shock"], "decelerating", "med", "2026-09-25")
    hub("st/macro/tickers/SPY — S&P 500.md", ["S&P 500", "SPX", "$SPY"], "accelerating", "high", "2026-09-29")
    write_json("st/tech/graph.json", graph("2026-10-01", [
        row("Semicap", "trend", "stable", "med", 35, 0, 0.040, 5)], {}, {}))
    write_json("st/macro/graph.json", graph("2026-10-01", [
        row("Energy Shock", "trend", "decelerating", "med", 6, -1, 0.052, 6),
        row("SPY — S&P 500", "ticker", "accelerating", "high", 2, 2, 0.060, 9)], {}, {}))
    write_json("st/ledger.json", {
        "meta": {"strategy_version": "ST-v1.1", "as_of": "2026-10-01 (SAMPLE)", "starting_capital": 100000},
        "open_positions": [
            {"ticker": "SPY", "direction": "LONG", "shares": 20, "cost_basis": 560.0, "opened_date": "2026-09-30",
             "stop": 550.0, "target": 580.0, "review_date": "2026-10-10", "horizon": "Swing",
             "current_price_asof": 566.0, "unrealized_pnl": 120.0, "unrealized_pct": 1.07,
             "strategy_version": "ST-v1.1", "originating_synthesis": "run 2026-09-30"},
            {"ticker": "USO", "direction": "SHORT", "shares": 40, "cost_basis": 75.0, "opened_date": "2026-09-30",
             "stop": 78.0, "target": 70.0, "review_date": "2026-10-08", "horizon": "Fast",
             "current_price_asof": 74.0, "unrealized_pnl": 40.0, "unrealized_pct": 1.33,
             "strategy_version": "ST-v1.1", "originating_synthesis": "run 2026-09-30"},
        ],
        "closed_positions": [
            close("QQQ", "LONG", "2026-09-22", "2026-09-26", 480.0, 492.0, 10, 120.0, 2.5, "closed-winner", "win", "ST-v1.1", "run 2026-09-22", "Fast"),
            close("XLP", "LONG", "2026-09-22", "2026-09-24", 84.0, 82.49, 50, -75.5, -1.8, "closed-stopped", "loss", "ST-v1.1", "run 2026-09-22", "Fast"),
            close("IWM", "LONG", "2026-09-23", "2026-10-01", 220.0, 220.66, 20, 13.2, 0.3, "closed-mixed", "flat", "ST-v1.1", "run 2026-09-23", "Swing"),
        ],
        "working_orders": [], "cash": 72000.0, "equity_asof": 98500.0, "gross_exposure_pct": 26.4,
        "realized_pnl_total": 57.7, "unrealized_pnl_total": 160.0, "total_return_pct": -1.5,
        "equity_history": [{"date": "2026-10-01", "equity": 98500.0, "note": "sample"}], "flags": [],
    })
    run_note("st/runs/2026-09-30.md", "2026-09-30", "ST", "Opened SPY long and USO short. All prices invented.")
    run_note("st/runs/2026-10-01.md", "2026-10-01", "ST", "Reconciled to broker: in sync. Closed IWM flat. All prices invented.")

    # ------------------------------------------------------------------ ROTATION book (ranks off the LONG graph)
    def rot(t, sh, basis, rank, tw, aw, comp, held):
        return {"ticker": t, "direction": "LONG", "shares": sh, "cost_basis": basis, "opened_date": "2026-09-01",
                "rank": rank, "target_weight": tw, "actual_weight": aw, "composite": comp, "days_held": held,
                "status": "open", "strategy_version": "ROTATION-v1.0"}
    write_json("rotation/ledger.json", {
        "meta": {"strategy_version": "ROTATION-v1.0", "as_of": "2026-09-26 (SAMPLE)", "starting_capital": 100000},
        "open_positions": [rot("XLK", 40, 230.0, 1, 0.34, 0.33, 1.8, 25), rot("XLI", 60, 130.0, 2, 0.33, 0.34, 1.4, 25),
                           rot("XLV", 50, 145.0, 3, 0.33, 0.33, 1.1, 25)],
        "closed_positions": [
            {"ticker": "XLE", "direction": "LONG", "opened_date": "2026-08-04", "closed_date": "2026-09-01", "shares": 70,
             "cost_basis": 100.0, "exit_price": 104.2, "realized_pnl": 294.0, "rotation_pnl_pct": 4.2, "days_held": 28,
             "close_reason": "rotated out (rank fell below cut-off)"},
            {"ticker": "XLB", "direction": "LONG", "opened_date": "2026-08-04", "closed_date": "2026-09-01", "shares": 40,
             "cost_basis": 90.0, "exit_price": 88.2, "realized_pnl": -72.0, "rotation_pnl_pct": -2.0, "days_held": 28,
             "close_reason": "rotated out (rank fell below cut-off)"},
        ],
        "cash": 58000.00, "equity_asof": 103210.0, "equity_history": [{"date": "2026-09-26", "equity": 103210.0, "note": "sample"}],
        "flags": [],
    })

    # ------------------------------------------------------------------ shared: registry, forecast ledger, ingest marker
    write("sources.yaml", """# SAMPLE source registry. All sources are fictional.
sources:
  - slug: example-analyst
    display: Example Analyst
    aliases: ["@ExampleAnalyst", "ExampleAnalyst", "Example Analyst"]
    platform: x
    type: independent
    status: active
  - slug: sample-bank-desk
    display: Sample Bank Macro Desk
    aliases: ["Sample Bank", "Sample Bank Desk"]
    platform: sellside
    type: sellside
    status: active
  - slug: demo-newsletter
    display: Demo Newsletter
    aliases: ["Demo Letter"]
    platform: substack
    type: independent
    status: active
""")
    with (ROOT / "forecast_ledger.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["book", "analyst", "date", "ticker", "heat", "direction", "version", "file", "fwd_ret", "adj_ret",
                    "authors", "author_n", "narrative_stage", "stage_transition", "market_cap", "cap_bucket"])
        w.writerows([
            ["LONG", "tech", "2026-08-01", "MU", 8.0, "LONG", "LONG-v1.0", "sample", 0.111, 0.085, "example-analyst;demo-newsletter", 2, "diffusing", "emerging->diffusing", 1.0e12, "mega"],
            ["LONG", "tech", "2026-08-08", "MU", 7.0, "LONG", "LONG-v1.0", "sample", -0.020, -0.031, "example-analyst", 1, "diffusing", "diffusing->diffusing", 1.0e12, "mega"],
            ["LONG", "macro", "2026-08-01", "GLD", 7.0, "LONG", "LONG-v1.0", "sample", 0.039, 0.012, "sample-bank-desk", 1, "crowded", "diffusing->crowded", "", "etf"],
            ["LONG", "tech", "2026-08-01", "KLAC", 6.0, "LONG", "LONG-v1.0", "sample", -0.060, -0.072, "demo-newsletter", 1, "emerging", "emerging->emerging", 9.0e10, "large"],
            ["ST", "macro", "2026-09-30", "SPY", 6.0, "LONG", "ST-v1.1", "sample", 0.011, 0.004, "sample-bank-desk", 1, "crowded", "crowded->crowded", "", "etf"],
        ])
    write_json("ingest_status.json", {
        "label": "SAMPLE", "date": "2026-10-01", "started": "2026-10-01T12:15:00Z", "finished": "2026-10-01T12:31:00Z",
        "routines": {"tech-video": {"status": "ok", "added": 3}, "macro-video": {"status": "ok", "added": 5},
                     "free-newsletters": {"status": "ok", "added": 1}},
        "cap_status": {"Tech library": 212, "Macro library": 240},
    })
    print(f"sample data written under {ROOT}")


if __name__ == "__main__":
    main()
