#!/bin/bash
# Original DNTG stack in one command: MySQL5 + Java game server + Apache/PHP,
# serving the SUPPLIED client files from ESSamp/wwwroot (/res/Main.swf).
# No Vite, no dist client, no Python server. Logs under output/orig-stack/.
# Usage: tools/orig-stack.sh up|down|status   (BRIDGE=0 to skip the WS shim)
#
# NOTE on the bridge: browsers cannot open raw TCP sockets, so the Flash
# client's socket to 127.0.0.1:8008 is forwarded through a byte-transparent
# WS->TCP shim on :8181 (tools/bridge, websockify-compatible). It only swaps
# the transport; the SWF, the protocol and the packets are untouched and the
# game server stays 100% Java. Ruffle is served by Apache itself via an
# Alias to client/public/ruffle/ (no copies, no Vite).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRV="$ROOT/TonNgoKhong/server"
LOGDIR="$ROOT/output/orig-stack"
MYSQL="$SRV/ESSamp/MySQL5/bin/mysqld.exe"
MYSQLADMIN="$SRV/ESSamp/MySQL5/bin/mysql.exe"
JAVA="$SRV/jre6/bin/java.exe"
HTTPD="$SRV/ESSamp/Apache2/bin/httpd.exe"
BRIDGE="${BRIDGE:-1}"
mkdir -p "$LOGDIR"

pid_on_port() { netstat -ano 2>/dev/null | grep -E "LISTENING" | grep -E ":$1 " | awk '{print $NF}' | sort -u | head -1; }
kill_port() {
  local p; p="$(pid_on_port "$1")"
  if [ -n "$p" ]; then echo "stopping PID $p on :$1"; taskkill //F //PID "$p" >/dev/null 2>&1; sleep 2; fi
}
wait_port() { # $1=port $2=timeout_s $3=name
  local t=0
  while [ -z "$(pid_on_port "$1")" ]; do
    sleep 2; t=$((t+2))
    if [ "$t" -ge "$2" ]; then echo "TIMEOUT waiting for $3 (:$1)"; tail -n 15 "$LOGDIR/$3.log"; return 1; fi
  done
  echo "$3 up on :$1 (${t}s)"; return 0
}
case "${1:-}" in
  up) ;;
  down)
    for svc in bridge apache java mysql; do
      if [ -f "$LOGDIR/$svc.pid" ]; then taskkill //F //PID "$(cat "$LOGDIR/$svc.pid")" >/dev/null 2>&1; rm -f "$LOGDIR/$svc.pid"; fi
    done
    "$SRV/ESSamp/MySQL5/bin/mysqladmin.exe" -uroot -p123456 shutdown >/dev/null 2>&1
    echo "original stack stopped"; exit 0 ;;
  status)
    for p in 3306 8008 80 8181; do echo ":$p -> PID $(pid_on_port $p || echo -)"; done; exit 0 ;;
  *) echo "usage: $0 up|down|status   (env: BRIDGE=0|1, default 1)"; exit 1 ;;
esac

echo "=== stopping stray listeners so the original daemons own their ports"
kill_port 8008; kill_port 8080; kill_port 5173; kill_port 8181; kill_port 80

echo "=== 1/4 MySQL5 (bundled data: caonima + dntg)"
"$MYSQL" --basedir="$SRV/ESSamp/MySQL5" --datadir="$SRV/ESSamp/MySQL5/data" --port=3306 >"$LOGDIR/mysql.log" 2>&1 &
echo $! >"$LOGDIR/mysql.pid"
wait_port 3306 60 mysql || exit 1
if "$MYSQLADMIN" -uroot -p123456 -e "SELECT 1" >/dev/null 2>&1; then
  echo "mysql auth ok (root/123456)"
elif "$MYSQLADMIN" -uroot -e "SELECT 1" >/dev/null 2>&1; then
  echo "root has empty password -> setting to 123456 for the Java server"
  "$SRV/ESSamp/MySQL5/bin/mysqladmin.exe" -uroot password 123456 >>"$LOGDIR/mysql.log" 2>&1
else
  echo "WARN: cannot auth to mysql as root (empty or 123456); Java may fail - check $LOGDIR/mysql.log"; fi

echo "=== 2/4 Java game server (jre6 + dntg_start.jar, per server.bat)"
cd "$SRV"
"$JAVA" -server -Xms256m -Xmx1024m -XX:PermSize=128M -XX:MaxPermSize=256M -jar dntg_start.jar >"$LOGDIR/java.log" 2>&1 &
echo $! >"$LOGDIR/java.pid"
cd "$ROOT"
wait_port 8008 240 java || exit 1

echo "=== 3/4 Apache+PHP (conf repointed from D:/TonNgoKhong to this tree)"
WIN_SRV="$(cygpath -m "$SRV")"
WIN_RUFFLE="$(cygpath -m "$ROOT/client/public/ruffle")"
if [ ! -f "$ROOT/client/public/ruffle/ruffle.js" ]; then
  echo "WARN: client/public/ruffle/ruffle.js missing - run 'npm install' in client/ (predev stages Ruffle); /ruffle will 404 until then"
fi
sed "s|D:/TonNgoKhong/server|$WIN_SRV|g; s|D:/TonNgoKhong|$WIN_SRV|g" "$SRV/ESSamp/Apache2/conf/httpd.conf" >"$LOGDIR/httpd.conf"
# Correct WASM MIME (Ruffle instantiateStreaming needs application/wasm).
cat >>"$LOGDIR/httpd.conf" <<EOF
AddType application/wasm .wasm
EOF
# Access log for the swap-chain trace (which SWF/data URL loads, in order).
cat >>"$LOGDIR/httpd.conf" <<EOF
CustomLog "$LOGDIR/access.log" common
EOF
# Serve the Ruffle runtime from Apache itself (no Vite, no copies).
cat >>"$LOGDIR/httpd.conf" <<EOF

# --- orig-stack: Ruffle runtime for the supplied Flash client ---
Alias /ruffle "$WIN_RUFFLE"
<Directory "$WIN_RUFFLE">
  Options Indexes FollowSymLinks
  AllowOverride None
  Order allow,deny
  Allow from all
</Directory>
EOF
"$HTTPD" -f "$LOGDIR/httpd.conf" -X >"$LOGDIR/apache.log" 2>&1 &
echo $! >"$LOGDIR/apache.pid"
wait_port 80 60 apache || { echo "Apache failed - PHP login pages unavailable (game server still up)"; }

if [ "$BRIDGE" = "1" ]; then
  echo "=== 4/4 WS->TCP socket shim :8181 (transport only, game stays Java)"
  cd "$ROOT/tools/bridge"
  # LOG_PACKETS=1: hex-dump every frame (length + first bytes) so the
  # socket traffic is visible in bridge.log. Payloads are encrypted or
  # session-scoped; never commit this log.
  (LOG_PACKETS=1 node bridge.js >"$LOGDIR/bridge.log" 2>&1 & echo $! >"$LOGDIR/bridge.pid")
  cd "$ROOT"
  wait_port 8181 30 bridge || exit 1
else
  echo "=== 4/4 bridge skipped (BRIDGE=0): browser play unavailable, raw-TCP probes only"
fi

echo; echo "ORIGINAL STACK UP  (logs: $LOGDIR)"
echo "1. login in your own browser:  http://127.0.0.1/UserCenter/Login.php  (e.g. 111111/111111)"
echo "2. play the supplied client:   http://127.0.0.1/RuffleGamelogin.php  (same /res/Main.swf Gamelogin.php embeds)"
echo "3. monitor: tail -F $LOGDIR/*.log   |   stop: tools/orig-stack.sh down"
