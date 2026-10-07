# quant-state — a read-only MCP server over a three-book quant research system

`quant-state` exposes the *state* of an agent-driven investment-research pipeline — its knowledge
graph, three paper ledgers, forecast ledger, source registry, ingestion marker, and a read-only
broker snapshot — as typed [MCP](https://modelcontextprotocol.io) tools and resources. Any Claude
surface (Claude Code sub-agents, Claude Desktop, a future hosted deployment) can then ask compact,
structured questions instead of reading whole files.

It is deliberately **read-only**. It never writes a vault or ledger, never places or cancels an
order, never runs a pipeline stage. The orchestrator keeps every write and every order behind its
existing marker-file and reconcile-first contracts; this server returns *diffs and facts* for it
to act on.

## The system it sits on

Three books, each with its own Obsidian vault(s), ledger, and graph snapshot:

| Book | Horizon | Ledger | Graph |
|---|---|---|---|
| `LONG` | weekly, 2–8-week theses | `Main Mind/Synthesis/Portfolio_Ledger.json` (sim) | `pipeline-tooling/graph/{Research,Macro} Mind.json` |
| `ST` | daily, 48 h–2 wk trades (live paper on Alpaca) | `…ST/Main Mind/Synthesis/Portfolio_Ledger.json` | `pipeline-tooling-st/graph/…` |
| `ROTATION` | weekly systematic trend-rotation sleeve (paper) | `Main Mind/Rotation/Portfolio_Ledger.json` | shares LONG's graph |

```
                 ┌──────────────── research ingestion (X bookmarks + Grok, YouTube, Substack, Dropbox) ────────────────┐
                 │   NotebookLM notebooks  ──►  daily/weekly query anchors  ──►  triage wires evidence into hubs   │
                 └────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                                              ▼
        Obsidian vaults (hub .md frontmatter: aliases, direction, strength, realized_outcomes)
        build_graph.py ──► graph/<Vault>.json (pagerank, velocity, staleness, evidence edges, narrative stages)
        Portfolio_Ledger.json × 3 · forecast_ledger.csv · sources.yaml · ingest_status.json · Pipeline Runs/*.md
                                                              │
                                              ┌───────────────┴───────────────┐
                                              │   quant-state (this server)   │  read side ONLY
                                              │  state.py  ←  server.py/stdio │
                                              └───────────────┬───────────────┘
                                                              ▼
              Claude Code stage agents · Claude Desktop · any MCP client       (writes + orders stay in the
                                                                                orchestrator's own Python)
```

## Tools

All tools take `book` ∈ `LONG | ST | ROTATION` unless noted, and all carry `readOnlyHint=true`.

| Tool | Answers |
|---|---|
| `list_books()` | the three books, where their state lives, which graph snapshots exist |
| `graph_meta(book)` | per-vault snapshot as-of, node/edge/hub counts, stale hubs, components, contradiction flags |
| `resolve_entity(book, mention)` | `"Micron"` / `"$MU"` / `"AI infra"` → the **canonical hub filename** via each hub's `aliases:` (a non-canonical wikilink silently drops its edge; triage does this by hand today) |
| `get_theme(book, name)` | one hub: direction/strength/last_assessed, staleness, pagerank, velocity, narrative stage, realized track record, top evidence edges (source, weight, age, stance, short quote) |
| `get_ticker_context(book, ticker)` | `get_theme` + the book's ledger exposure to that ticker |
| `fading_theses(book)` | hubs whose support is decaying (stale, decelerating, negative velocity, weak strength), worst-first |
| `ledger_summary(book)` | cash, equity, gross, realized/unrealized, return, counts, last equity mark |
| `get_positions(book)` | compact open positions (rotation adds rank / weights) |
| `get_pick_outcomes(book, ticker?, since?)` | realized closes with verdicts |
| `hit_rate(book, strategy_version?, since?)` | wins / graded closes, respecting the version-cohort rule |
| `score_run(book, date)` | what one synthesis run closed, still holds, and realized |
| `list_runs(book)` | recent run dates (eval notes readable as resources) |
| `forecast_rows(book?, analyst?, ticker?, author?)` | candidate-level forward-return rows (directional instrumentation, never a signal) |
| `resolve_source(handle)` | X handle / name → registry slug, or `unattributed` (never guessed) |
| `ingest_status()` | the pre-dawn ingestion marker and notebook cap counts |
| `broker_snapshot(book, subcommand=account)` | paper-broker positions/equity via the existing Alpaca adapter's **read** subcommands only |
| `reconcile_diff(book)` | ledger vs broker — the diff only |

Resources: `quant://books`, `quant://ledger/{book}`, `quant://run/{book}/{date}`, `quant://ingest`.

### What is refused by construction

`broker_snapshot` runs the adapters' `account` / `reconcile` subcommands and nothing else;
`submit`, `rebalance`, `--live`, `--auto`, `--allow-live` are rejected inside `state.py` before any
process is spawned. Credentials are read by the adapters themselves, never by this server.

## Install / run

```bash
cd quant-state-mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # mcp>=2,<3
.venv/bin/python test_state.py      # read-only tests against the live files (broker stubbed)
.venv/bin/python smoke_client.py    # spawns server.py over stdio with the official client
.venv/bin/python server.py          # stdio server
```

Register for every Claude Code session (user scope):

```bash
claude mcp add -s user quant-state -- "$PWD/.venv/bin/python" "$PWD/server.py"
```

## Measured context (static proxy — read the caveat)

`measure_context.py` compares the bytes an agent must ingest to answer a concrete stage question by
reading the underlying file(s) versus calling the typed tool. Numbers from this system on
2026-09-22:

| Question a stage asks | File read | Tool | Ratio |
|---|---|---|---|
| Open exposure + headline (track-outcomes pre-read) | 162 KB | 4.1 KB | 40× |
| Is hub X still supported; strongest evidence? | 1,602 KB | 2.3 KB | 698× |
| What did run Y close; cohort hit rate? | 172 KB | 1.6 KB | 109× |
| Which canonical hub does "Micron" map to? | 990 KB (alias scan of every hub) | 0.2 KB | 4,039× |
| Is the ST ledger tied out to the broker? | 839 KB | 0.1 KB (diff) | 6,504× |

**Caveat, stated plainly:** this is a byte proxy for a *naïve full-file read*, not a live per-run
token measurement. Real stages partially read files, and the stages that dominate this pipeline's
cost — triage and the analysts — must read hub *prose* to lift verbatim evidence quotes, and gain
nothing from typed reads. The wins are confined to structured-state questions like the five above.
The honest line is therefore:

> Built a read-only MCP server exposing a three-book research system's knowledge graph, paper
> ledgers, forecast ledger, and broker state as 17 typed tools; the structured-state reads a
> stage makes (exposure, hub support, run scoring, entity resolution, broker tie-out) shrink from
> 160 KB–1.6 MB of file reads to 0.1–4 KB of tool responses.

To turn that into a per-run number, instrument one stage (track-outcomes is the natural first) and
record its input tokens with and without the server.

## Non-goals

- Orchestration. MCP is a tool interface; the pipeline's stage sequencing, marker contracts, and
  Workflow dispatch stay where they are.
- Ingestion. The Selenium/cookie/Dropbox paths are long-running and brittle; only `ingest_status`
  is exposed.
- NotebookLM. Two NotebookLM MCP servers already exist in this environment; nothing is duplicated.
- Any write, any order.

## Layout

```
state.py            pure read functions (no MCP import) — the thing to test
server.py           MCPServer wrapper, stdio transport
test_state.py       36 read-only checks against the live files
smoke_client.py     end-to-end stdio smoke test through mcp.client
measure_context.py  the static byte comparison above
```
