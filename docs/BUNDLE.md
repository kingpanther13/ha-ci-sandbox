# Bundle contract

A bundle is a directory with exactly this shape:

```
app.jar
launcher/
  start.sh
```

Anything else in the directory is copied along and available to the launcher.

## `launcher/start.sh`

- Must be executable. It is run with the bundle's copy as the working
  directory (`/data/work`), so `./app.jar` and `./launcher/...` are relative
  paths.
- Receives the add-on option `java_opts` in the `JAVA_OPTS` environment
  variable. `java` (JDK 11) is on `PATH`.
- Must serve HTTP on port 8080, bound to `127.0.0.1` or `0.0.0.0`. That port
  is what LAN port 8080 is relayed to.
- Should run in the foreground. When it exits, the add-on logs the exit code
  and idles until restarted.

## Network, as seen by the application

- `/etc/hosts` contains `localhost` and one loopback alias per allowed
  hostname. `/etc/resolv.conf` is empty: no other name resolves.
- Connecting to an allowed hostname on port 443 reaches the real host (plain
  TCP relay; TLS is end to end, so certificates validate normally).
- Any other port, host or IP address is unreachable (`ENETUNREACH` /
  resolution failure).

## Delivery

- **Share directory:** copy the bundle to the path in `bundle_dir`
  (default `/share/ha-ci-sandbox`). Checked on every start and every 30 s
  while waiting.
- **Tarball:** set `bundle_url` to a `.tar.gz` of the layout above (a single
  top-level directory wrapping it is also accepted). Downloaded once to the
  add-on's private storage; set `bundle_sha256` to have it verified first.
  Only used when no bundle exists in either location.

The share copy is read-only to the add-on; the launcher runs on a writable
copy under `/data/work`, recreated from the source on every start.
