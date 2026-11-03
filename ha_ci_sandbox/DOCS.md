# HA CI Sandbox

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

## Multiple instances

With `instances: N`, the add-on starts N copies of the launcher, each in its
own network namespace (so each may bind port 8080) with its own persistent
storage. The launcher always sees `/data/work` and `/data/hub`; for instance
N > 1 those are bind mounts of `/data/work-N` and `/data/hub-N`. Instance N is
reached on container port 8080+N-1; map the ports you need in the add-on's
Network section. Each instance runs the startup self-test on its own port.

### Different versions and saved data

Use `instance_profiles` to select a bundle and persistent data profile for an
individual instance. For example, keep the current instance unchanged and run
another version alongside it:

```yaml
instances: 2
bundle_dir: /share/ha-ci-sandbox
instance_profiles:
  - instance: 2
    profile: preview-v2
    bundle_dir: /share/app-preview-v2
```

Instance 1 keeps its existing database. Instance 2 uses the selected bundle
and a new database in `/data/profiles/preview-v2/instance-2/hub`. The launcher
still sees `/data/hub` and `/data/work`. Profile names allow letters, digits,
underscores and hyphens (1–64 characters, starting with a letter or digit).

Restart the add-on after changing profiles or bundles; this restarts every
instance. Choose a different profile when trying another version to give it
fresh data. Returning to the previous profile and instance number reuses that
profile's saved data. Removing an entry returns that instance to its original
storage; it does not delete the named profile. No database is copied or migrated
automatically. Even when two instances use the same profile name, they keep
separate databases.

Each entry may instead supply `bundle_url` and `bundle_sha256`. Downloads for
named profiles are cached separately by source and checksum; changing either
selects a new cache on restart. An explicit bundle source does not fall back to
the shared bundle or shared download URL. A profile with no source overrides
inherits the global bundle settings. Download or checksum failures leave only
that instance waiting for its bundle; other instances can still start. Restart
to retry a failed download. A missing directory bundle waits for it to appear.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `instances` | `1` | How many independent copies of the application to run (1-8). Instance N listens on container port 8080+N-1 (map the port in the Network section) and keeps its own storage, so all instances share one bundle but nothing else. |
| `instance_profiles` | `[]` | Per-instance overrides: `instance`, `profile`, and optional `bundle_dir`, `bundle_url`, `bundle_sha256`. Unlisted instances keep the original shared bundle and existing data paths. |
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
