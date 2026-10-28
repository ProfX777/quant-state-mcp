#!/bin/sh
# Register quant-state with the Claude desktop app for ordinary chats.
#
# The app loads claude_desktop_config.json once at launch, keeps it in memory, and writes the whole
# file back whenever it saves a preference, so an entry added while the app is running is lost on
# the next save. This script quits the app, adds the entry, and relaunches it. Run it from
# Terminal.app (not from a terminal inside Claude, which dies when the app quits):
#
#     sh ~/Developer/quant-state-mcp/install_desktop.sh
#
set -e
CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
APP="/Applications/Claude.app/Contents/MacOS/Claude"
HERE="$(cd "$(dirname "$0")" && pwd)"

osascript -e 'tell application "Claude" to quit' >/dev/null 2>&1 || true
for _ in $(seq 1 30); do
    pgrep -f "$APP" >/dev/null || break
    sleep 1
done
if pgrep -f "$APP" >/dev/null; then
    echo "Claude is still running. Quit it (Cmd+Q) and run this again." >&2
    exit 1
fi

cp "$CFG" "$CFG.bak-$(date +%Y%m%d-%H%M%S)"
python3 - "$CFG" "$HERE" <<'EOF'
import json, os, sys
path, here = sys.argv[1], sys.argv[2]
cfg = json.load(open(path))
cfg.setdefault("mcpServers", {})["quant-state"] = {
    "command": os.path.join(here, ".venv", "bin", "python"),
    "args": [os.path.join(here, "server.py")],
    "env": {"QUANT_STATE_CONFIG": os.path.expanduser("~/.quant-state/config.json")},
}
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
print("quant-state added; config keys now:", ", ".join(cfg))
EOF

open -a Claude
echo "Claude relaunched. In a new chat, ask: what's trending in my LONG book?"
