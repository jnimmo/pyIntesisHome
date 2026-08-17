"""Probe whether the IntesisHome / AC Cloud API accepts writes over HTTPS.

pyIntesisHome sends commands over a TCP socket on port 5210. If the HTTPS
API also accepted them, firewalled setups would stop being read-only. No
such write command is documented; this tests the plausible candidates.

Two checks, since either alone can mislead:

1. Echo. The API mirrors back any section name, including invented ones,
   so a section appearing in the response means nothing. A candidate
   echoing identically to an invented control section was not understood.
2. Effect. Read, write, wait, re-read. Only a real change proves a write.

Check 2 needs a device connected to the cloud. It need not be running - a
unit switched off still reports state and accepts setpoint changes. With
nothing reporting, a failed write is indistinguishable from an
unsupported one, so the script stops instead of guessing.

Writes: setpoint +/-1 degree, restored in a finally block. Nothing else
is touched. Stays within the reported setpoint range, since the cloud
would clamp an out-of-range write and a clamp looks like an ignore.

Output is anonymised (device#1, etc.) and safe to post. Local-only detail
goes to stderr, so `> result.txt` captures just the postable result.

Usage:
    INTESIS_USER=... INTESIS_PASS=... python3 probe_cloud_set.py
    ... python3 probe_cloud_set.py --brand airconwithme --device <id>

Status 2026-08-17, from live runs against one account:

  * Dispatch is entirely on the `cmd` parameter, which is a map of
    section names. Unknown sections are echoed back as {"": ""} stubs -
    never an error - so a section appearing in a response is meaningless.
  * A JSON request body is ignored outright: sending the local api.cgi
    envelope {"command": ..., "data": ...} as the body, with credentials
    in the query string, returns [] (no sections requested).
  * That same envelope inside `cmd` is read as two sections named
    "command" and "data", and stubbed like any other unknown section.
  * /api.php/set/control returns HTTP 404.
  * Matches a capture of AC Cloud iOS 3.3.3, which issued only reads when
    toggling power.

So check 1 is a consistent negative. Check 2 remains unrun against real
hardware - the account available reports 34 datapoints, all
configuration descriptors, so it has nothing writable. The
write/restore path is simulation-tested only, hence the prompt.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# stdlib-only: this gets handed to strangers, and an aiohttp dependency
# would cost more testers than async buys.

BRANDS = {
    "intesishome": "https://user.intesishome.com/api.php/get/control",
    "airconwithme": "https://user.airconwithme.com/api.php/get/control",
    "anywair": "https://anywair.intesishome.com/api.php/get/control",
}

READ_CMD = {"status": {"hash": "x"}, "config": {"hash": "x"}}

SETPOINT_UID = 9
SETPOINT_MIN_UID = 35
SETPOINT_MAX_UID = 36
CONTROL_SECTION = "nosuchsectionplease"

INTESIS_NULL = 32768  # "unavailable"; common on a switched-off unit
STEP = 10  # tenths of a degree

# Live-operation datapoints. A device reporting none of these exposes
# only descriptors and has nothing writable.
OPERATIONAL_UIDS = {1, 2, 4, 5, 6, 9, 10, 37, 42}

SETTLE_SECONDS = 4.0  # API reports setDelay 0.7; margin for the round trip

UID_NAMES = {
    1: "power",
    2: "mode",
    4: "fan_speed",
    5: "vane_vertical",
    6: "vane_horizontal",
    9: "setpoint",
    10: "temperature",
    13: "working_hours",
    14: "alarm_status",
    15: "error_code",
    35: "setpoint_min",
    36: "setpoint_max",
    37: "outdoor_temp",
    42: "climate_working_mode",
    50000: "external_led",
    60002: "rssi",
}


# The local controller API (api.cgi) uses a different envelope to the
# cloud: a raw JSON body {"command": ..., "data": {...}} rather than a
# form field holding a map of sections. If the two share backend lineage
# the cloud may understand it. Probed with reads, which are safe and work
# even when no device is reporting.
LOCAL_READ_COMMANDS = ["getinfo", "getavailabledatapoints", "getdatapointvalue"]
LOCAL_CONTROL_COMMAND = "nosuchcommandplease"


def local(*args):
    """Print to stderr: tester-facing detail that must not be posted."""
    print(*args, file=sys.stderr)


def post(url, username, password, cmd, extra=None):
    """POST a cmd object. Returns (http_status, parsed_or_None, raw_text)."""
    fields = {
        "username": username,
        "password": password,
        "version": "3.3.3",
        "cmd": json.dumps(cmd),
    }
    fields.update(extra or {})
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(url, data=data)
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            status, text = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return None, None, f"connection failed: {exc.reason}"

    try:
        return status, json.loads(text), text
    except ValueError:
        return status, None, text


def post_json(url, payload):
    """POST a raw JSON body, as the local api.cgi expects."""
    data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return None, f"connection failed: {exc.reason}"


def probe_envelope(url, username, password):
    """Test whether the cloud understands the local API's command envelope.

    Read-only, so it is safe and needs no reporting device. Each command
    is compared against a nonsense command name sent the same way: only a
    difference indicates the envelope means anything to the server.
    """
    print("\n--- local-API envelope, via cmd= form field ---")
    control = None
    for command in [LOCAL_CONTROL_COMMAND] + LOCAL_READ_COMMANDS:
        envelope = {"command": command, "data": {"username": username}}
        status, _, text = post(url, username, password, envelope)
        shape = f"HTTP {status} {text[:120]}"
        if control is None:
            control = shape
            print(f"  {command:24} {shape}   (control)")
        else:
            same = "same as control" if shape == control else ">>> DIFFERS <<<"
            print(f"  {command:24} {shape}   {same}")

    # Credentials go in the query string, not the JSON body: the cloud
    # reads them as form fields, so a JSON body alone fails auth before
    # reaching command dispatch and every row comes back identical for
    # reasons that say nothing about the envelope.
    query = urllib.parse.urlencode(
        {"username": username, "password": password, "version": "3.3.3"}
    )
    print("\n--- local-API envelope, raw JSON body, credentials in query ---")
    control = None
    for command in [LOCAL_CONTROL_COMMAND] + LOCAL_READ_COMMANDS:
        payload = {"command": command, "data": {}}
        status, text = post_json(f"{url}?{query}", payload)
        shape = f"HTTP {status} {text[:120]}"
        if "WRONG_USERNAME_PASSWORD" in text:
            shape += "  [auth failed - this transport cannot authenticate]"
        if control is None:
            control = shape
            print(f"  {command:24} {shape}   (control)")
        else:
            same = "same as control" if shape == control else ">>> DIFFERS <<<"
            print(f"  {command:24} {shape}   {same}")


class Anonymiser:
    """Stable device id -> device#N mapping."""

    def __init__(self):
        self._seen = {}

    def __call__(self, device_id):
        device_id = str(device_id)
        if device_id not in self._seen:
            self._seen[device_id] = f"device#{len(self._seen) + 1}"
        return self._seen[device_id]


def read_state(url, username, password):
    """Return (config, {(device_id, uid): value}); exits on failure."""
    status, payload, text = post(url, username, password, READ_CMD)
    if payload is None:
        raise SystemExit(f"Could not read state (HTTP {status}): {text[:200]}")
    if "errorCode" in payload:
        raise SystemExit(
            f"API rejected the login: {payload.get('errorMessage')} "
            f"(code {payload['errorCode']})"
        )
    statuses = (payload.get("status") or {}).get("status") or []
    values = {(str(s["deviceId"]), s["uid"]): s["value"] for s in statuses}
    return payload.get("config") or {}, values


def candidates(device_id, uid, value):
    """(label, url_path_override, cmd_object) per candidate write form."""
    target = {"deviceId": device_id, "uid": uid, "value": value}
    return [
        ("cmd={'set': {...}}", None, {"set": target}),
        ("cmd={'set': [...]} list form", None, {"set": [target]}),
        ("cmd={'setdatapointvalue': {...}}", None, {"setdatapointvalue": target}),
        ("cmd={'control': {...}}", None, {"control": target}),
        ("cmd={read..., 'set': [...]}", None, {**READ_CMD, "set": [target]}),
        ("POST to /api.php/set/control", "set/control", {"set": target}),
        # Local api.cgi envelope, sent through the cloud's form field.
        (
            "cmd={'command':'setdatapointvalue','data':{...}}",
            None,
            {"command": "setdatapointvalue", "data": target},
        ),
    ]


def choose_probe_value(original, low, high):
    """Pick a setpoint one STEP from original, in range.

    Returns (value, None) or (None, reason). Prefers up; goes down if
    already at max, since an out-of-range write would be clamped and a
    clamp is indistinguishable from an ignore.
    """
    if original is None:
        return None, "the device does not report a temperature setpoint"
    if original == INTESIS_NULL:
        return None, (
            "the device reports its setpoint as unavailable (32768). This is "
            "common when the unit is switched off at the wall or the indoor "
            "unit is not communicating"
        )
    if not 0 < original < 1000:
        return (
            None,
            f"the reported setpoint ({original}) is not a plausible temperature",
        )

    up, down = original + STEP, original - STEP
    if high is None or up <= high:
        return up, None
    if low is None or down >= low:
        return down, None
    return None, (
        f"the allowed setpoint range ({low}-{high}) is too narrow to change "
        "by a degree and change back"
    )


def dump_datapoints(values, device_id, names):
    """Log what a device reports, to diagnose a skip."""
    reported = sorted(uid for (dev, uid) in values if dev == device_id)
    local(
        f"\n  [local only] {names.get(device_id, '(unnamed)')!r} reports "
        f"{len(reported)} datapoint(s):"
    )
    for uid in reported:
        local(
            f"    uid {uid:<6} {UID_NAMES.get(uid, ''):<22} = {values[(device_id, uid)]}"
        )


def device_names(config):
    """device id -> friendly name, from the config block."""
    names = {}
    for installation in config.get("inst") or []:
        for device in installation.get("devices") or []:
            names[str(device.get("id"))] = device.get("name")
    return names


def print_device_table(device_ids, names, options, anon):
    """Local-only device list, for picking one. Real names by design."""
    local("\n  [local only - not written to the postable result]")
    for device_id in device_ids:
        value, reason = options[device_id]
        state = "can be tested" if value is not None else f"cannot: {reason}"
        local(
            f"    {device_id}  {names.get(device_id, '(unnamed)')!r}"
            f"  [{anon(device_id)}]  {state}"
        )


def section_echo(payload, section):
    """What the server placed in a named response section."""
    if payload is None:
        return "<no JSON body>"
    if section not in payload:
        return "<section absent>"
    return json.dumps(payload[section])[:200]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brand", choices=sorted(BRANDS), default="intesishome")
    parser.add_argument("--device", help="device id, if the account has several")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation prompt before writing",
    )
    args = parser.parse_args()

    username = os.environ.get("INTESIS_USER")
    password = os.environ.get("INTESIS_PASS")
    if not username or not password:
        print(__doc__)
        return 1

    url = BRANDS[args.brand]
    anon = Anonymiser()

    print("=" * 68)
    print("pyIntesisHome HTTPS command probe")
    print(f"brand: {args.brand}    python: {sys.version.split()[0]}")
    print("=" * 68)

    config, values = read_state(url, username, password)
    print(
        f"\nbaseline read OK. forceUpdate={config.get('forceUpdate')!r} "
        f"lastAppVersion={config.get('lastAppVersion')!r}"
    )

    # Runs regardless of device state: it is read-only and tests whether
    # the cloud understands the local API's envelope at all.
    probe_envelope(url, username, password)

    if not values:
        print(
            "\nRESULT: INCONCLUSIVE for the write test - no device is reporting.\n"
            "\nThe account is reachable but no device on it is talking to the\n"
            "cloud, so a command that fails is indistinguishable from a command\n"
            "that was never supported.\n"
            "\nNote the unit does NOT need to be running - a unit switched off but\n"
            "still connected reports state and can have its setpoint changed, which\n"
            "is all this test needs. Please re-run when a controller is connected."
        )
        return 2

    device_ids = sorted({device_id for device_id, _ in values})
    names = device_names(config)

    # Evaluate every device, so a multi-device account isn't rejected
    # because an arbitrary first pick is the unusable one.
    options = {}
    for candidate in device_ids:
        value, reason = choose_probe_value(
            values.get((candidate, SETPOINT_UID)),
            values.get((candidate, SETPOINT_MIN_UID)),
            values.get((candidate, SETPOINT_MAX_UID)),
        )
        options[candidate] = (value, reason)

    probeable = [d for d in device_ids if options[d][0] is not None]

    if args.device:
        device_id = args.device
        if device_id not in device_ids:
            print(f"\nDevice {device_id!r} is not reporting state on this account.")
            print_device_table(device_ids, names, options, anon)
            return 1
    elif len(probeable) == 1:
        device_id = probeable[0]
    elif not probeable:
        print("\nRESULT: SKIPPED - no device on this account can be safely probed.")
        print_device_table(device_ids, names, options, anon)
        for candidate in device_ids:
            dump_datapoints(values, candidate, names)

        # Separate "script is fussy" from "nothing here is writable".
        if not any(
            uid in OPERATIONAL_UIDS for (dev, uid) in values if dev in device_ids
        ):
            print(
                "\nEvery datapoint being reported is a configuration or capability\n"
                "descriptor - there is no power, mode, fan, setpoint or temperature\n"
                "among them. That usually means the WiFi controller is online and\n"
                "describing itself, but the indoor unit behind it is not\n"
                "communicating. Nothing on this account is writable, so no probe\n"
                "could succeed here regardless of which datapoint it targeted."
            )
        else:
            print(
                "\nThis probe only ever writes to the temperature setpoint, since\n"
                "every other datapoint would be more disruptive to test on a live\n"
                "system."
            )
        return 2
    else:
        # Don't pick silently: the tester needs to know which unit moved.
        print("\nThis account has more than one device that could be tested.")
        print_device_table(device_ids, names, options, anon)
        print("\nRe-run with --device <id> to choose one.")
        return 1

    probe_value, reason = options[device_id]
    if probe_value is None:
        print(f"\nRESULT: SKIPPED - cannot safely probe this device: {reason}.")
        return 2

    original = values[(device_id, SETPOINT_UID)]
    local("\n  [local only - not written to the postable result]")
    local(f"    testing {names.get(device_id, '(unnamed)')!r} (id {device_id})")
    local(f"    it appears in the result below as {anon(device_id)}")
    if not args.yes:
        local("\n  About to attempt writes to a real system.")
        local(
            f"    {names.get(device_id, '(unnamed)')!r} setpoint "
            f"{original / 10:.1f}C -> {probe_value / 10:.1f}C, then back to "
            f"{original / 10:.1f}C."
        )
        local("    Nothing else is touched. Expected outcome: no change at all.")
        try:
            if input("  Type 'yes' to continue: ").strip().lower() != "yes":
                local("  Aborted; nothing was sent.")
                return 1
        except (EOFError, KeyboardInterrupt):
            local("\n  Aborted; nothing was sent.")
            return 1

    print(
        f"testing on {anon(device_id)}: setpoint {original / 10:.1f} -> "
        f"{probe_value / 10:.1f} (restored afterwards)"
    )

    changed_by = None
    try:
        # Check 1 yardstick: what an invented section comes back as.
        _, payload, _ = post(
            url,
            username,
            password,
            {
                CONTROL_SECTION: {
                    "deviceId": device_id,
                    "uid": SETPOINT_UID,
                    "value": probe_value,
                }
            },
        )
        control_echo = section_echo(payload, CONTROL_SECTION)
        print(f"\ncontrol (invented section) returned: {control_echo}\n")

        for label, path, cmd in candidates(device_id, SETPOINT_UID, probe_value):
            candidate_url = url.rsplit("/", 2)[0] + "/" + path if path else url
            section = list(cmd)[-1]
            status, payload, text = post(candidate_url, username, password, cmd)

            if status is None:
                print(f"{label}\n    {text}\n")
                continue

            echo = section_echo(payload, section)
            if status != 200:
                note = "endpoint does not exist"
            elif echo == control_echo:
                note = "echoed exactly like the invented section - not understood"
            else:
                note = f"echo DIFFERS from control: {echo}"

            # Check 2.
            time.sleep(SETTLE_SECONDS)
            _, after = read_state(url, username, password)
            now = after.get((device_id, SETPOINT_UID))
            effective = now == probe_value

            print(f"{label}")
            print(f"    HTTP {status}  {note}")
            print(
                f"    setpoint after: {now} (wanted {probe_value})"
                f"{'  <<< CHANGED' if effective else ''}\n"
            )

            if effective:
                changed_by = label
                break
    finally:
        _, after = read_state(url, username, password)
        if after.get((device_id, SETPOINT_UID)) != original:
            print(f"restoring setpoint to {original / 10:.1f} ...")
            for _, path, cmd in candidates(device_id, SETPOINT_UID, original):
                restore_url = url.rsplit("/", 2)[0] + "/" + path if path else url
                post(restore_url, username, password, cmd)
            time.sleep(SETTLE_SECONDS)
            _, after = read_state(url, username, password)
            state = after.get((device_id, SETPOINT_UID))
            print(
                f"setpoint now {state}."
                + ("" if state == original else "  PLEASE CHECK THIS MANUALLY.")
            )

    print("=" * 68)
    if changed_by:
        print("RESULT: A COMMAND WORKED OVER HTTPS.")
        print(f"The winning form was: {changed_by}")
        print("\nThis is a significant finding - please report it with the log above.")
    else:
        print("RESULT: NO HTTPS COMMAND WORKED.")
        print("Every candidate either was echoed like an invented section, or")
        print("changed nothing on a device that was online and reporting.")
        print("\nThis supports the conclusion that commands require the socket")
        print("on port 5210, and that the HTTPS API is read-only.")
    print("=" * 68)
    print("\nThis result contains no credentials, device IDs, or names, and is")
    print("safe to post publicly. Lines marked [local only] are not part of it;")
    print("to save a clean copy, re-run redirecting stdout:")
    print("    python3 probe_cloud_set.py > result.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
