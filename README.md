# quant-state

A read-only [MCP](https://modelcontextprotocol.io) server that lets an AI assistant ask structured questions about a personal AI research and paper-trading system: its knowledge graph, three simulated portfolios, a forecast ledger, a source registry and paper-broker positions. **17 typed tools, 4 resources, no writes, no orders.**

Built with Claude Code. This repository is the public, read-only interface to a larger private system that runs daily: AI agents read a curated set of market research, maintain an evidence graph of investment themes, turn it into trade ideas, track them in paper portfolios, and grade every outcome against the sources behind it. **Plain-English overview of the full system: [AI-Assisted Research Desk](https://claude.ai/artifact/PFXkK5nqYGNHHPKkhNyar1).**

## Try it in a minute

The repo ships with an invented sample dataset, so everything runs without access to the private system.

```bash
git clone https://github.com/ProfX777/quant-state-mcp.git && cd quant-state-mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python test_state.py      # 48 checks on the sample data, no network
.venv/bin/python smoke_client.py    # starts the server over MCP and calls every tool
```

Add it to Claude Code and ask questions in plain English ("which themes are losing support?", "is the rotation book in sync with the broker?"):

```bash
claude mcp add quant-state -- "$PWD/.venv/bin/python" "$PWD/server.py"
```

## Pointing it at real data

Where the data lives is a config file, not code. With no setting the server uses `sample_data/config.json`. To use your own data, copy that file, edit the paths, and set one environment variable:

```bash
claude mcp add quant-state -e QUANT_STATE_CONFIG=/path/to/my-config.json -- "$PWD/.venv/bin/python" "$PWD/server.py"
```

Every response that describes the system carries a `data_source` label (`SAMPLE` or whatever your config calls itself), and the server states it at startup, so sample numbers can't be mistaken for live ones. `*.local.json` is git-ignored for configs kept inside the folder.

## Tools

All tools take `book` = `LONG` (weekly, 2-8 week theses), `ST` (daily, 2 days to 2 weeks) or `ROTATION` (weekly systematic theme rotation), unless noted. Every tool is marked read-only.

| Tool | Answers |
|---|---|
| `list_books()` | Which data is loaded, and what each book has |
| `graph_meta(book)` | Graph snapshot date, counts, stale hubs, contradiction flags per research domain |
| `resolve_entity(book, mention)` | `"Micron"` / `"$MU"` / `"AI infra"` → the canonical theme or company page, via aliases |
| `get_theme(book, name)` | Direction, strength, staleness, pagerank, velocity, narrative stage, track record, strongest evidence |
| `get_ticker_context(book, ticker)` | `get_theme` plus the book's position in that ticker |
| `fading_theses(book)` | Themes losing support (stale, decelerating, negative velocity), worst first |
| `ledger_summary(book)` | Cash, equity, exposure, P&L, open/closed counts |
| `get_positions(book)` | Open positions with stops and review dates |
| `get_pick_outcomes(book, ticker?, since?)` | Closed positions and their verdicts |
| `hit_rate(book, strategy_version?, since?)` | Win rate by rule-version cohort |
| `score_run(book, date)` | What one run closed and still holds |
| `list_runs(book)` | Recent run dates (notes readable as resources) |
| `forecast_rows(...)` | Forward returns for every candidate idea, picked or not |
| `resolve_source(handle)` | Handle → registered source, or `unattributed` (never guessed) |
| `ingest_status()` | Last ingestion run and library sizes |
| `broker_snapshot(book)` | Paper-broker positions, equity, cash |
| `reconcile_diff(book)` | Ledger vs broker: what differs |

Resources: `quant://books`, `quant://ledger/{book}`, `quant://run/{book}/{date}`, `quant://ingest`.

## Safety by construction

- **Cannot trade.** `broker_snapshot` runs only an adapter's `account` or `reconcile` subcommand. `submit`, `rebalance` and any live flag are refused before a process starts, and the tests check it.
- **Cannot write.** No tool modifies a ledger, note or file. `reconcile_diff` reports differences; acting on them is left to whatever owns the ledger.
- **No credentials.** Broker adapters read their own credentials. The server never sees them.
- **Labelled data.** Sample and live data can't be confused (see above).

## Measured context savings

`measure_context.py` compares the bytes an agent reads to answer a structured question by opening the underlying files, versus calling the tool. On the live system (2026-10-07):

| Question | Read the files | Call the tool | Ratio |
|---|---|---|---|
| Open exposure and headline numbers | 162 KB | 4.2 KB | 39× |
| Support and evidence for one theme | 1,561 KB | 2.4 KB | 660× |
| What a run closed, and the cohort hit rate | 162 KB | 0.7 KB | 217× |
| Canonical page for a mention | 990 KB | 0.25 KB | 4,006× |
| Ledger vs broker tie-out | 808 KB | 0.13 KB | 6,264× |

This is a byte proxy for a naive full-file read, not a per-run token measurement. Stages that must read note prose (for example, to quote evidence word for word) gain nothing from typed reads; the gain is confined to structured questions like these. On the small sample dataset the same script shows smaller ratios.

## Tests

- `test_state.py`: 48 checks on the sample data, including the config switch, alias resolution, cohort hit rates, and the broker path end to end through `sample_data/fake_broker.py`.
- `smoke_client.py`: starts the server with the official MCP client and calls all 17 tools and two resources.
- Both take under a minute and need no network or credentials.

## Layout

```
state.py            read-only functions over the data (no MCP dependency; what the tests exercise)
server.py           MCP server wrapper, stdio transport
sample_data/        invented dataset, config template, fake broker adapter, generator script
test_state.py       unit-level checks
smoke_client.py     end-to-end MCP protocol test
measure_context.py  the byte comparison above
```

## Versions

- **0.2.0**: data location moved to a config file; bundled sample dataset; SAMPLE/LIVE labelling; tests run anywhere; fixed broker text-table parsing when prices are padded.
- **0.1.0**: first release; ran only against the author's machine.
