#!/bin/bash
# Desktop runtime for the ORIGINAL Flash client (no browser, no bridge).
# Logs in through the supplied Apache/PHP pages, extracts the exact flashvars
# Gamelogin.php would give Flash Player, and plays the SUPPLIED /res/Main.swf
# in Ruffle desktop (native TCP sockets, trace output on stdout).
# Usage: tools/desktop-client.sh <username> <password>
#   logs: output/desktop-client/ruffle.log
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB="http://127.0.0.1"
RUFFLE="$ROOT/output/ruffle-desktop/ruffle.exe"
LOGDIR="$ROOT/output/desktop-client"
mkdir -p "$LOGDIR"
[ -x "$RUFFLE" ] || { echo "missing $RUFFLE (see output/ruffle-desktop)"; exit 1; }
USER="${1:-}"; PASS="${2:-}"
[ -n "$USER" ] && [ -n "$PASS" ] || { echo "usage: $0 <username> <password>"; exit 1; }

JAR="$LOGDIR/cookies.txt"; rm -f "$JAR"
echo "=== login via supplied AccountHandler.php"
LOGIN_OUT=$(curl -s -c "$JAR" -b "$JAR" --data-urlencode "Action=Login" \
  --data-urlencode "uName=$USER" --data-urlencode "uPas=$PASS" \
  "$WEB/AjaxRequest/AccountHandler.php")
echo "login says: $LOGIN_OUT"
echo "=== fetch Gamelogin.php flashvars (session gate + signed uid/t/sign)"
curl -s -b "$JAR" "$WEB/Gamelogin.php" -o "$LOGDIR/gamelogin.html"
grep -q "Main.swf" "$LOGDIR/gamelogin.html" \
  || { echo "Gamelogin gate refused (bad login?)"; head -c 300 "$LOGDIR/gamelogin.html"; echo; exit 1; }

PARAMS="$LOGDIR/flashvars.args"
python3 "$ROOT/tools/parse_flashvars.py" "$LOGDIR/gamelogin.html" "$PARAMS"
echo "flashvars: $(wc -l < "$PARAMS") params"
mapfile -t PARGS < "$PARAMS"
# Defensive: strip any CR so values never carry \r (breaks host lookup).
PARGS=("${PARGS[@]%$'\r'}")
echo "=== starting Ruffle desktop: $WEB/res/Main.swf (log: $LOGDIR/ruffle.log)"
# --tcp-connections allow: the game opens raw sockets to ip:sport; without this
# Ruffle pops a permission dialog per attempt (and re-asks in a loop).
"$RUFFLE" --tcp-connections allow --base "$WEB/res/" "$WEB/res/Main.swf" "${PARGS[@]}" \
  >"$LOGDIR/ruffle.log" 2>&1
echo "ruffle exited: $?"
