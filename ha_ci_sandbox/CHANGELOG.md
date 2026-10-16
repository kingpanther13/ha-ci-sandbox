# Changelog

## 0.1.1

- A failed bundle download no longer stops the add-on; it logs and waits.
- `allowed_hosts` entries are validated as DNS names and de-duplicated.
- Stopping the add-on sends SIGTERM to the launcher instead of killing it.
- The download URL is logged without its query string.
- The container hostname resolves to 127.0.0.1 inside the sandbox.

## 0.1.0

- Initial release: network-isolated JVM bundle runner with inbound relay on
  port 8080, allow-listed HTTPS egress relays, and a startup self-test.
