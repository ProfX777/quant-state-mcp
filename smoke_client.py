#!/usr/bin/env python3
"""End-to-end smoke test over the real MCP protocol: start server.py over stdio with the official
client, list tools and resources, call every tool, read two resources. Uses the bundled SAMPLE data,
so it runs anywhere (including CI).

    python smoke_client.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent

EXPECTED_TOOLS = {"list_books", "graph_meta", "resolve_entity", "get_theme", "get_ticker_context", "fading_theses",
                  "ledger_summary", "get_positions", "get_pick_outcomes", "hit_rate", "score_run", "list_runs",
                  "forecast_rows", "resolve_source", "ingest_status", "broker_snapshot", "reconcile_diff"}
CALLS = [
    ("list_books", {}, lambda r: r["data_source"]["label"] == "SAMPLE" and set(r["books"]) == {"LONG", "ST", "ROTATION"}),
    ("graph_meta", {"book": "LONG"}, lambda r: set(r["domains"]) == {"tech", "macro"}),
    ("resolve_entity", {"book": "LONG", "mention": "Micron"}, lambda r: r["canonical"] == "MU"),
    ("get_theme", {"book": "LONG", "name": "AI Infrastructure", "evidence_limit": 3}, lambda r: r["found"] and len(r["evidence"]) == 3),
    ("get_ticker_context", {"book": "LONG", "ticker": "MU"}, lambda r: r["ledger"]["open"][0]["shares"] == 10),
    ("fading_theses", {"book": "ST", "limit": 3}, lambda r: r["count"] == 2),
    ("ledger_summary", {"book": "LONG"}, lambda r: r["open_positions"] == 3),
    ("get_positions", {"book": "ROTATION"}, lambda r: len(r["positions"]) == 3),
    ("get_pick_outcomes", {"book": "LONG", "since": "2026-09-20"}, lambda r: r["count"] == 4),
    ("hit_rate", {"book": "LONG", "strategy_version": "LONG-v1.0"}, lambda r: r["n"] == 4 and r["wins"] == 2),
    ("score_run", {"book": "LONG", "date": "2026-08-01"}, lambda r: r["run_note_exists"] and r["wins"] == 1),
    ("list_runs", {"book": "ST", "limit": 2}, lambda r: r["latest"][-1] == "2026-10-01"),
    ("forecast_rows", {"book": "LONG", "ticker": "MU"}, lambda r: r["count"] == 2),
    ("resolve_source", {"handle": "@ExampleAnalyst"}, lambda r: r["slug"] == "example-analyst"),
    ("ingest_status", {}, lambda r: r["date"] == "2026-10-01"),
    ("broker_snapshot", {"book": "ST"}, lambda r: len(r["data"]["positions"]) == 2),
    ("reconcile_diff", {"book": "ROTATION"}, lambda r: r["only_at_broker"] == ["XLU"]),
]


def attr(obj, *names):
    """mcp 2.x models use snake_case; tolerate camelCase too."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    raise AttributeError(names)


async def main():
    env = {k: v for k, v in os.environ.items() if k != "QUANT_STATE_CONFIG"}   # force the bundled sample
    params = StdioServerParameters(command=sys.executable, args=[str(HERE / "server.py")], env=env, cwd=str(HERE))
    ok = total = 0

    def report(passed, msg):
        nonlocal ok, total
        total += 1
        ok += bool(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            init = await s.initialize()
            instructions = attr(init, "instructions") or ""
            report("DATA SOURCE: SAMPLE" in instructions, "server announces its data source at startup")

            tools = {t.name: t for t in (await s.list_tools()).tools}
            report(EXPECTED_TOOLS <= set(tools), f"{len(tools)} tools registered (missing: {sorted(EXPECTED_TOOLS - set(tools))})")
            report(all(attr(tools[n].annotations, "read_only_hint", "readOnlyHint") for n in EXPECTED_TOOLS if n in tools),
                   "every tool is marked read-only")

            res = (await s.list_resources()).resources
            tmpl = attr(await s.list_resource_templates(), "resource_templates", "resourceTemplates")
            uris = {str(r.uri) for r in res} | {attr(t, "uri_template", "uriTemplate") for t in tmpl}
            report({"quant://books", "quant://ingest", "quant://ledger/{book}", "quant://run/{book}/{date}"} <= uris,
                   f"resources: {sorted(uris)}")

            for name, args, pred in CALLS:
                r = await s.call_tool(name, args)
                sc = attr(r, "structured_content", "structuredContent")
                payload = sc if sc is not None else json.loads(r.content[0].text)
                if isinstance(payload, dict) and set(payload) == {"result"}:
                    payload = payload["result"]
                try:
                    passed = (not attr(r, "is_error", "isError")) and pred(payload)
                except Exception as e:  # report the payload rather than crash the run
                    passed, payload = False, f"{payload!r}"[:200] + f" ({e!r})"
                size = len(json.dumps(payload, default=str))
                report(passed, f"{name}({', '.join(f'{k}={v!r}' for k, v in args.items())}) -> {size} bytes")

            txt = (await s.read_resource("quant://ingest")).contents[0].text
            report('"2026-10-01"' in txt, f"read quant://ingest -> {len(txt)} bytes")
            txt = (await s.read_resource("quant://run/ST/2026-10-01")).contents[0].text
            report(txt.startswith("---"), f"read quant://run/ST/2026-10-01 -> {len(txt)} bytes")

    print(f"\n{ok}/{total} checks passed")
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
