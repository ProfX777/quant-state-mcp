#!/usr/bin/env python3
"""quant-state — a READ-ONLY MCP server over the three-book quant research system.

Exposes the knowledge graph, the three paper ledgers, the forecast ledger, the source registry,
the ingest marker, and a read-only broker snapshot as typed tools + resources, so any Claude
surface (Claude Code sub-agents, Claude Desktop, a future deployment) can ask compact questions
instead of reading whole files.

What it deliberately does NOT do: write to any vault or ledger, place or cancel an order, run a
pipeline stage, or ingest anything. The orchestrator keeps every write and every order behind its
existing marker-file / reconcile-first contracts. `broker_snapshot` can only run the adapters'
`account` / `reconcile` subcommands — `submit` and `rebalance` are refused inside state.py.

Run (stdio):  .venv/bin/python server.py
Register:     claude mcp add -s user quant-state -- <abs>/.venv/bin/python <abs>/server.py
"""
from __future__ import annotations

import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

import state

RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
RO_BROKER = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True)

server = MCPServer(
    name="quant-state",
    version="0.1.0",
    instructions=(
        "Read-only state of a three-book quant research system (books: LONG = weekly 2-8wk theses, "
        "ST = daily 48h-2wk trades, ROTATION = weekly systematic sleeve). Start with list_books, then "
        "resolve_entity before get_theme (wikilinks must be canonical hub names). Nothing here writes "
        "or trades; reconcile_diff returns a diff for the orchestrator to act on."
    ),
)


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=None, default=str)


# ----------------------------------------------------------------------------- discovery
@server.tool(annotations=RO, description="The three books (LONG / ST / ROTATION): horizon, ledger path, which graph snapshots exist.")
def list_books() -> dict:
    return state.books()


@server.tool(annotations=RO, description="Per-vault graph snapshot metadata for a book: as-of date, node/edge/hub counts, stale hubs, components, contradiction flags.")
def graph_meta(book: str) -> dict:
    return state.graph_meta(book)


# ----------------------------------------------------------------------------- knowledge graph
@server.tool(annotations=RO, description="Resolve a mention ('Micron', '$MU', 'AI infra') to the CANONICAL hub filename via each hub's aliases. A non-canonical wikilink silently drops its graph edge, so call this before wiring or before get_theme. A miss means: do not wire; flag as a new-hub candidate.")
def resolve_entity(book: str, mention: str) -> dict:
    return state.resolve_entity(book, mention)


@server.tool(annotations=RO, description="One hub (trend or ticker) as the graph sees it: direction/strength/last_assessed, staleness, pagerank, velocity, narrative stage, realized track record, and the top evidence edges (source note, weight, age, stance, short quote).")
def get_theme(book: str, name: str, evidence_limit: int = 8) -> dict:
    return state.get_theme(book, name, evidence_limit=evidence_limit)


@server.tool(annotations=RO, description="get_theme for a ticker PLUS the book's ledger exposure to it (open position with stop/review date, or the most recent close).")
def get_ticker_context(book: str, ticker: str) -> dict:
    return state.get_ticker_context(book, ticker)


@server.tool(annotations=RO, description="Hubs whose thesis support is decaying — stale assessment, decelerating direction, negative velocity, low/unknown strength — worst-first. What a synthesis should not lean on.")
def fading_theses(book: str, limit: int = 15) -> dict:
    return state.fading_theses(book, limit=limit)


# ----------------------------------------------------------------------------- ledgers / outcomes
@server.tool(annotations=RO, description="Ledger headline for a book: cash, equity, gross exposure, realized/unrealized P&L, return, open/closed counts, last equity mark.")
def ledger_summary(book: str) -> dict:
    return state.ledger_summary(book)


@server.tool(annotations=RO, description="Open positions for a book (compact: ticker, direction, shares, basis, stop, review date, horizon, unrealized; rotation adds rank/weights).")
def get_positions(book: str) -> dict:
    return state.get_positions(book)


@server.tool(annotations=RO, description="Closed positions (realized outcomes) for a book, optionally filtered by ticker and/or a since-date (YYYY-MM-DD).")
def get_pick_outcomes(book: str, ticker: str | None = None, since: str | None = None, limit: int = 50) -> dict:
    return state.get_pick_outcomes(book, ticker=ticker, since=since, limit=limit)


@server.tool(annotations=RO, description="Realized hit rate over a book's closes (wins / graded; flat counts in the denominator). Pass strategy_version (e.g. 'LONG-v1.0', 'ST-v1.1') to respect the version-cohort rule; since=YYYY-MM-DD to window it.")
def hit_rate(book: str, strategy_version: str | None = None, since: str | None = None) -> dict:
    return state.hit_rate(book, strategy_version=strategy_version, since=since)


@server.tool(annotations=RO, description="Everything the ledger knows about one synthesis run (date YYYY-MM-DD): closes that originated from it with outcomes, positions it still holds, realized P&L, and whether its run note exists.")
def score_run(book: str, date: str) -> dict:
    return state.score_run(book, date)


@server.tool(annotations=RO, description="List the most recent pipeline run dates for a book (each has an eval note readable via the quant://run/{book}/{date} resource).")
def list_runs(book: str, limit: int = 12) -> dict:
    return state.list_runs(book, limit=limit)


@server.tool(annotations=RO, description="Candidate-level forward-return rows from the forecast ledger (every analyst candidate, picked or not). Filter by book, analyst (tech|macro), ticker, or cited author slug. Directional-only instrumentation — never a trade signal.")
def forecast_rows(book: str | None = None, analyst: str | None = None, ticker: str | None = None, author: str | None = None, limit: int = 100) -> dict:
    return state.forecast_rows(book=book, analyst=analyst, ticker=ticker, author=author, limit=limit)


# ----------------------------------------------------------------------------- registry / ingest
@server.tool(annotations=RO, description="Resolve an X handle / display name / citation name against sources.yaml (the closed source registry). A miss returns attributed_to: unattributed — never guess a slug.")
def resolve_source(handle: str) -> dict:
    return state.resolve_source(handle)


@server.tool(annotations=RO, description="The pre-dawn ingestion marker: per-routine adds/failures, notebook source counts vs the 300 cap, measurement status.")
def ingest_status() -> dict:
    return state.ingest_status()


# ----------------------------------------------------------------------------- broker (read-only)
@server.tool(annotations=RO_BROKER, description="Read-only paper-broker snapshot for a book via the existing Alpaca adapter's `account` (or `reconcile`) subcommand: positions, equity, cash, self-check. This server cannot place, modify, or cancel orders.")
def broker_snapshot(book: str, subcommand: str = "account") -> dict:
    return state.broker_snapshot(book, subcommand=subcommand)


@server.tool(annotations=RO_BROKER, description="Ledger open positions vs broker positions — the DIFF only (tickers only in one place, qty/side mismatches, equity on each side). Booking any fill it reveals stays in the orchestrator (reconcile-first rule).")
def reconcile_diff(book: str) -> dict:
    return state.reconcile_diff(book)


# ----------------------------------------------------------------------------- resources (big read-only blobs)
@server.resource("quant://books", name="books", description="The three books and where their state lives.", mime_type="application/json")
def r_books() -> str:
    return _j(state.books())


@server.resource("quant://ledger/{book}", name="ledger", description="Full Portfolio_Ledger.json for a book (LONG | ST | ROTATION).", mime_type="application/json")
def r_ledger(book: str) -> str:
    return _j(state._ledger(book))


@server.resource("quant://run/{book}/{date}", name="run_note", description="The per-run eval note (markdown) for a book and date (YYYY-MM-DD).", mime_type="text/markdown")
def r_run(book: str, date: str) -> str:
    return state.run_note(book, date)


@server.resource("quant://ingest", name="ingest_status", description="ingest_status.json — the predawn ingestion marker.", mime_type="application/json")
def r_ingest() -> str:
    return _j(state.ingest_status())


if __name__ == "__main__":
    server.run(transport="stdio")
