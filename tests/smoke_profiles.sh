#!/usr/bin/env bash
set -euo pipefail
root=$(mktemp -d)
name="sandbox-profile-test-$$"
cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
    rm -rf -- "$root"
}
trap cleanup EXIT
mkdir -p "$root/data" "$root/share/main/launcher" "$root/share/preview/launcher"
cp tests/fixtures/launcher/* "$root/share/main/launcher/"
cp tests/fixtures/launcher/* "$root/share/preview/launcher/"
echo version-one > "$root/share/main/app.jar"
echo version-two > "$root/share/preview/app.jar"
configure() {
    cat > "$root/data/options.json" <<EOF
{"instances":2,"allowed_hosts":[],"bundle_dir":"/share/main",
 "instance_profiles":[{"instance":2,"profile":"$1","bundle_dir":"/share/preview"}]}
EOF
}
start() {
    docker run -d --name "$name" --cap-add SYS_ADMIN --cap-add NET_ADMIN \
        --security-opt apparmor=unconfined \
        -v "$root/data:/data" -v "$root/share:/share:ro" \
        -p 127.0.0.1:18080:8080 -p 127.0.0.1:18081:8081 sandbox-profile-test >/dev/null
}
expect() {
    local port=$1 version=$2 starts=$3
    for _ in $(seq 1 90); do
        if curl -fsS --max-time 2 "http://127.0.0.1:$port/" 2>/dev/null \
            | jq -e --arg v "$version" --argjson n "$starts" '.version == $v and .starts == $n' >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    docker logs "$name"
    echo "Expected $version with $starts starts on port $port" >&2
    return 1
}
stop() { docker stop -t 10 "$name" >/dev/null; docker rm "$name" >/dev/null; }
configure preview-v2
start
expect 18080 version-one 1
expect 18081 version-two 1
stop
start
expect 18080 version-one 2
expect 18081 version-two 2
stop
configure preview-fresh
start
expect 18080 version-one 3
expect 18081 version-two 1
stop
configure preview-v2
start
expect 18080 version-one 4
expect 18081 version-two 3
echo 'Profile switching, restart persistence, and legacy database isolation passed.'
