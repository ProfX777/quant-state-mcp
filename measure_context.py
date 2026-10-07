#!/usr/bin/env python3
"""Static context measurement: how many bytes an agent must read to answer a structured question by
opening the underlying files, versus calling the typed tool. Tokens are approximated as bytes / 4.
This is a reproducible proxy for a naive full-file read, not a live per-run token measurement.

    python measure_context.py                                    # bundled sample (small files)
    QUANT_STATE_CONFIG=~/my-config.json python measure_context.py # a real deployment
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state  # noqa: E402


def size(path) -> int:
    return path.stat().st_size if path and Path(path).exists() else 0


def tool_bytes(obj) -> int:
    return len(json.dumps(obj, default=str))


def first_trend(book):
    for _domain, kind, p in state._hub_files(book):
        if kind == "trend":
            return p.stem
    return None


B = state.CONFIG["books"]
theme = first_trend("LONG")
long_graph = B["LONG"]["domains"][0]["graph"]
rows = [
    ("Open exposure + headline", size(B["LONG"]["ledger"]),
     tool_bytes(state.get_positions("LONG")) + tool_bytes(state.ledger_summary("LONG"))),
    (f"Support + evidence for one theme ({theme})", size(long_graph) + size(state.hub_path("LONG", theme)),
     tool_bytes(state.get_theme("LONG", theme))),
    ("Run outcome + cohort hit rate", size(B["LONG"]["ledger"]),
     tool_bytes(state.hit_rate("LONG")) + tool_bytes(state.score_run("LONG", (state.list_runs("LONG")["latest"] or [""])[0]))),
    ("Canonical hub for a mention", sum(size(p) for _d, _k, p in state._hub_files("LONG")),
     tool_bytes(state.resolve_entity("LONG", "Micron"))),
    ("Ledger vs broker tie-out (diff shape; broker call excluded)", size(B["ST"]["ledger"]),
     tool_bytes({"in_sync": True, "only_in_ledger": [], "only_at_broker": [], "qty_or_side_mismatch": [],
                 "broker_equity": 0, "ledger_equity": 0})),
]

print(f"data source: {state.CONFIG['label']}\n")
print(f"{'question':58s} {'file bytes':>11s} {'tool bytes':>11s} {'ratio':>8s}")
tf = tt = 0
for q, f, t in rows:
    tf += f
    tt += t
    print(f"{q[:58]:58s} {f:11,d} {t:11,d} {f / max(t, 1):7.1f}x")
print(f"\nTOTAL: files {tf:,d} bytes vs tools {tt:,d} bytes -> {tf / max(tt, 1):.1f}x "
      f"(~{max(tf - tt, 0) // 4:,d} tokens at bytes/4)")
print("Stages that must read note prose (to quote evidence verbatim) gain nothing from typed reads; "
      "the gain is confined to structured-state questions like these.")
