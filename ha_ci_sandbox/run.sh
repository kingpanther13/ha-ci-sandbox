#!/usr/bin/env bash
# Outer supervisor: reads options, fetches the bundle if asked, starts the
# relays that bridge the sandbox to the outside, then launches one inner.sh per
# instance, each in its own network + mount namespace. Everything an instance
# can reach goes through the Unix sockets in /run/sb.
set -euo pipefail

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] [run] $*"; }

OPTS=/data/options.json
BUNDLE_DIR=$(jq -r '.bundle_dir // "/share/ha-ci-sandbox"' "$OPTS")
BUNDLE_URL=$(jq -r '.bundle_url // empty' "$OPTS")
BUNDLE_SHA=$(jq -r '.bundle_sha256 // empty' "$OPTS")
JAVA_OPTS=$(jq -r '.java_opts // empty' "$OPTS")
LOG_LEVEL=$(jq -r '.log_level // "info"' "$OPTS")
INSTANCES=$(jq -r '.instances // 1' "$OPTS")
mapfile -t RAW_HOSTS < <(jq -r '.allowed_hosts[]? // empty' "$OPTS")

[ "$LOG_LEVEL" = "debug" ] && set -x

# Operator notes (the `notes` option) are echoed first so anyone reading this
# log knows what the bundle is and how to reach it.
NOTES=$(jq -r '.notes // empty' "$OPTS")
if [ -n "$NOTES" ]; then
    echo "==================== OPERATOR NOTES ===================="
    printf '%s\n' "$NOTES"
    echo "========================================================"
fi

case "$INSTANCES" in
    [1-8]) ;;
    *) log "instances must be 1..8 (got '$INSTANCES'); using 1"; INSTANCES=1 ;;
esac

has_bundle() { [ -f "$1/app.jar" ] && [ -f "$1/launcher/start.sh" ]; }

# Only plain DNS names are accepted (they end up in the hosts file and in socat
# addresses); duplicates are dropped.
HOSTS=()
for h in "${RAW_HOSTS[@]}"; do
    h=${h,,}
    if [[ ! "$h" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]]; then
        log "Ignoring invalid allowed_hosts entry: '$h'"
        continue
    fi
    dup=0
    for e in "${HOSTS[@]}"; do [ "$e" = "$h" ] && dup=1; done
    [ "$dup" = 1 ] || HOSTS+=("$h")
done

mkdir -p /run/sb /data
rm -f /run/sb/*.sock /run/sb/selftest-* /run/sb/hosts

# Optional download path: only used when neither bundle location is populated.
# Failures here are logged, not fatal: the sandbox still starts and waits.
if ! has_bundle "$BUNDLE_DIR" && ! has_bundle /data/bundle && [ -n "$BUNDLE_URL" ]; then
    log "No bundle present; downloading ${BUNDLE_URL%%\?*}"
    if ! curl -fsSL --retry 3 -o /data/bundle.tar.gz "$BUNDLE_URL"; then
        log "Download failed; continuing without a bundle"
        rm -f /data/bundle.tar.gz
    fi
    if [ -f /data/bundle.tar.gz ] && [ -n "$BUNDLE_SHA" ]; then
        echo "$BUNDLE_SHA  /data/bundle.tar.gz" | sha256sum -c - \
            || { log "Checksum mismatch for downloaded bundle; refusing it"; rm -f /data/bundle.tar.gz; }
    fi
    if [ -f /data/bundle.tar.gz ]; then
        rm -rf /data/bundle && mkdir -p /data/bundle
        tar -xzf /data/bundle.tar.gz -C /data/bundle || log "Could not extract the downloaded archive"
        rm -f /data/bundle.tar.gz
        # Accept a tarball whose content sits in one top-level directory.
        if ! has_bundle /data/bundle; then
            inner=$(find /data/bundle -mindepth 1 -maxdepth 1 -type d | head -n1 || true)
            if [ -n "$inner" ] && has_bundle "$inner"; then
                mv "$inner"/* /data/bundle/ && rmdir "$inner"
            fi
        fi
        has_bundle /data/bundle && log "Bundle extracted to /data/bundle" \
            || log "Downloaded archive does not contain app.jar and launcher/start.sh"
    fi
fi

# One loopback alias per allowed host; the sandbox resolves names only through
# this file, and only these aliases have a listener behind them.
{
    echo "127.0.0.1 localhost $(hostname)"
    i=11
    for h in "${HOSTS[@]}"; do
        echo "127.0.0.$i $h"
        i=$((i + 1))
    done
} > /run/sb/hosts
: > /run/sb/resolv.conf

# Outside egress relays, shared by all instances: plain TCP passthrough to
# <host>:443, so TLS is negotiated end to end between the application and the
# real host.
i=11
for h in "${HOSTS[@]}"; do
    socat "UNIX-LISTEN:/run/sb/egress-$i.sock,fork,unlink-early" "TCP:$h:443" &
    log "Egress relay: $h via 127.0.0.$i"
    i=$((i + 1))
done

# Outside ingress relays: one container port per instance (8080, 8081, ...)
# -> that instance's Unix socket -> its inside relay -> the app on 8080.
for n in $(seq 1 "$INSTANCES"); do
    port=$((8080 + n - 1))
    socat "TCP-LISTEN:$port,fork,reuseaddr" "UNIX-CONNECT:/run/sb/ingress-$n.sock" &
    log "Instance $n: ingress relay on container port $port"
done

# Ingress half of the self-test, per instance: inner.sh serves a tiny HTTP page
# on its 8080 and signals readiness; we fetch it through the instance's port.
for n in $(seq 1 "$INSTANCES"); do
    (
        port=$((8080 + n - 1))
        for _ in $(seq 1 120); do
            [ -f "/run/sb/selftest-ready-$n" ] && break
            sleep 1
        done
        if [ -f "/run/sb/selftest-ready-$n" ]; then
            code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$port/" || true)
            if [ "$code" = "200" ]; then
                log "Instance $n self-test ingress: OK (HTTP 200 through port $port)"
            else
                log "Instance $n self-test ingress: FAILED (got '$code' through port $port)"
            fi
        else
            log "Instance $n self-test ingress: skipped (sandbox never signalled readiness)"
        fi
        touch "/run/sb/selftest-done-$n"
    ) &
done

export BUNDLE_DIR JAVA_OPTS LOG_LEVEL

# On stop, hand SIGTERM to every inner.sh (each forwards it to its launcher) so
# the applications can shut down cleanly before Supervisor's kill timeout.
stopping=0
on_term() {
    stopping=1
    log "Stop requested; terminating all instances"
    # Target the bash processes running inner.sh (cmdline "bash /inner.sh"), not the unshare parents.
    pkill -TERM -f 'bash /inner.sh' 2>/dev/null || true
}
trap on_term TERM INT

PIDS=()
for n in $(seq 1 "$INSTANCES"); do
    log "Starting sandbox namespace for instance $n"
    INSTANCE=$n unshare --net --mount --fork --propagation private /inner.sh &
    PIDS+=("$!")
done

rc=0
for p in "${PIDS[@]}"; do
    wait "$p" || rc=$?
done
if [ "$stopping" = 1 ]; then
    log "All instances stopped (last code $rc)"
    exit 0
fi
log "All instances exited (last code $rc); container stays up so logs remain readable. Restart the add-on to run again."
trap 'exit 0' TERM INT
sleep infinity &
wait $!
