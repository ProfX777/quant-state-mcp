"""quant-state: READ-ONLY accessors over a three-book AI research and paper-trading system.

Pure functions with no MCP dependency, so they can be tested directly. Every function takes a `book`
in {LONG, ST, ROTATION}, because the three books keep separate ledgers, graphs and run notes.

WHERE THE DATA LIVES IS A CONFIG FILE, NOT CODE
  * QUANT_STATE_CONFIG=/path/to/config.json  -> use that file (a real deployment)
  * unset                                    -> sample_data/config.json (bundled, invented data)
Relative paths in a config resolve against the config file's own folder, `~` expands, and the token
"{python}" in a broker command means "the Python running this server". Every response that describes
the system carries `data_source`, so sample numbers can never be mistaken for live ones.

What a book's data looks like (see sample_data/ for a complete example):
  * ledger      JSON with meta, open_positions, closed_positions, cash, equity history
  * runs        a folder of per-run notes named YYYY-MM-DD.md
  * domains     research areas (e.g. tech, macro), each with a graph snapshot JSON (hub rows with
                pagerank / velocity / staleness, per-hub evidence edges, narrative stages) and folders
                of theme ("trend") and company ("ticker") notes whose front-matter carries aliases,
                direction, strength and a realized-outcome track record
  * broker      an optional adapter command; ONLY its read subcommands are ever run
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_ENV = "QUANT_STATE_CONFIG"
DEFAULT_CONFIG = HERE / "sample_data" / "config.json"
READ_ONLY_BROKER = {"account", "reconcile"}   # the ONLY broker subcommands this module will ever run


class BookError(ValueError):
    pass


class ConfigError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- configuration
def _resolve(base: Path, value):
    if value in (None, ""):
        return None
    p = Path(os.path.expanduser(str(value)))
    return p if p.is_absolute() else (base / p).resolve()


def load_config(path=None) -> dict:
    """Read and normalise a config file. Raises ConfigError with a fix-it message if it is missing."""
    p = Path(os.path.expanduser(str(path or os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG)))
    if not p.exists():
        raise ConfigError(f"config not found: {p}. Set {CONFIG_ENV} to a valid config file, "
                          f"or unset it to use the bundled sample data.")
    raw = json.loads(p.read_text())
    base = p.parent
    books = {}
    for name, b in raw["books"].items():
        domains = [{"name": d["name"], "graph": _resolve(base, d.get("graph")),
                    "hubs": {kind: _resolve(base, folder) for kind, folder in (d.get("hubs") or {}).items()}}
                   for d in b.get("domains", [])]
        broker = b.get("broker")
        if broker:
            cmd = []
            for part in broker["cmd"]:
                if part == "{python}":
                    cmd.append(sys.executable)
                elif part.endswith(".py"):
                    cmd.append(str(_resolve(base, part)))
                else:
                    cmd.append(os.path.expanduser(part))
            broker = {"cmd": cmd, "json": bool(broker.get("json"))}
        books[name.upper()] = {"horizon": b.get("horizon", ""), "ledger": _resolve(base, b["ledger"]),
                               "runs": _resolve(base, b.get("runs")), "domains": domains, "broker": broker}
    return {"label": raw.get("label", "UNLABELLED"), "path": str(p), "books": books,
            "sources_yaml": _resolve(base, raw.get("sources_yaml")),
            "forecast_csv": _resolve(base, raw.get("forecast_csv")),
            "ingest_status": _resolve(base, raw.get("ingest_status"))}


CONFIG = load_config()


def data_source() -> dict:
    return {"label": CONFIG["label"], "config": CONFIG["path"]}


def _book(book: str) -> dict:
    b = (book or "").upper()
    if b not in CONFIG["books"]:
        raise BookError(f"unknown book {book!r}; expected one of {sorted(CONFIG['books'])}")
    return CONFIG["books"][b]


def books() -> dict:
    out = {}
    for name, b in CONFIG["books"].items():
        out[name] = {"horizon": b["horizon"], "ledger_exists": bool(b["ledger"] and b["ledger"].exists()),
                     "domains": [d["name"] for d in b["domains"]],
                     "graphs_available": [d["name"] for d in b["domains"] if d["graph"] and d["graph"].exists()],
                     "run_notes": bool(b["runs"] and b["runs"].exists()),
                     "broker_configured": bool(b["broker"])}
    return {"data_source": data_source(), "books": out}


# ----------------------------------------------------------------------------- front-matter
def _fm(path: Path) -> dict:
    """Minimal front-matter reader for hub notes: scalars, flat lists, and the realized_outcomes
    list-of-dicts. Dependency-free on purpose."""
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
        if val in ("", "[]"):
            cur_list = []
            out[key] = cur_list
        else:
            cur_list = None
            out[key] = val.strip("'\"")
    return out


def _hub_files(book: str):
    for d in _book(book)["domains"]:
        for kind, folder in d["hubs"].items():
            if folder and folder.exists():
                for p in sorted(folder.glob("*.md")):
                    yield d["name"], kind, p


def hub_path(book: str, name: str):
    for _domain, _kind, p in _hub_files(book):
        if p.stem == name:
            return p
    return None


def resolve_entity(book: str, mention: str) -> dict:
    """Map a mention ('Micron', '$MU', 'AI infra') to the canonical hub name via each hub's `aliases`.
    A non-canonical link silently drops its graph edge, so this is the lookup triage does by hand."""
    q = (mention or "").strip().lstrip("[").rstrip("]").strip()
    ql = q.lower().lstrip("$")
    alias_hits = []
    for domain, kind, p in _hub_files(book):
        stem = p.stem
        if stem.lower() == ql or stem.lower().split(" — ")[0] == ql:
            return {"query": q, "resolved": True, "canonical": stem, "domain": domain, "kind": kind, "match": "name"}
        for a in _fm(p).get("aliases", []) or []:
            if str(a).lower().lstrip("$") == ql:
                alias_hits.append({"canonical": stem, "domain": domain, "kind": kind, "match": f"alias:{a}"})
    if alias_hits:
        return {"query": q, "resolved": True, **alias_hits[0], "other_matches": alias_hits[1:]}
    return {"query": q, "resolved": False, "note": "no hub or alias matches; do not link it, flag it as a new-hub candidate"}


# ----------------------------------------------------------------------------- graph
def _graph(domain: dict) -> dict:
    p = domain["graph"]
    if not p or not p.exists():
        raise FileNotFoundError(f"no graph snapshot for domain {domain['name']!r}")
    return json.loads(p.read_text())


def graph_meta(book: str) -> dict:
    out = {}
    for d in _book(book)["domains"]:
        try:
            g = _graph(d)
        except FileNotFoundError as e:
            out[d["name"]] = {"error": str(e)}
            continue
        out[d["name"]] = {"generated": g.get("generated"), "as_of": g.get("today"), "counts": g.get("counts"),
                          "components": (g.get("connectivity") or {}).get("post", {}).get("n_components"),
                          "contradiction_flags": len(g.get("contradictions") or []),
                          "half_life_days": g.get("edge_half_life_days"), "stale_after_days": g.get("stale_assessment_days")}
    return {"book": book.upper(), "data_source": data_source(), "domains": out}


def _find_row(book: str, name: str):
    nl = name.lower()
    for d in _book(book)["domains"]:
        try:
            g = _graph(d)
        except FileNotFoundError:
            continue
        for r in g.get("rows", []):
            if r.get("type") in ("trend", "ticker") and str(r.get("name", "")).lower() == nl:
                return d["name"], g, r
    return None, None, None


def get_theme(book: str, name: str, evidence_limit: int = 8) -> dict:
    """A hub (theme or company) as the graph and its own notes see it: direction, strength, staleness,
    pagerank, velocity, narrative stage, realized track record, and the strongest evidence edges."""
    res = resolve_entity(book, name)
    canonical = res.get("canonical", name)
    domain, g, row = _find_row(book, canonical)
    if row is None:
        return {"book": book.upper(), "query": name, "found": False, "resolve": res}
    ev = sorted((g.get("hub_evidence") or {}).get(canonical, []), key=lambda e: -(e.get("weight") or 0))
    stage = (g.get("narrative_stages") or {}).get(canonical, {})
    p = hub_path(book, canonical)
    fm = _fm(p) if p else {}
    ro = fm.get("realized_outcomes") or []
    n = int(fm.get("realized_n") or 0)
    return {
        "book": book.upper(), "domain": domain, "hub": canonical, "type": row.get("type"), "found": True,
        "graph_as_of": g.get("today"),
        "direction": fm.get("direction") or row.get("direction"), "strength": fm.get("strength") or row.get("strength"),
        "last_assessed": fm.get("last_assessed"), "stale": row.get("stale"), "age_days": row.get("age_days"),
        "pagerank": row.get("pagerank"), "deep_read_score": row.get("deep_read_score"), "velocity": row.get("velocity"),
        "momentum": row.get("momentum"), "in_degree": row.get("in_degree"),
        "narrative_stage": stage.get("narrative_stage"), "stage_transition": stage.get("stage_transition"),
        "source_diversity": stage.get("source_diversity_count"),
        "realized": {"n": n, "hit_rate": float(fm["realized_hit_rate"]) if n else None, "last": ro[-1] if ro else None},
        "aliases": fm.get("aliases") or [],
        "evidence_count": len(ev),
        "evidence": [{"source": e.get("source_note"), "weight": e.get("weight"), "age_days": e.get("age_days"),
                      "stance": e.get("stance"), "conf": e.get("conf"), "quote": (e.get("quote") or "")[:160]}
                     for e in ev[:evidence_limit]],
    }


def get_ticker_context(book: str, ticker: str) -> dict:
    """get_theme for a ticker plus the book's ledger exposure to it (open position or most recent close)."""
    t = get_theme(book, ticker)
    L = _ledger(book)
    tk = ticker.upper().lstrip("$")
    open_pos = [_slim_pos(o) for o in L.get("open_positions", []) if str(o.get("ticker", "")).upper() == tk]
    closes = [c for c in L.get("closed_positions", []) if str(c.get("ticker", "")).upper() == tk]
    t["ledger"] = {"open": open_pos, "last_close": _slim_close(closes[-1]) if closes else None, "closes_total": len(closes)}
    return t


def fading_theses(book: str, limit: int = 15) -> dict:
    """Hubs whose support is decaying (stale, decelerating, negative velocity, weak strength), worst first."""
    out = []
    for d in _book(book)["domains"]:
        try:
            g = _graph(d)
        except FileNotFoundError:
            continue
        stages = g.get("narrative_stages") or {}
        for r in g.get("rows", []):
            if r.get("type") not in ("trend", "ticker"):
                continue
            reasons = []
            if r.get("stale"):
                reasons.append(f"stale ({r.get('age_days')}d since assessment)")
            if r.get("direction") == "decelerating":
                reasons.append("direction decelerating")
            if (r.get("velocity") or 0) < 0:
                reasons.append(f"velocity {r.get('velocity')}")
            if r.get("strength") in ("low", "unknown") and r.get("type") == "trend":
                reasons.append(f"strength {r.get('strength')}")
            if reasons:
                out.append({"domain": d["name"], "hub": r["name"], "type": r["type"], "direction": r.get("direction"),
                            "strength": r.get("strength"), "age_days": r.get("age_days"), "velocity": r.get("velocity"),
                            "pagerank": r.get("pagerank"),
                            "narrative_stage": stages.get(r["name"], {}).get("narrative_stage"), "reasons": reasons})
    out.sort(key=lambda x: (-len(x["reasons"]), -(x["age_days"] or 0)))
    return {"book": book.upper(), "count": len(out), "hubs": out[:limit]}


# ----------------------------------------------------------------------------- ledgers
def _ledger(book: str) -> dict:
    return json.loads(_book(book)["ledger"].read_text())


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
    L = _ledger(book)
    m = L.get("meta", {})
    eh = L.get("equity_history") or []
    return {"book": book.upper(), "data_source": data_source(), "strategy_version": m.get("strategy_version"),
            "as_of": m.get("as_of") or L.get("as_of"), "cash": L.get("cash"), "equity": L.get("equity_asof"),
            "gross_exposure_pct": L.get("gross_exposure_pct"), "realized_pnl_total": L.get("realized_pnl_total"),
            "unrealized_pnl_total": L.get("unrealized_pnl_total"), "total_return_pct": L.get("total_return_pct"),
            "open_positions": len(L.get("open_positions", [])), "closed_positions": len(L.get("closed_positions", [])),
            "working_orders": len(L.get("working_orders", []) or []),
            "last_equity_mark": {"date": eh[-1].get("date"), "equity": eh[-1].get("equity")} if eh else None,
            "flags_count": len(L.get("flags") or [])}


def get_positions(book: str) -> dict:
    L = _ledger(book)
    return {"book": book.upper(), "data_source": data_source()["label"],
            "as_of": (L.get("meta") or {}).get("as_of") or L.get("as_of"),
            "positions": [_slim_pos(o) for o in L.get("open_positions", [])]}


def _closed_date(c: dict) -> str:
    return str(c.get("closed_date") or c.get("date_closed") or "")


def get_pick_outcomes(book: str, ticker: str | None = None, since: str | None = None, limit: int = 50) -> dict:
    rows = _ledger(book).get("closed_positions", [])
    if ticker:
        rows = [c for c in rows if str(c.get("ticker", "")).upper() == ticker.upper()]
    if since:
        rows = [c for c in rows if _closed_date(c) >= since]
    rows = sorted(rows, key=_closed_date)[-limit:]
    return {"book": book.upper(), "count": len(rows), "closes": [_slim_close(c) for c in rows]}


def _outcome(c: dict):
    if c.get("outcome"):
        return c["outcome"]
    v = str(c.get("verdict", "")).lower()
    if "winner" in v:
        return "win"
    if "loser" in v or "stopped" in v or "killed" in v:
        return "loss"
    if "mixed" in v:
        return "flat"
    pct = c.get("realized_pct") if c.get("realized_pct") is not None else c.get("rotation_pnl_pct")
    if pct is None:
        return None
    return "win" if pct > 1.0 else "loss" if pct < -1.0 else "flat"


def hit_rate(book: str, strategy_version: str | None = None, since: str | None = None) -> dict:
    """Realized hit rate: wins / graded closes, with flat counting in the denominator. Filter by
    strategy_version to keep cohorts from different rule versions apart."""
    rows = _ledger(book).get("closed_positions", [])
    if strategy_version:
        rows = [c for c in rows if c.get("strategy_version") == strategy_version]
    if since:
        rows = [c for c in rows if _closed_date(c) >= since]
    graded = [(c, o) for c, o in ((c, _outcome(c)) for c in rows) if o]
    n = len(graded)
    w = sum(1 for _, o in graded if o == "win")
    f = sum(1 for _, o in graded if o == "flat")
    pcts = [c.get("realized_pct") if c.get("realized_pct") is not None else c.get("rotation_pnl_pct") for c, _ in graded]
    pcts = [p for p in pcts if p is not None]
    return {"book": book.upper(), "strategy_version": strategy_version, "since": since, "n": n, "wins": w,
            "flats": f, "losses": n - w - f, "hit_rate": round(w / n, 3) if n else None,
            "avg_return_pct": round(sum(pcts) / len(pcts), 2) if pcts else None,
            "note": "hit_rate = wins / graded closes; flat counts in the denominator"}


def score_run(book: str, date: str) -> dict:
    """Everything the ledger knows about one run (YYYY-MM-DD): what it closed, what it still holds."""
    L = _ledger(book)
    closes = [c for c in L.get("closed_positions", []) if date in str(c.get("originating_synthesis", ""))]
    opens = [o for o in L.get("open_positions", []) if date in str(o.get("originating_synthesis", ""))]
    runs = _book(book)["runs"]
    graded = [(_outcome(c), c) for c in closes]
    return {"book": book.upper(), "run": date, "run_note_exists": bool(runs and (runs / f"{date}.md").exists()),
            "closed": [_slim_close(c) for c in closes], "still_open": [_slim_pos(o) for o in opens],
            "wins": sum(1 for o, _ in graded if o == "win"), "losses": sum(1 for o, _ in graded if o == "loss"),
            "flats": sum(1 for o, _ in graded if o == "flat"),
            "realized_pnl": round(sum(c.get("realized_pnl") or 0 for c in closes), 2)}


def list_runs(book: str, limit: int = 12) -> dict:
    d = _book(book)["runs"]
    dates = sorted(p.stem for p in d.glob("????-??-??.md")) if d and d.exists() else []
    return {"book": book.upper(), "count": len(dates), "latest": dates[-limit:]}


def run_note(book: str, date: str) -> str:
    d = _book(book)["runs"]
    p = d / f"{date}.md" if d else None
    if not p or not p.exists():
        raise FileNotFoundError(f"no run note for {book}/{date}")
    return p.read_text()


# ----------------------------------------------------------------------------- forecast ledger
def forecast_rows(book: str | None = None, analyst: str | None = None, ticker: str | None = None,
                  author: str | None = None, limit: int = 100) -> dict:
    """Candidate-level forward-return rows (every analyst candidate, picked or not). Directional
    instrumentation only, never a trade signal."""
    p = CONFIG["forecast_csv"]
    if not p or not p.exists():
        return {"error": "no forecast ledger configured"}
    rows = []
    with p.open() as f:
        for r in csv.DictReader(f):
            if book and r.get("book", "").upper() != book.upper():
                continue
            if analyst and r.get("analyst") != analyst:
                continue
            if ticker and r.get("ticker", "").upper() != ticker.upper():
                continue
            if author and author not in (r.get("authors") or ""):
                continue
            rows.append({k: r.get(k) for k in ("book", "analyst", "date", "ticker", "heat", "direction", "version",
                                               "fwd_ret", "adj_ret", "author_n", "narrative_stage", "cap_bucket")})
    adj = [float(r["adj_ret"]) for r in rows if r.get("adj_ret") not in (None, "")]
    return {"count": len(rows), "positive_adj_ret_share": round(sum(x > 0 for x in adj) / len(adj), 3) if adj else None,
            "avg_adj_ret": round(sum(adj) / len(adj), 4) if adj else None, "rows": rows[-limit:]}


# ----------------------------------------------------------------------------- registry / ingest
def _registry() -> list:
    p = CONFIG["sources_yaml"]
    entries, cur = [], None
    for ln in (p.read_text().split("\n") if p and p.exists() else []):
        m = re.match(r"^\s*- slug:\s*(\S+)", ln)
        if m:
            cur = {"slug": m.group(1), "aliases": [], "display": None, "platform": None, "type": None, "status": None}
            entries.append(cur)
            continue
        if cur is None:
            continue
        for k in ("display", "platform", "type", "status"):
            mm = re.match(rf"^\s*{k}:\s*(.+?)\s*$", ln)
            if mm:
                cur[k] = mm.group(1)
        ma = re.match(r"^\s*aliases:\s*\[(.*)\]", ln)
        if ma:
            cur["aliases"] = [a.strip().strip("'\"") for a in ma.group(1).split(",") if a.strip()]
    return entries


def resolve_source(handle: str) -> dict:
    """Resolve a handle or name against the source registry (slug or alias, case-insensitive, leading
    @ ignored). A miss returns attributed_to: unattributed; a slug is never guessed."""
    q = (handle or "").strip().lstrip("@").lower()
    for e in _registry():
        if e["slug"].lower() == q or any(a.lower().lstrip("@") == q for a in e["aliases"]):
            return {"query": handle, "resolved": True, **e}
    return {"query": handle, "resolved": False, "attributed_to": "unattributed",
            "note": "no slug or alias matches; a candidate to add on the next registry review"}


def ingest_status() -> dict:
    p = CONFIG["ingest_status"]
    if not p or not p.exists():
        return {"error": "no ingest marker configured"}
    return json.loads(p.read_text())


# ----------------------------------------------------------------------------- broker (read-only)
_POS_RE = re.compile(r"^\s+([A-Z][A-Z0-9.]*)\s+(long|short)\s+qty\s+([\d.]+)\s+avg\s+\$\s*([\d.]+)", re.I)


def broker_snapshot(book: str, subcommand: str = "account", timeout: int = 90) -> dict:
    """Run the book's broker adapter with a READ subcommand (`account` or `reconcile`) and parse its
    positions, equity and cash. `submit`, `rebalance` and every live/auto flag are refused before any
    process starts, so this module cannot place an order. Adapters read their own credentials."""
    if subcommand not in READ_ONLY_BROKER:
        raise PermissionError(f"refused: {subcommand!r} is not a read-only subcommand ({sorted(READ_ONLY_BROKER)})")
    b = _book(book)
    if not b["broker"]:
        return {"book": book.upper(), "error": "no broker configured for this book"}
    cmd = b["broker"]["cmd"] + [subcommand] + (["--json"] if b["broker"]["json"] else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = p.stdout or ""
    res = {"book": book.upper(), "data_source": data_source()["label"], "subcommand": subcommand,
           "rc": p.returncode, "paper": ("PAPER" in out) or None}
    if "===JSON===" in out:
        try:
            res["data"] = json.loads(out.split("===JSON===", 1)[1].strip())
        except ValueError as e:
            res["parse_error"] = str(e)
    else:
        recs = [{"symbol": m.group(1), "side": m.group(2).lower(), "qty": float(m.group(3)),
                 "avg_entry_price": float(m.group(4))} for m in map(_POS_RE.match, out.splitlines()) if m]
        eq = re.search(r"equity \$([\d.,]+)", out)
        cash = re.search(r"cash \$([\d.,]+)", out)
        res["data"] = {"positions": recs, "equity": float(eq.group(1).replace(",", "")) if eq else None,
                       "cash": float(cash.group(1).replace(",", "")) if cash else None}
    if p.stderr.strip():
        res["stderr_tail"] = p.stderr[-400:]
    return res


def reconcile_diff(book: str, timeout: int = 90) -> dict:
    """Ledger open positions vs broker positions: the DIFF only, no writes. Booking any fill it reveals
    stays with whatever owns the ledger."""
    snap = broker_snapshot(book, "account", timeout=timeout)
    if "error" in snap:
        return snap
    data = snap.get("data") or {}
    broker = {r["symbol"].upper(): r for r in data.get("positions", [])}
    ledger = {str(o["ticker"]).upper(): o for o in _ledger(book).get("open_positions", [])}
    only_ledger, only_broker = sorted(set(ledger) - set(broker)), sorted(set(broker) - set(ledger))
    mismatch = []
    for t in sorted(set(ledger) & set(broker)):
        lq, bq = float(ledger[t].get("shares") or 0), float(broker[t].get("qty") or 0)
        ls = "short" if str(ledger[t].get("direction", "")).upper() == "SHORT" else "long"
        if abs(lq - bq) > 1e-6 or ls != broker[t].get("side"):
            mismatch.append({"ticker": t, "ledger": {"qty": lq, "side": ls}, "broker": {"qty": bq, "side": broker[t].get("side")}})
    return {"book": book.upper(), "data_source": data_source()["label"],
            "in_sync": not (only_ledger or only_broker or mismatch),
            "only_in_ledger": only_ledger, "only_at_broker": only_broker, "qty_or_side_mismatch": mismatch,
            "broker_equity": data.get("equity"), "ledger_equity": _ledger(book).get("equity_asof")}
