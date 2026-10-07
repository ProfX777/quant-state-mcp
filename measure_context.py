#!/usr/bin/env python3
"""Honest, static context measurement: bytes an agent must ingest to answer a stage question by
READING FILES versus by calling the typed tool. Token counts are approximated as bytes/4 and
labelled as such; this is a reproducible lower-bound proxy, NOT a live per-run token measurement
(that requires instrumenting an actual stage run — see README).

Each row is a concrete question a pipeline stage asks today, the file(s) it would read to answer
it, and the tool response that answers the same question."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import state

B = state.BOOKS


def size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def tool_bytes(obj) -> int:
    return len(json.dumps(obj, default=str))


rows = []
# 1. track-outcomes Mode 2: "what is the LONG book's open exposure + last mark?"
files = size(B["LONG"]["ledger"])
tools = tool_bytes(state.get_positions("LONG")) + tool_bytes(state.ledger_summary("LONG"))
rows.append(("LONG open exposure + headline (track-outcomes Mode 2 pre-read)", "Portfolio_Ledger.json", files, "get_positions + ledger_summary", tools))
# 2. synthesis: "is AI Infrastructure still supported; what's the strongest evidence?"
files = size(B["LONG"]["graph_dir"] / "Research Mind.json") + size(B["LONG"]["vault_root"] / "Research Mind/Trends/AI Infrastructure.md")
tools = tool_bytes(state.get_theme("LONG", "AI Infrastructure"))
rows.append(("Hub support + top evidence (synthesis / analyst pre-read)", "graph/Research Mind.json + hub .md", files, "get_theme", tools))
# 3. eval note: "what did the 2026-08-07 run close, and how did it score?"
files = size(B["LONG"]["ledger"]) + size(B["LONG"]["vault_root"] / "Main Mind/Synthesis/Outcome_Scorecard.md")
tools = tool_bytes(state.score_run("LONG", "2026-08-07")) + tool_bytes(state.hit_rate("LONG", strategy_version="LONG-v1.0"))
rows.append(("Run outcome + cohort hit rate (eval-note assembly)", "Portfolio_Ledger.json + Outcome_Scorecard.md", files, "score_run + hit_rate", tools))
# 4. triage: "what canonical hub does 'Micron' map to?"
files = sum(size(p) for _, _, p in state._hub_files("LONG"))
tools = tool_bytes(state.resolve_entity("LONG", "Micron"))
rows.append(("Entity resolution for wiring (triage Step 3)", "every Trends/*.md + Tickers/*.md (alias scan)", files, "resolve_entity", tools))
# 5. ST morning: "is the broker in sync with the ledger?" — file side = ledger only (broker call is identical either way)
files = size(B["ST"]["ledger"])
tools = tool_bytes({"in_sync": True, "only_in_ledger": [], "only_at_broker": [], "qty_or_side_mismatch": [], "broker_equity": 0, "ledger_equity": 0})
rows.append(("Broker/ledger tie-out shape (track-outcomes-st Mode 0; broker call excluded on both sides)", "ST Portfolio_Ledger.json", files, "reconcile_diff (diff only)", tools))

print(f"{'question':70s} {'file bytes':>11s} {'tool bytes':>11s} {'ratio':>7s} {'~tokens saved (bytes/4)':>24s}")
tf = tt = 0
for q, fdesc, f, tdesc, t in rows:
    tf += f; tt += t
    print(f"{q[:70]:70s} {f:11,d} {t:11,d} {f / max(t, 1):6.1f}x {(f - t) // 4:24,d}")
    print(f"    files: {fdesc}\n    tool : {tdesc}")
print(f"\nTOTAL over these five reads: files {tf:,d} bytes vs tools {tt:,d} bytes -> {tf / max(tt, 1):.1f}x, ~{(tf - tt) // 4:,d} tokens (bytes/4 proxy)")
print("Caveat: static byte proxy. Stages that must read hub PROSE (triage evidence_quote, analysts) gain nothing from typed reads; "
      "the wins are confined to structured-state questions like the five above.")
