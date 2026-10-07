#!/usr/bin/env python3
"""Stand-in broker adapter for the SAMPLE dataset.

Prints canned paper-account output in the same two formats real adapters use (a text table, plus an
optional `===JSON===` block) for the read-only subcommands `account` and `reconcile`, and refuses
everything else. It lets the broker tools be demonstrated and tested without credentials or a network.

    python fake_broker.py --book ST account --json
"""
import json
import sys

POSITIONS = {
    "LONG": [],  # the long-horizon book is a simulated ledger with no broker mirror
    "ST": [
        {"symbol": "SPY", "side": "long", "qty": 20, "avg_entry_price": 560.0},
        {"symbol": "USO", "side": "short", "qty": 40, "avg_entry_price": 75.0},
    ],
    "ROTATION": [
        {"symbol": "XLK", "side": "long", "qty": 40, "avg_entry_price": 230.0},
        {"symbol": "XLI", "side": "long", "qty": 60, "avg_entry_price": 130.0},
        {"symbol": "XLV", "side": "long", "qty": 50, "avg_entry_price": 145.0},
        {"symbol": "XLU", "side": "long", "qty": 5, "avg_entry_price": 80.0},  # deliberate break: not in the ledger
    ],
}
EQUITY = {"LONG": 101234.56, "ST": 98500.00, "ROTATION": 103210.00}
CASH = {"LONG": 62000.00, "ST": 72000.00, "ROTATION": 58000.00}
READ_ONLY = {"account", "reconcile"}


def main(argv):
    book = argv[argv.index("--book") + 1].upper() if "--book" in argv else "ST"
    sub = next((a for a in argv if not a.startswith("-") and a not in (book, book.lower())), None)
    if sub not in READ_ONLY:
        print(f"REFUSED: the sample broker serves only {sorted(READ_ONLY)}, not {sub!r}", file=sys.stderr)
        return 2
    pos = POSITIONS[book]
    print(f"PAPER account SAMPLE | ACTIVE | equity ${EQUITY[book]:,.2f} | cash ${CASH[book]:,.2f}")
    print(f"positions ({len(pos)}):")
    for p in pos:
        print(f"  {p['symbol']:6s} {p['side']:5s} qty {p['qty']:>8g} avg ${p['avg_entry_price']:>10g}")
    print("\n  SELF-CHECK: OK (sample data)")
    if "--json" in argv:
        print("===JSON===")
        print(json.dumps({"equity": EQUITY[book], "cash": CASH[book], "positions": pos}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
