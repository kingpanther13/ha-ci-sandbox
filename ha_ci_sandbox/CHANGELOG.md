# Changelog

## 0.2.0

- New `instances` option (1-8): run several independent copies of the
  application from one bundle, each in its own namespace with its own storage,
  on container ports 8080, 8081, ...

## 0.1.2

- New `notes` option: free text shown in the configuration tab and printed at
  the top of the add-on log on every start.

## 0.1.1

- A failed bundle download no longer stops the add-on; it logs and waits.
- `allowed_hosts` entries are validated as DNS names and de-duplicated.
- Stopping the add-on sends SIGTERM to the launcher instead of killing it.
- The download URL is logged without its query string.
- The container hostname resolves to 127.0.0.1 inside the sandbox.

## 0.1.0

- Initial release: network-isolated JVM bundle runner with inbound relay on
  port 8080, allow-listed HTTPS egress relays, and a startup self-test.
