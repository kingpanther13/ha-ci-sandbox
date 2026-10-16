# HA CI Sandbox

A Home Assistant add-on repository with one add-on, **HA CI Sandbox**, which
runs a JVM application bundle in a network-isolated sandbox: reachable from
your LAN on one port, able to reach only an allow-list of hostnames over
HTTPS, and nothing else.

## Install

1. In Home Assistant go to **Settings → Add-ons → Add-on store → ⋮ →
   Repositories** and add `https://github.com/kingpanther13/ha-ci-sandbox`.
2. Install **HA CI Sandbox**. The image is built on your machine (amd64 only).
3. Put a bundle in `/share/ha-ci-sandbox/` (or set `bundle_url`), then start
   the add-on. See `docs/BUNDLE.md` for what a bundle is.

The add-on's documentation tab describes the options, the sandbox and the
startup self-test.

## Second instance

`ha_ci_sandbox_2` is an identical copy with its own slug, storage and default
bundle directory (`/share/ha-ci-sandbox-2`), so two sandboxes can run side by side.
Keep the two folders in sync when changing the add-on.
