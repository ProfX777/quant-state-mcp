#!/usr/bin/env python3
"""End-to-end smoke test: spawn server.py over stdio with the official client, list tools and
resources, call the read-only tools, read a resource. No broker calls (those hit Alpaca)."""
import asyncio, json, sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).parent
PY = HERE / ".venv/bin/python"

EXPECTED_TOOLS = {"list_books", "graph_meta", "resolve_entity", "get_theme", "get_ticker_context", "fading_theses",
                  "ledger_summary", "get_positions", "get_pick_outcomes", "hit_rate", "score_run", "list_runs",
                  "forecast_rows", "resolve_source", "ingest_status", "broker_snapshot", "reconcile_diff"}
CALLS = [
    ("list_books", {}, lambda r: set(r) == {"LONG", "ST", "ROTATION"}),
    ("resolve_entity", {"book": "LONG", "mention": "Micron"}, lambda r: r["canonical"] == "MU"),
    ("get_theme", {"book": "LONG", "name": "AI Infrastructure", "evidence_limit": 3}, lambda r: r["found"] and len(r["evidence"]) == 3),
    ("get_ticker_context", {"book": "LONG", "ticker": "MU"}, lambda r: r["ledger"]["open"][0]["shares"] == 8),
    ("fading_theses", {"book": "ST", "limit": 3}, lambda r: r["count"] >= 0),
    ("ledger_summary", {"book": "LONG"}, lambda r: r["open_positions"] == 9),
    ("get_positions", {"book": "ROTATION"}, lambda r: len(r["positions"]) == 5),
    ("get_pick_outcomes", {"book": "LONG", "since": "2026-09-22"}, lambda r: r["count"] == 8),
    ("hit_rate", {"book": "LONG", "strategy_version": "LONG-v1.0"}, lambda r: r["n"] == 13 and r["wins"] == 4),
    ("score_run", {"book": "LONG", "date": "2026-08-07"}, lambda r: r["run_note_exists"]),
    ("list_runs", {"book": "ST", "limit": 2}, lambda r: r["latest"][-1] == "2026-09-15"),
    ("forecast_rows", {"book": "LONG", "ticker": "MU", "limit": 2}, lambda r: r["count"] > 0),
    ("resolve_source", {"handle": "@dylan522p"}, lambda r: r["slug"] == "dylan522p"),
    ("ingest_status", {}, lambda r: r["date"] == "2026-09-20"),
]


async def main():
    params = StdioServerParameters(command=str(PY), args=[str(HERE / "server.py")])
    ok = 0; total = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = {t.name: t for t in (await s.list_tools()).tools}
            total += 1; c = EXPECTED_TOOLS <= set(tools); ok += c
            print(f"[{'PASS' if c else 'FAIL'}] {len(tools)} tools registered; expected set present  missing={sorted(EXPECTED_TOOLS - set(tools))}")
            def _ro(t):   # mcp 2.x pydantic field is read_only_hint (camelCase alias on the wire)
                a = t.annotations
                return bool(a and (getattr(a, "read_only_hint", None) or getattr(a, "readOnlyHint", None)))
            total += 1; c = all(_ro(tools[n]) for n in EXPECTED_TOOLS if n in tools); ok += c
            print(f"[{'PASS' if c else 'FAIL'}] every tool carries readOnlyHint=True")
            def g(o, *names):   # mcp 2.x models are snake_case; tolerate camelCase too
                for n in names:
                    if hasattr(o, n): return getattr(o, n)
                raise AttributeError(names)
            res = (await s.list_resources()).resources
            tmpl = g(await s.list_resource_templates(), "resource_templates", "resourceTemplates")
            uris = {str(r.uri) for r in res} | {g(t, "uri_template", "uriTemplate") for t in tmpl}
            total += 1; c = {"quant://books", "quant://ingest", "quant://ledger/{book}", "quant://run/{book}/{date}"} <= uris; ok += c
            print(f"[{'PASS' if c else 'FAIL'}] resources: {sorted(uris)}")
            for name, args, pred in CALLS:
                total += 1
                r = await s.call_tool(name, args)
                sc = g(r, "structured_content", "structuredContent")
                payload = sc if sc is not None else json.loads(r.content[0].text)
                if isinstance(payload, dict) and set(payload) == {"result"}:
                    payload = payload["result"]
                try:
                    c = (not g(r, "is_error", "isError")) and pred(payload)
                except Exception as e:
                    c = False; payload = f"{payload!r}"[:200] + f" ({e!r})"
                ok += c
                size = len(json.dumps(payload, default=str)) if not isinstance(payload, str) else len(payload)
                print(f"[{'PASS' if c else 'FAIL'}] {name}({', '.join(f'{k}={v!r}' for k, v in args.items())}) -> {size} bytes")
            total += 1
            rr = await s.read_resource("quant://ingest")
            txt = rr.contents[0].text; c = '"date": "2026-09-20"' in txt; ok += c
            print(f"[{'PASS' if c else 'FAIL'}] read_resource quant://ingest -> {len(txt)} bytes")
            total += 1
            rr = await s.read_resource("quant://run/ST/2026-09-15")
            c = rr.contents[0].text.startswith("---"); ok += c
            print(f"[{'PASS' if c else 'FAIL'}] read_resource quant://run/ST/2026-09-15 -> {len(rr.contents[0].text)} bytes")
    print(f"\n{ok}/{total} checks passed")
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
