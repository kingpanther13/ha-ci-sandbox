# HA CI Sandbox 2

Runs a JVM application bundle inside a sandbox that has no network access of
its own. The application can be reached from your LAN on one port, and it can
reach a short allow-list of hostnames over HTTPS. Nothing else resolves or
connects.

## How it works

- The application runs in its own network namespace with only a loopback
  interface, and in a private mount namespace.
- Inbound: LAN port 8080 is relayed over a Unix socket into the sandbox, to
  the application's port 8080.
- Outbound: each allowed hostname is given a loopback alias (127.0.0.11,
  127.0.0.12, ...) in the sandbox's private `/etc/hosts`. A listener on that
  alias relays raw TCP to `<hostname>:443` outside the sandbox. TLS is
  negotiated end to end between the application and the real host; the add-on
  never terminates or inspects it.
- DNS is disabled inside the sandbox (empty `resolv.conf`), so only the
  aliases resolve.

## Bundle

The add-on does nothing until a bundle is present. A bundle is a directory
containing:

- `app.jar` — the application
- `launcher/start.sh` — an executable script that starts it (see the
  repository's `docs/BUNDLE.md` for the contract)

Provide it in one of two ways:

1. Copy it to the `share` folder at the path set by `bundle_dir`
   (default `/share/ha-ci-sandbox`).
2. Set `bundle_url` to a `.tar.gz` of the same layout; it is downloaded once
   into the add-on's private storage. Set `bundle_sha256` to have the download
   verified.

The bundle is copied to a writable work directory inside the add-on before the
launcher runs, so the `share` copy is never modified.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `bundle_dir` | `/share/ha-ci-sandbox` | Directory on the share holding the bundle |
| `bundle_url` | unset | Optional tarball to download when no bundle is present |
| `bundle_sha256` | unset | Optional SHA-256 of that tarball |
| `allowed_hosts` | GitHub hostnames | Hostnames the application may reach on port 443 |
| `java_opts` | `-Xms336m -Xmx336m ...` | Passed to the launcher as `JAVA_OPTS` |
| `log_level` | `info` | `debug` traces every shell command |
| `notes` | unset | Free text for operators (what the bundle is, how to reach it). Printed at the top of the add-on log on every start. |

## Startup self-test

On every start the add-on checks, from inside the sandbox, that each allowed
host resolves to its alias, that a TLS connection to the first allowed host
succeeds through the relay, that an unlisted host and a direct IP are
unreachable, and that port 8080 is reachable from outside. Results are in the
add-on log as `Self-test ...: OK` or `FAILED`.

## Lifecycle

If the launcher exits, the container stays up so the log remains readable;
restart the add-on to run again. The add-on is `boot: manual` and does not
start with Home Assistant.
