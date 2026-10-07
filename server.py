#!/usr/bin/env python3
"""quant-state: a READ-ONLY MCP server over a three-book AI research and paper-trading system.

Exposes the knowledge graph, the three ledgers, the forecast ledger, the source registry, the ingest
marker and a read-only broker snapshot as typed tools and resources, so any MCP client (Claude Code,
Claude Desktop, other agents) can ask compact questions instead of reading whole files.

It never writes, never trades and never runs a pipeline stage. `broker_snapshot` can only run an
adapter's `account` / `reconcile` subcommands; `submit` and `rebalance` are refused in state.py.

    python server.py                                     # stdio, bundled SAMPLE data
    QUANT_STATE_CONFIG=~/my-config.json python server.py # stdio, your own data
"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

import state

RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
RO_BROKER = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True)

server = MCPServer(
    name="quant-state",
    version="0.2.0",
    instructions=(
        f"DATA SOURCE: {state.CONFIG['label']}. "
        "Read-only state of a three-book research system (LONG = weekly 2-8 week theses, ST = daily "
        "2 day to 2 week trades, ROTATION = weekly systematic theme rotation). Start with list_books, "
        "then resolve_entity before get_theme, because hub names must be canonical. Nothing here writes "
        "or trades; reconcile_diff returns a diff for whoever owns the ledger to act on."
    ),
)


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ----------------------------------------------------------------------------- discovery
@server.tool(annotations=RO, description="Which data this server is reading (SAMPLE or LIVE) and the three books: horizon, research domains, which graph snapshots and run notes exist, whether a broker is configured.")
def list_books() -> dict:
    return state.books()


@server.tool(annotations=RO, description="Per-domain graph snapshot metadata for a book: as-of date, node/edge/hub counts, stale hubs, components, contradiction flags.")
def graph_meta(book: str) -> dict:
    return state.graph_meta(book)


# ----------------------------------------------------------------------------- knowledge graph
@server.tool(annotations=RO, description="Resolve a mention ('Micron', '$MU', 'AI infra') to the canonical hub name via each hub's aliases. Call before get_theme or before linking a note. A miss means: do not link it; flag it as a new-hub candidate.")
def resolve_entity(book: str, mention: str) -> dict:
    return state.resolve_entity(book, mention)


@server.tool(annotations=RO, description="One hub (theme or company): direction, strength, last assessed, staleness, pagerank, velocity, narrative stage, realized track record, and the strongest evidence edges (source, weight, age, stance, short quote).")
def get_theme(book: str, name: str, evidence_limit: int = 8) -> dict:
    return state.get_theme(book, name, evidence_limit=evidence_limit)


@server.tool(annotations=RO, description="get_theme for a ticker plus the book's ledger exposure to it: the open position with stop and review date, or the most recent close.")
def get_ticker_context(book: str, ticker: str) -> dict:
    return state.get_ticker_context(book, ticker)


@server.tool(annotations=RO, description="Hubs whose support is decaying (stale, decelerating, negative velocity, weak strength), worst first. What an idea should not lean on.")
def fading_theses(book: str, limit: int = 15) -> dict:
    return state.fading_theses(book, limit=limit)


# ----------------------------------------------------------------------------- ledgers / outcomes
@server.tool(annotations=RO, description="Ledger headline for a book: cash, equity, gross exposure, realized and unrealized P&L, return, open and closed counts, last equity mark.")
def ledger_summary(book: str) -> dict:
    return state.ledger_summary(book)


@server.tool(annotations=RO, description="Open positions for a book: ticker, direction, shares, basis, stop, review date, horizon, unrealized P&L (the rotation book adds rank and weights).")
def get_positions(book: str) -> dict:
    return state.get_positions(book)


@server.tool(annotations=RO, description="Closed positions with their verdicts, optionally filtered by ticker and/or a since-date (YYYY-MM-DD).")
def get_pick_outcomes(book: str, ticker: str | None = None, since: str | None = None, limit: int = 50) -> dict:
    return state.get_pick_outcomes(book, ticker=ticker, since=since, limit=limit)


@server.tool(annotations=RO, description="Realized hit rate (wins / graded closes; flat counts in the denominator). Pass strategy_version (e.g. 'LONG-v1.0') to keep rule-version cohorts apart; since=YYYY-MM-DD to window it.")
def hit_rate(book: str, strategy_version: str | None = None, since: str | None = None) -> dict:
    return state.hit_rate(book, strategy_version=strategy_version, since=since)


@server.tool(annotations=RO, description="Everything the ledger knows about one run (YYYY-MM-DD): positions it closed with outcomes, positions it still holds, realized P&L, and whether its run note exists.")
def score_run(book: str, date: str) -> dict:
    return state.score_run(book, date)


@server.tool(annotations=RO, description="The most recent run dates for a book. Each has a note readable as the quant://run/{book}/{date} resource.")
def list_runs(book: str, limit: int = 12) -> dict:
    return state.list_runs(book, limit=limit)


@server.tool(annotations=RO, description="Candidate-level forward-return rows (every analyst candidate, picked or not). Filter by book, analyst (tech|macro), ticker or cited source. Directional instrumentation only, never a trade signal.")
def forecast_rows(book: str | None = None, analyst: str | None = None, ticker: str | None = None, author: str | None = None, limit: int = 100) -> dict:
    return state.forecast_rows(book=book, analyst=analyst, ticker=ticker, author=author, limit=limit)


# ----------------------------------------------------------------------------- registry / ingest
@server.tool(annotations=RO, description="Resolve a handle or name against the source registry. A miss returns attributed_to: unattributed; a slug is never guessed.")
def resolve_source(handle: str) -> dict:
    return state.resolve_source(handle)


@server.tool(annotations=RO, description="The ingestion marker: per-routine adds and failures, research-library sizes, last run time.")
def ingest_status() -> dict:
    return state.ingest_status()


# ----------------------------------------------------------------------------- broker (read-only)
@server.tool(annotations=RO_BROKER, description="Read-only paper-broker snapshot for a book via its adapter's `account` (or `reconcile`) subcommand: positions, equity, cash. This server cannot place, modify or cancel orders.")
def broker_snapshot(book: str, subcommand: str = "account") -> dict:
    return state.broker_snapshot(book, subcommand=subcommand)


@server.tool(annotations=RO_BROKER, description="Ledger open positions vs broker positions, as a diff only: tickers in one place but not the other, quantity or side mismatches, equity on each side.")
def reconcile_diff(book: str) -> dict:
    return state.reconcile_diff(book)


# ----------------------------------------------------------------------------- resources
@server.resource("quant://books", name="books", description="Data source and the three books.", mime_type="application/json")
def r_books() -> str:
    return _j(state.books())


@server.resource("quant://ledger/{book}", name="ledger", description="Full ledger JSON for a book (LONG | ST | ROTATION).", mime_type="application/json")
def r_ledger(book: str) -> str:
    return _j(state._ledger(book))


@server.resource("quant://run/{book}/{date}", name="run_note", description="The run note (markdown) for a book and date (YYYY-MM-DD).", mime_type="text/markdown")
def r_run(book: str, date: str) -> str:
    return state.run_note(book, date)


@server.resource("quant://ingest", name="ingest_status", description="The ingestion marker.", mime_type="application/json")
def r_ingest() -> str:
    return _j(state.ingest_status())


if __name__ == "__main__":
    server.run(transport="stdio")
