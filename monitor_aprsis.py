"""Standalone APRS-IS traffic monitor.

Opens a second, independent connection to APRS-IS (does not share any state
with main.py) and shows two kinds of lines:

  [MINE ] — a packet your gate iGated (the i-path after qAR, is you)
  [->X]   — a packet SOMEONE ELSE iGated that your gate probably also heard
            (your gate lost the dedupe race to iGate X)
  [TX   ] — your own beacon bouncing back from APRS-IS

Zero latency impact on main.py — separate process, separate socket.

Server-side filtering: aprsc's `q/con/ipath` filter does NOT take a callsign
as ipath (it's just `I` or `T`), so we can't ask the server to pre-filter
for packets credited to us. Instead we pull a geographic range of traffic
(--range LAT,LON,KM) plus our own TX (b/CALL), then client-side-tag each
line by inspecting the i-path. Without --range you only see your own TX.

Login uses your real base callsign on SSID 15 with passcode -1 (RX-only).
APRS-IS no longer accepts placeholder callsigns ("Login by user not
allowed"); a real call with passcode -1 is fine for read-only use. SSID 15
is unlikely to collide with your gate/handheld sessions. Override with
--login-as if needed.

Usage:
    python3 monitor_aprsis.py YOURCALL-SSID [--range LAT,LON,KM]
    python3 monitor_aprsis.py KM6ABC-1 --range 32.80,-117.03,100
"""

import argparse
import asyncio
import datetime
import socket as _socket
import sys

# Default to the North America regional pool. The generic `rotate.aprs2.net`
# is nominally geo-aware but in practice sometimes hands out servers in
# Sydney / Europe — fine for a monitor but a disaster for a real gate racing
# other iGates for dedupe credit. Keep both scripts pointed at the same
# regional pool so monitor and gate agree on which servers they're using.
APRS_IS_HOST = "noam.aprs2.net"
APRS_IS_PORT = 14580


def _ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


def _extract_igate(tnc2_line):
    """Return the i-gate callsign from ',qA?,<call>:' or None if absent.

    Any q-construct (qAC, qAR, qAr, qAS, qAI, ...) counts; we only care
    which station APRS-IS credited for the packet.
    """
    # qConstruct is literally 'qA' followed by one letter, then a comma,
    # then the i-gate call, then a colon ending the header.
    header_end = tnc2_line.find(':')
    if header_end < 0:
        return None
    header = tnc2_line[:header_end]
    idx = header.rfind(',qA')
    if idx < 0 or idx + 4 >= len(header):
        return None
    # ',qAX,' is 5 chars; the gate call starts right after
    return header[idx + 5:]


async def stream(target_call, login_as, range_spec):
    # b/CALL gets our own TX; r/lat/lon/km gets nearby traffic so we can
    # client-side-tag packets our gate iGated. aprsc's q/con/ipath can't
    # filter by iGate callsign (ipath is 'I'/'T', not a call), so range
    # is the only way to see MINE vs ->OTHER tagging live.
    filter_parts = [f"b/{target_call}"]
    if range_spec:
        filter_parts.append(f"r/{range_spec.replace(',', '/')}")
    filter_expr = " ".join(filter_parts)
    # Read-only login (-1 passcode). Must use a real callsign — APRS-IS now
    # rejects fake placeholders with "Login by user not allowed".
    login = (
        f"user {login_as} pass -1 vers aprs-radio-mon 0.1 "
        f"filter {filter_expr}\r\n"
    )

    while True:
        try:
            print(f"[{_ts()}] Connecting to {APRS_IS_HOST}:{APRS_IS_PORT} ...")
            reader, writer = await asyncio.open_connection(
                APRS_IS_HOST, APRS_IS_PORT
            )
            sock = writer.get_extra_info('socket')
            if sock is not None:
                try:
                    sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
                except Exception:
                    pass

            writer.write(login.encode('ascii'))
            await writer.drain()

            print(f"[{_ts()}] Logged in as {login_as} (RX-only, passcode -1)")
            print(f"[{_ts()}] Filter: {filter_expr}")
            print(f"[{_ts()}] [MINE ] = packet APRS-IS credited to your gate")
            print(f"[{_ts()}] [->X]   = someone else's gate (X) got credit")
            print(f"[{_ts()}] [TX   ] = your own beacon bouncing back")
            print(f"[{_ts()}] --- streaming (Ctrl+C to quit) ---")

            tx_prefix = f"{target_call}>"
            while True:
                line = await reader.readline()
                if not line:
                    break  # server closed; outer loop will reconnect
                text = line.decode('ascii', errors='replace').rstrip()
                if not text:
                    continue
                if text.startswith('#'):
                    print(f"[{_ts()}] {text}")
                    continue
                # Tag by i-path first (that's the credit question); fall back
                # to source match (our own TX) if the packet has no q-const.
                gate = _extract_igate(text)
                if gate == target_call:
                    tag = "MINE "
                elif text.startswith(tx_prefix):
                    tag = "TX   "
                elif gate is not None:
                    tag = f"->{gate}"
                else:
                    tag = "?    "
                print(f"[{_ts()}] [{tag}] {text}")

            print(f"[{_ts()}] Server closed the connection — reconnecting in 5s")
        except Exception as e:
            print(f"[{_ts()}] Connection error: {e} — reconnecting in 5s")

        await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser(
        description="Live APRS-IS monitor for a single callsign-SSID.",
    )
    parser.add_argument(
        "call",
        help="Your gate's callsign with SSID, e.g. KM6ABC-1. Must match "
             "exactly how your gate logs in to APRS-IS; filters are "
             "case-sensitive and do not wildcard the SSID.",
    )
    parser.add_argument(
        "--login-as",
        default=None,
        help="Callsign-SSID to use for the monitor's own APRS-IS login. "
             "Defaults to <base>-15 so it won't collide with your gate / "
             "handheld / mobile sessions. Only RX-only (passcode -1) is used.",
    )
    parser.add_argument(
        "--range",
        default=None,
        metavar="LAT,LON,KM",
        help="Geographic range filter to catch nearby traffic for GATED "
             "detection. Example: 32.80,-117.03,100 (San Diego, 100 km). "
             "Without this you only see your own TX, since aprsc has no "
             "server-side filter that takes an iGate callsign.",
    )
    args = parser.parse_args()

    # APRS traffic is uppercase on the wire — normalise so filters match the
    # bytes we actually receive, and so a lower-case input doesn't silently
    # produce zero matches.
    target_call = args.call.upper()
    base_call = target_call.split("-", 1)[0]
    login_as = (args.login_as or f"{base_call}-15").upper()

    if "-" not in target_call:
        print(
            f"Warning: '{target_call}' has no SSID suffix. APRS-IS filters "
            f"match exactly, so you may miss packets from/to e.g. "
            f"'{target_call}-1'.",
            file=sys.stderr,
        )

    if login_as == target_call:
        print(
            f"ERROR: --login-as ({login_as}) collides with the gate's own "
            f"session. Pick a different SSID.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.range is not None:
        parts = args.range.split(",")
        if len(parts) != 3:
            print(
                f"ERROR: --range must be LAT,LON,KM (got '{args.range}')",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(
            "Note: no --range given, so you'll only see your own TX. "
            "Add e.g. --range 32.80,-117.03,100 to also see nearby traffic "
            "and tag by iGate credit.",
            file=sys.stderr,
        )

    try:
        asyncio.run(stream(target_call, login_as, args.range))
    except KeyboardInterrupt:
        print()
        print("Monitor stopped.")


if __name__ == "__main__":
    main()
