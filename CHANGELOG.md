# Changelog

## Unreleased

### Added

**Web portal command fallback.** When the command socket cannot be opened,
the cloud (`IntesisHome`) controller now sends SETs the way the
accloud.intesis.com web portal does: a form login over HTTPS followed by
`POST /device/setVal` with the same uid/value datapoints the socket protocol
uses. Motivated by the August 2026 outage, where the socket server was
unreachable for days while both the HTTP API and the portal kept working
([hass-intesishome#68](https://github.com/jnimmo/hass-intesishome/issues/68)),
leaving the integration read-only. The portal session lives in its own
`aiohttp` session (closed by `stop()`), logs in lazily on first use, and
retries once with a fresh login when its session expires. Normal socket
operation resumes automatically as soon as the socket can be opened again.

**Bounded socket connect (`SOCKET_CONNECT_TIMEOUT`, 5s).** Opening the
command socket previously paid a full kernel TCP timeout (~130s) when the
port was filtered, and every SET waited it out before failing. The attempt
is now capped, so commands fall back (or fail) in seconds.

## 2.3.0

Reworks the cloud (`IntesisHome`) controller so that state comes from HTTPS
polling, and the TCP socket is opened only by commands rather than held open
permanently. While a socket is open it still carries status pushes, and
polling stands down for the duration. This fixes the availability flapping
reported in
[hass-intesishome#50](https://github.com/jnimmo/hass-intesishome/issues/50),
where entities went unavailable every time the socket timed out even though
the REST endpoint remained perfectly healthy.

### Breaking changes

**`connect()` no longer opens the socket.** It authenticates, loads state and
starts the poller. The socket is opened lazily by the first command. Start-up
therefore no longer depends on outbound access to the cloud's high port.

**`is_connected` is now `False` in normal operation.** It reports raw socket
state, and the socket only exists around commands. Consumers that gate entity
availability on it will show everything as unavailable.

> Migrate to **`is_available`** (new in this release), which is true when a
> recent poll succeeded *or* a socket is up. This is the property to gate
> availability on.

**Automatic reconnection has been removed.** A dropped socket is no longer an
error to recover from: polling continues to carry state, and the next command
opens a fresh socket. `_reconnect_loop` and the backoff settings are gone.

### Added

- `is_available` — whether the controller has a working path to the device.
- `use_socket` (default `True`) — set `False` to never open a socket, making
  the controller read-only.
- `poll_interval` (default `120`, floor `60`) — seconds between state polls.
  Pass `0`/`None` to disable polling.

### Changed

- Polling stands down while a socket is up, so a healthy socket costs no extra
  API traffic. The keepalive bounds how long a half-dead socket can suppress
  polling, and a disconnect triggers an immediate poll so availability does not
  dip in the gap.
- `poll_status()` now fires one update callback per device rather than only for
  the last device in the status list, so multi-device installations no longer
  leave devices showing stale state.
- `poll_status()` is serialised, so a poll can no longer consume the single-use
  socket token that a concurrent connect is about to present.
- `poll_status()` tolerates a response with no `config` block.
- A poll that returns no device state no longer counts as a successful update.
  An account whose devices are all offline answers `200` with an empty status
  list; treating that as success pinned availability true while serving state
  that never refreshed.

### Added (diagnostics)

- `examples/probe_cloud_set.py` — standalone, dependency-free probe for whether
  the cloud HTTPS API accepts writes. See its header for findings to date.
