#!/usr/bin/env bash
# Runs inside the sandbox namespaces (own network stack with loopback only,
# private mount namespace). Wires the inside half of the relays, proves the
# isolation with a self-test, then waits for a bundle and runs its launcher.
set -euo pipefail

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] [sandbox] $*"; }

[ "${LOG_LEVEL:-info}" = "debug" ] && set -x
BUNDLE_DIR=${BUNDLE_DIR:-/share/ha-ci-sandbox}

has_bundle() { [ -f "$1/app.jar" ] && [ -f "$1/launcher/start.sh" ]; }

ip link set lo up
mount --bind /run/sb/hosts /etc/hosts
mount --bind /run/sb/resolv.conf /etc/resolv.conf

# Inside egress listeners: 127.0.0.N:443 -> Unix socket -> outside relay.
HOSTS=()
while read -r ip host; do
    [ "$ip" = "127.0.0.1" ] && continue
    n=${ip##*.}
    socat "TCP-LISTEN:443,bind=$ip,fork,reuseaddr" "UNIX-CONNECT:/run/sb/egress-$n.sock" &
    HOSTS+=("$host")
done < /run/sb/hosts

# Inside ingress listener: Unix socket -> the application's port 8080.
socat "UNIX-LISTEN:/run/sb/ingress.sock,fork,unlink-early" "TCP:127.0.0.1:8080" &
sleep 1

# ---- self-test -------------------------------------------------------------
ok() { log "Self-test $1: OK"; }
bad() { log "Self-test $1: FAILED ($2)"; }

for h in "${HOSTS[@]}"; do
    r=$(getent hosts "$h" | awk '{print $1}' || true)
    case "$r" in
        127.0.0.*) ok "resolve $h -> $r" ;;
        *) bad "resolve $h" "got '$r'" ;;
    esac
done

if [ "${#HOSTS[@]}" -gt 0 ]; then
    first=${HOSTS[0]}
    if curl -sS -o /dev/null --max-time 20 "https://$first/" 2>/tmp/curl.err; then
        ok "egress TLS to $first"
    else
        bad "egress TLS to $first" "$(tr -d '\n' < /tmp/curl.err)"
    fi
fi

if curl -s -o /dev/null --max-time 8 https://example.com/ 2>/dev/null; then
    bad "unlisted host blocked" "example.com was reachable"
else
    ok "unlisted host blocked"
fi

if curl -s -o /dev/null --max-time 8 http://1.1.1.1/ 2>/dev/null; then
    bad "direct IP blocked" "1.1.1.1 was reachable"
else
    ok "direct IP blocked"
fi

# Ingress half: serve a page on 8080 and let the outer script fetch it.
echo "ha-ci-sandbox self-test" > /run/sb/index.html
python3 -m http.server 8080 --bind 127.0.0.1 --directory /run/sb >/dev/null 2>&1 &
http_pid=$!
sleep 1
touch /run/sb/selftest-ready
for _ in $(seq 1 30); do
    [ -f /run/sb/selftest-done ] && break
    sleep 1
done
kill "$http_pid" 2>/dev/null || true
wait "$http_pid" 2>/dev/null || true
rm -f /run/sb/index.html
log "Self-test finished"

# ---- bundle ------------------------------------------------------------------
SRC=""
while true; do
    if has_bundle "$BUNDLE_DIR"; then SRC=$BUNDLE_DIR; break; fi
    if has_bundle /data/bundle; then SRC=/data/bundle; break; fi
    log "No bundle found at $BUNDLE_DIR (expects app.jar and launcher/start.sh). Waiting..."
    sleep 30
done

log "Using bundle from $SRC"
rm -rf /data/work
mkdir -p /data/work
cp -a "$SRC"/. /data/work/
chmod +x /data/work/launcher/start.sh
cd /data/work
export JAVA_OPTS="${JAVA_OPTS:-}"
log "Starting launcher with JAVA_OPTS='$JAVA_OPTS'"
rc=0
./launcher/start.sh || rc=$?
log "Launcher exited with code $rc"
exit "$rc"
