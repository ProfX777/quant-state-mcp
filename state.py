"""quant-state — READ-ONLY accessors over the three-book quant research system.

Pure functions, no MCP dependency, no network except the explicitly-named broker snapshot (which
shells out to the existing Alpaca adapters' READ subcommands only). Every function takes a
`book` in {LONG, ST, ROTATION} because the three books keep separate vaults, ledgers, and graphs.

Sources of truth this module reads (never writes):
  * knowledge graph   — build_graph.py's JSON per vault (<tooling>/graph/<Vault>.json): hub rows
                        (pagerank, velocity, staleness, direction/strength), per-hub evidence
                        edges, narrative stages, contradiction flags
  * hub frontmatter   — Trends/*.md and Tickers/*.md (aliases, direction, strength,
                        last_assessed, realized_outcomes track record)
  * ledgers           — Main Mind/Synthesis/Portfolio_Ledger.json (LONG, ST) and
                        Main Mind/Rotation/Portfolio_Ledger.json (ROTATION)
  * forecast ledger   — <tooling-long>/forecast_ledger.csv (candidate-level forward returns)
  * run notes         — Main Mind/Pipeline Runs/<date>.md (per-run eval)
  * source registry   — <tooling-long>/sources.yaml
  * ingest marker     — <tooling-st>/ingest_status.json
  * broker            — alpaca_exec*.py `account` / `reconcile` (paper accounts; read-only
                        subcommands ONLY — `submit` / `rebalance` are refused by construction)
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
ICLOUD = HOME / "Library/Mobile Documents/com~apple~CloudDocs"
TOOLING = HOME / ".claude/pipeline-tooling"
TOOLING_ST = HOME / ".claude/pipeline-tooling-st"
TOOLING_ROT = HOME / ".claude/pipeline-tooling-rotation"

BOOKS = {
    "LONG": {
        "vault_root": ICLOUD / "Obsidian Vaults",
        "graph_dir": TOOLING / "graph",
        "ledger": ICLOUD / "Obsidian Vaults/Main Mind/Synthesis/Portfolio_Ledger.json",
        "runs": ICLOUD / "Obsidian Vaults/Main Mind/Pipeline Runs",
        "alpaca": [sys.executable, str(TOOLING / "alpaca_exec_long.py")],
        "alpaca_json": False,
        "horizon": "weekly (Fri), 2-8 week theses",
    },
    "ST": {
        "vault_root": ICLOUD / "Obsidian Vaults ST",
        "graph_dir": TOOLING_ST / "graph",
        "ledger": ICLOUD / "Obsidian Vaults ST/Main Mind/Synthesis/Portfolio_Ledger.json",
        "runs": ICLOUD / "Obsidian Vaults ST/Main Mind/Pipeline Runs",
        "alpaca": [sys.executable, str(TOOLING_ST / "alpaca_exec.py")],
        "alpaca_json": True,
        "horizon": "daily, 48h-2wk trades",
    },
    "ROTATION": {
        "vault_root": ICLOUD / "Obsidian Vaults",          # rotation ranks off the LONG graph
        "graph_dir": TOOLING / "graph",
        "ledger": ICLOUD / "Obsidian Vaults/Main Mind/Rotation/Portfolio_Ledger.json",
        "runs": ICLOUD / "Obsidian Vaults/Main Mind/Pipeline Runs",   # shares the LONG run notes
        "alpaca": [sys.executable, str(TOOLING_ROT / "alpaca_exec_rotation.py")],
        "alpaca_json": False,
        "horizon": "weekly systematic trend-rotation sleeve",
    },
}
VAULTS = ("Research Mind", "Macro Mind")           # tech graph, macro graph (both books)
HUB_FOLDERS = ("Trends", "Tickers")
READ_ONLY_ALPACA = {"account", "reconcile"}         # the ONLY subcommands this module will ever run
SOURCES_YAML = TOOLING / "sources.yaml"
FORECAST_CSV = TOOLING / "forecast_ledger.csv"
INGEST_STATUS = TOOLING_ST / "ingest_status.json"


class BookError(ValueError):
    pass


def _book(book: str) -> dict:
    b = (book or "").upper()
    if b not in BOOKS:
        raise BookError(f"unknown book {book!r}; expected one of {sorted(BOOKS)}")
    return BOOKS[b]


# ----------------------------------------------------------------------------- frontmatter
def _fm(path: Path) -> dict:
    """Minimal YAML-ish frontmatter reader for hub files: scalars, flat lists, and the
    realized_outcomes list-of-dicts. Deliberately dependency-free."""
    raw = path.read_text(errors="ignore")
    if not raw.startswith("---\n"):
        return {}
    end = raw.find("\n---\n", 4)
    out, key, cur_list, cur_dict = {}, None, None, None
    for ln in raw[4:end].split("\n"):
        if ln.startswith("- ") or ln.startswith("  - "):
            item = ln.split("- ", 1)[1].strip()
            if key == "realized_outcomes":
                cur_dict = {}
                k, _, v = item.partition(":")
                cur_dict[k.strip()] = v.strip().strip("'\"")
                cur_list.append(cur_dict)
            elif cur_list is not None:
                cur_list.append(item.strip("'\""))
            continue
        if ln.startswith("  ") and cur_dict is not None and ":" in ln:
            k, _, v = ln.strip().partition(":")
            cur_dict[k.strip()] = v.strip().strip("'\"")
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        cur_dict = None
        if val == "" or val == "[]":
            cur_list = [] if val == "" else []
            out[key] = cur_list
        else:
            cur_list = None
            out[key] = val.strip("'\"")
    return out


def _hub_files(book: str):
    b = _book(book)
    for vault in VAULTS:
        for folder in HUB_FOLDERS:
            d = b["vault_root"] / vault / folder
            if d.exists():
                for p in sorted(d.glob("*.md")):
                    yield vault, folder[:-1].lower(), p        # 'trend' | 'ticker'


def resolve_entity(book: str, mention: str) -> dict:
    """Map a mention ('Micron', '$MU', 'AI infra') to the canonical hub filename via each hub's
    `aliases:` — the same map build_graph.py canonicalises with. A non-canonical wikilink silently
    drops its edge, so this is the lookup triage does by hand."""
    q = (mention or "").strip().lstrip("[").rstrip("]").strip()
    ql = q.lower().lstrip("$")
    exact, alias_hits = None, []
    for vault, kind, p in _hub_files(book):
        stem = p.stem
        if stem.lower() == ql or stem.lower().split(" — ")[0] == ql:
            exact = {"canonical": stem, "vault": vault, "kind": kind, "match": "filename"}
            break
        fm = _fm(p)
        for a in fm.get("aliases", []) or []:
            if str(a).lower().lstrip("$") == ql:
                alias_hits.append({"canonical": stem, "vault": vault, "kind": kind, "match": f"alias:{a}"})
    if exact:
        return {"query": q, "resolved": True, **exact}
    if alias_hits:
        return {"query": q, "resolved": True, **alias_hits[0], "other_matches": alias_hits[1:]}
    return {"query": q, "resolved": False, "note": "no hub or alias matches — do NOT wire; flag as a new-hub candidate"}


# ----------------------------------------------------------------------------- graph
def _graph(book: str, vault: str) -> dict:
    p = _book(book)["graph_dir"] / f"{vault}.json"
    if not p.exists():
        raise FileNotFoundError(f"no graph snapshot for {book}/{vault} at {p}")
    return json.loads(p.read_text())


def graph_meta(book: str) -> dict:
    out = {}
    for vault in VAULTS:
        try:
            g = _graph(book, vault)
        except FileNotFoundError as e:
            out[vault] = {"error": str(e)}; continue
        out[vault] = {"generated": g.get("generated"), "as_of": g.get("today"), "counts": g.get("counts"),
                      "components": (g.get("connectivity") or {}).get("post", {}).get("n_components"),
                      "contradiction_flags": len(g.get("contradictions") or []),
                      "half_life_days": g.get("edge_half_life_days"), "stale_after_days": g.get("stale_assessment_days")}
    return out


def _find_row(book: str, name: str):
    nl = name.lower()
    for vault in VAULTS:
        try:
            g = _graph(book, vault)
        except FileNotFoundError:
            continue
        for r in g.get("rows", []):
            if r.get("type") in ("trend", "ticker") and str(r.get("name", "")).lower() == nl:
                return vault, g, r
    return None, None, None


def get_theme(book: str, name: str, evidence_limit: int = 8) -> dict:
    """A hub (trend or ticker) as the graph and its own frontmatter see it: pagerank, velocity,
    staleness, direction/strength, narrative stage, realized track record, and the top evidence
    edges (source note, weight, age, stance, quote)."""
    res = resolve_entity(book, name)
    canonical = res.get("canonical", name)
    vault, g, row = _find_row(book, canonical)
    if row is None:
        return {"book": book.upper(), "query": name, "found": False, "resolve": res}
    ev = sorted((g.get("hub_evidence") or {}).get(canonical, []), key=lambda e: -(e.get("weight") or 0))
    stage = (g.get("narrative_stages") or {}).get(canonical, {})
    hub_fm = {}
    for v, kind, p in _hub_files(book):
        if p.stem == canonical:
            hub_fm = _fm(p); break
    ro = hub_fm.get("realized_outcomes") or []
    return {
        "book": book.upper(), "vault": vault, "hub": canonical, "type": row.get("type"), "found": True,
        "graph_as_of": g.get("today"),
        "direction": hub_fm.get("direction") or row.get("direction"), "strength": hub_fm.get("strength") or row.get("strength"),
        "last_assessed": hub_fm.get("last_assessed"), "next_review": hub_fm.get("next_review"),
        "stale": row.get("stale"), "age_days": row.get("age_days"),
        "pagerank": row.get("pagerank"), "deep_read_score": row.get("deep_read_score"), "velocity": row.get("velocity"),
        "momentum": row.get("momentum"), "in_degree": row.get("in_degree"), "community": row.get("community"),
        "narrative_stage": stage.get("narrative_stage"), "stage_transition": stage.get("stage_transition"),
        "source_diversity": stage.get("source_diversity_count"),
        "realized": {"n": int(hub_fm.get("realized_n") or 0), "hit_rate": float(hub_fm.get("realized_hit_rate") or 0.0) if hub_fm.get("realized_n") else None,
                     "last": ro[-1] if ro else None},
        "aliases": hub_fm.get("aliases") or [],
        "evidence_count": len(ev),
        "evidence": [{"source": e.get("source_note"), "weight": e.get("weight"), "age_days": e.get("age_days"),
                      "stance": e.get("stance"), "conf": e.get("conf"), "quote": (e.get("quote") or "")[:160]} for e in ev[:evidence_limit]],
    }


def get_ticker_context(book: str, ticker: str) -> dict:
    """get_theme for a ticker hub PLUS the book's live ledger exposure to it (open position, or
    the most recent close)."""
    t = get_theme(book, ticker)
    L = _ledger(book)
    tk = ticker.upper().lstrip("$")
    open_pos = [_slim_pos(o) for o in L.get("open_positions", []) if str(o.get("ticker", "")).upper() == tk]
    closes = [c for c in L.get("closed_positions", []) if str(c.get("ticker", "")).upper() == tk]
    t["ledger"] = {"open": open_pos, "last_close": _slim_close(closes[-1]) if closes else None, "closes_total": len(closes)}
    return t


def fading_theses(book: str, limit: int = 15) -> dict:
    """Hubs whose thesis support is decaying: stale assessment, decelerating direction, or
    negative velocity — sorted worst-first. What a synthesis should NOT lean on."""
    out = []
    for vault in VAULTS:
        try:
            g = _graph(book, vault)
        except FileNotFoundError:
            continue
        stages = g.get("narrative_stages") or {}
        for r in g.get("rows", []):
            if r.get("type") not in ("trend", "ticker"):
                continue
            reasons = []
            if r.get("stale"): reasons.append(f"stale ({r.get('age_days')}d since assessment)")
            if r.get("direction") == "decelerating": reasons.append("direction decelerating")
            if (r.get("velocity") or 0) < 0: reasons.append(f"velocity {r.get('velocity')}")
            if r.get("strength") in ("low", "unknown") and r.get("type") == "trend": reasons.append(f"strength {r.get('strength')}")
            if reasons:
                out.append({"vault": vault, "hub": r["name"], "type": r["type"], "direction": r.get("direction"), "strength": r.get("strength"),
                            "age_days": r.get("age_days"), "velocity": r.get("velocity"), "pagerank": r.get("pagerank"),
                            "narrative_stage": stages.get(r["name"], {}).get("narrative_stage"), "reasons": reasons})
    out.sort(key=lambda x: (-len(x["reasons"]), -(x["age_days"] or 0)))
    return {"book": book.upper(), "count": len(out), "hubs": out[:limit]}


# ----------------------------------------------------------------------------- ledgers
def _ledger(book: str) -> dict:
    p = _book(book)["ledger"]
    return json.loads(p.read_text())


def _slim_pos(o: dict) -> dict:
    keys = ("ticker", "direction", "shares", "cost_basis", "opened_date", "stop", "target", "review_date", "horizon",
            "entry_verdict", "size_factor", "current_price_asof", "unrealized_pnl", "unrealized_pct", "strategy_version",
            "originating_synthesis", "last_reviewed", "rank", "target_weight", "actual_weight", "composite", "days_held")
    return {k: o[k] for k in keys if k in o and o[k] is not None}


def _slim_close(c: dict) -> dict:
    keys = ("ticker", "direction", "opened_date", "closed_date", "cost_basis", "close_price", "exit_price", "shares",
            "realized_pnl", "realized_pct", "rotation_pnl_pct", "verdict", "outcome", "horizon", "strategy_version",
            "originating_synthesis", "close_reason", "price_basis")
    return {k: c[k] for k in keys if k in c and c[k] is not None}


def ledger_summary(book: str) -> dict:
    L = _ledger(book); m = L.get("meta", {})
    eh = L.get("equity_history") or []
    return {"book": book.upper(), "strategy_version": m.get("strategy_version"), "as_of": m.get("as_of") or L.get("as_of"),
            "cash": L.get("cash"), "equity": L.get("equity_asof"), "gross_exposure_pct": L.get("gross_exposure_pct"),
            "realized_pnl_total": L.get("realized_pnl_total"), "unrealized_pnl_total": L.get("unrealized_pnl_total"),
            "total_return_pct": L.get("total_return_pct"), "open_positions": len(L.get("open_positions", [])),
            "closed_positions": len(L.get("closed_positions", [])), "working_orders": len(L.get("working_orders", []) or []),
            "last_equity_mark": {"date": eh[-1].get("date"), "equity": eh[-1].get("equity")} if eh else None,
            "flags_count": len(L.get("flags") or [])}


def get_positions(book: str) -> dict:
    L = _ledger(book)
    return {"book": book.upper(), "as_of": (L.get("meta") or {}).get("as_of") or L.get("as_of"),
            "positions": [_slim_pos(o) for o in L.get("open_positions", [])]}


def get_pick_outcomes(book: str, ticker: str | None = None, since: str | None = None, limit: int = 50) -> dict:
    L = _ledger(book)
    rows = L.get("closed_positions", [])
    if ticker: rows = [c for c in rows if str(c.get("ticker", "")).upper() == ticker.upper()]
    if since: rows = [c for c in rows if str(c.get("closed_date") or c.get("date_closed") or "") >= since]
    rows = sorted(rows, key=lambda c: str(c.get("closed_date") or c.get("date_closed") or ""))[-limit:]
    return {"book": book.upper(), "count": len(rows), "closes": [_slim_close(c) for c in rows]}


def _outcome(c: dict):
    o = c.get("outcome")
    if o: return o
    v = str(c.get("verdict", "")).lower()
    if "winner" in v: return "win"
    if "loser" in v or "stopped" in v or "killed" in v: return "loss"
    if "mixed" in v: return "flat"
    pct = c.get("realized_pct") if c.get("realized_pct") is not None else c.get("rotation_pnl_pct")
    if pct is None: return None
    return "win" if pct > 1.0 else "loss" if pct < -1.0 else "flat"


def hit_rate(book: str, strategy_version: str | None = None, since: str | None = None) -> dict:
    """Realized hit rate over the book's closes (win / total; flat counts in the denominator).
    Filter by strategy_version (e.g. LONG-v1.0) to respect the version-cohort rule."""
    L = _ledger(book)
    rows = L.get("closed_positions", [])
    if strategy_version: rows = [c for c in rows if c.get("strategy_version") == strategy_version]
    if since: rows = [c for c in rows if str(c.get("closed_date") or c.get("date_closed") or "") >= since]
    graded = [(c, _outcome(c)) for c in rows]
    graded = [(c, o) for c, o in graded if o]
    n = len(graded); w = sum(1 for _, o in graded if o == "win"); f = sum(1 for _, o in graded if o == "flat")
    pcts = [c.get("realized_pct") if c.get("realized_pct") is not None else c.get("rotation_pnl_pct") for c, _ in graded]
    pcts = [p for p in pcts if p is not None]
    return {"book": book.upper(), "strategy_version": strategy_version, "since": since, "n": n, "wins": w, "flats": f,
            "losses": n - w - f, "hit_rate": round(w / n, 3) if n else None,
            "avg_return_pct": round(sum(pcts) / len(pcts), 2) if pcts else None,
            "note": "hit_rate = wins / graded closes; flat counts in the denominator (the book's frozen mapping)"}


def score_run(book: str, date: str) -> dict:
    """Everything the book knows about one synthesis run: the closes that originated from it, the
    positions it still holds, and whether a run note exists."""
    L = _ledger(book); tag = f"{date}_Synthesis"
    closes = [c for c in L.get("closed_positions", []) if tag in str(c.get("originating_synthesis", ""))]
    opens = [o for o in L.get("open_positions", []) if tag in str(o.get("originating_synthesis", ""))]
    note = _book(book)["runs"] / f"{date}.md"
    graded = [(_outcome(c), c) for c in closes]
    return {"book": book.upper(), "run": date, "run_note_exists": note.exists(),
            "closed": [_slim_close(c) for c in closes], "still_open": [_slim_pos(o) for o in opens],
            "wins": sum(1 for o, _ in graded if o == "win"), "losses": sum(1 for o, _ in graded if o == "loss"),
            "flats": sum(1 for o, _ in graded if o == "flat"),
            "realized_pnl": round(sum(c.get("realized_pnl") or 0 for c in closes), 2)}


def list_runs(book: str, limit: int = 12) -> dict:
    d = _book(book)["runs"]
    dates = sorted(p.stem for p in d.glob("????-??-??.md")) if d.exists() else []
    return {"book": book.upper(), "runs_dir": str(d), "count": len(dates), "latest": dates[-limit:]}


def run_note(book: str, date: str) -> str:
    p = _book(book)["runs"] / f"{date}.md"
    if not p.exists():
        raise FileNotFoundError(f"no run note for {book}/{date}")
    return p.read_text()


# ----------------------------------------------------------------------------- forecast ledger
def forecast_rows(book: str | None = None, analyst: str | None = None, ticker: str | None = None,
                  author: str | None = None, limit: int = 100) -> dict:
    """Candidate-level forward-return rows from forecast_ledger.py (every analyst candidate, picked
    or not, joined to forward returns). Directional-only instrumentation — never a trade signal."""
    if not FORECAST_CSV.exists():
        return {"error": f"{FORECAST_CSV} missing (run forecast_ledger.py)"}
    rows = []
    with FORECAST_CSV.open() as f:
        for r in csv.DictReader(f):
            if book and r.get("book", "").upper() != book.upper(): continue
            if analyst and r.get("analyst") != analyst: continue
            if ticker and r.get("ticker", "").upper() != ticker.upper(): continue
            if author and author not in (r.get("authors") or ""): continue
            rows.append({k: r.get(k) for k in ("book", "analyst", "date", "ticker", "heat", "direction", "version", "fwd_ret", "adj_ret",
                                               "author_n", "narrative_stage", "cap_bucket")})
    fr = [float(r["adj_ret"]) for r in rows if r.get("adj_ret") not in (None, "")]
    return {"count": len(rows), "positive_adj_ret_share": round(sum(1 for x in fr if x > 0) / len(fr), 3) if fr else None,
            "avg_adj_ret": round(sum(fr) / len(fr), 4) if fr else None, "rows": rows[-limit:]}


# ----------------------------------------------------------------------------- registry / ingest
def resolve_source(handle: str) -> dict:
    """Resolve an X handle / display name / citation name against sources.yaml (slug or alias,
    case-insensitive, leading @ stripped). A miss means `attributed_to: unattributed` — never guess."""
    txt = SOURCES_YAML.read_text()
    q = (handle or "").strip().lstrip("@").lower()
    cur = None
    for ln in txt.split("\n"):
        m = re.match(r"^\s*- slug:\s*(\S+)", ln)
        if m:
            cur = {"slug": m.group(1), "aliases": [], "display": None, "platform": None, "type": None, "status": None}
            entries = resolve_source.__dict__.setdefault("_entries", [])
            entries.append(cur); continue
        if cur is None: continue
        for k in ("display", "platform", "type", "status"):
            mm = re.match(rf"^\s*{k}:\s*(.+?)\s*$", ln)
            if mm: cur[k] = mm.group(1)
        ma = re.match(r"^\s*aliases:\s*\[(.*)\]", ln)
        if ma: cur["aliases"] = [a.strip().strip("'\"") for a in ma.group(1).split(",") if a.strip()]
    entries = resolve_source.__dict__.pop("_entries", [])
    for e in entries:
        if e["slug"].lower() == q or any(a.lower().lstrip("@") == q for a in e["aliases"]):
            return {"query": handle, "resolved": True, **e}
    return {"query": handle, "resolved": False, "attributed_to": "unattributed",
            "note": "no slug/alias match — a new-source registry candidate for the next human review"}


def ingest_status() -> dict:
    if not INGEST_STATUS.exists():
        return {"error": f"{INGEST_STATUS} missing"}
    return json.loads(INGEST_STATUS.read_text())


# ----------------------------------------------------------------------------- broker (read-only)
def broker_snapshot(book: str, subcommand: str = "account", timeout: int = 90) -> dict:
    """Shell out to the book's Alpaca adapter READ subcommand (`account` | `reconcile`). The
    adapter reads its own credentials; this module never touches ~/.alpaca. `submit`, `rebalance`,
    `--live`, `--auto`, `--allow-live` are refused by construction — this server cannot place an
    order. The ST adapter emits structured JSON; LONG/ROTATION are parsed from their text tables."""
    if subcommand not in READ_ONLY_ALPACA:
        raise PermissionError(f"refused: {subcommand!r} is not a read-only subcommand ({sorted(READ_ONLY_ALPACA)})")
    b = _book(book)
    cmd = b["alpaca"] + [subcommand] + (["--json"] if b["alpaca_json"] else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = p.stdout or ""
    res = {"book": book.upper(), "subcommand": subcommand, "rc": p.returncode, "paper": ("PAPER" in out) or None}
    if "===JSON===" in out:
        try:
            res["data"] = json.loads(out.split("===JSON===", 1)[1].strip())
        except Exception as e:
            res["parse_error"] = str(e)
    else:
        recs = []
        for ln in out.splitlines():
            m = re.match(r"^\s+([A-Z][A-Z0-9.]*)\s+(long|short)\s+qty\s+([\d.]+)\s+avg\s+\$([\d.]+)", ln, re.I)
            if m:
                recs.append({"symbol": m.group(1), "side": m.group(2).lower(), "qty": float(m.group(3)), "avg_entry_price": float(m.group(4))})
        eq = re.search(r"equity \$([\d.,]+)", out); cash = re.search(r"cash \$([\d.,]+)", out)
        res["data"] = {"positions": recs, "equity": float(eq.group(1).replace(",", "")) if eq else None,
                       "cash": float(cash.group(1).replace(",", "")) if cash else None}
    res["text_tail"] = out[-1200:]
    if p.stderr.strip():
        res["stderr_tail"] = p.stderr[-400:]
    return res


def reconcile_diff(book: str, timeout: int = 90) -> dict:
    """Ledger open positions vs broker positions — the DIFF only (no writes). Feeds the book's
    reconcile-first rule; booking any fill it reveals stays in the orchestrator."""
    snap = broker_snapshot(book, "account", timeout=timeout)
    broker = {(r["symbol"].upper()): r for r in (snap.get("data") or {}).get("positions", [])}
    ledger = {str(o["ticker"]).upper(): o for o in _ledger(book).get("open_positions", [])}
    only_ledger = sorted(set(ledger) - set(broker)); only_broker = sorted(set(broker) - set(ledger)); qty_mismatch = []
    for t in sorted(set(ledger) & set(broker)):
        lq, bq = float(ledger[t].get("shares") or 0), float(broker[t].get("qty") or 0)
        ls = "short" if str(ledger[t].get("direction", "")).upper() == "SHORT" else "long"
        if abs(lq - bq) > 1e-6 or ls != broker[t].get("side"):
            qty_mismatch.append({"ticker": t, "ledger": {"qty": lq, "side": ls}, "broker": {"qty": bq, "side": broker[t].get("side")}})
    return {"book": book.upper(), "in_sync": not (only_ledger or only_broker or qty_mismatch),
            "only_in_ledger": only_ledger, "only_at_broker": only_broker, "qty_or_side_mismatch": qty_mismatch,
            "broker_equity": (snap.get("data") or {}).get("equity"), "ledger_equity": _ledger(book).get("equity_asof"),
            "note": "SIM books (LONG) have no broker mirror positions by design; ROTATION/ST should tie out."}


def books() -> dict:
    out = {}
    for k, b in BOOKS.items():
        out[k] = {"horizon": b["horizon"], "ledger": str(b["ledger"]), "ledger_exists": b["ledger"].exists(),
                  "graph_dir": str(b["graph_dir"]), "graphs": [v for v in VAULTS if (b["graph_dir"] / f"{v}.json").exists()],
                  "runs_dir": str(b["runs"])}
    return out
