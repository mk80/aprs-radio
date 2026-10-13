"""Standalone APRS-IS traffic monitor.

Opens a second, independent connection to APRS-IS (does not share any state
with main.py) and prints packets that either originate from you OR were
credited to your iGate. Useful for verifying that your gate is actually
getting credit for the packets it hears off the air.

Zero latency impact on main.py — separate process, separate socket.

Server-side filters used:
  b/CALL           — budlist: packets whose source callsign is CALL (your TX)
  q/CXURrSZI/CALL  — qConstruct filter: packets whose i-path (iGate) is CALL
                     under any q-construct (i.e. packets APRS-IS credits
                     to your gate; qAR is the typical one)

Login uses your real base callsign on SSID 15 with passcode -1 (RX-only).
APRS-IS no longer accepts fake placeholder callsigns ("Login by user not
allowed"), but a real call with passcode -1 is fine for read-only use.
SSID 15 is picked because it's uncommon and so unlikely to collide with
your gate / handheld / mobile sessions. Override with --login-as if needed.

Usage:
    python3 monitor_aprsis.py YOURCALL-SSID
    python3 monitor_aprsis.py YOURCALL-SSID --login-as YOURCALL-14

Example:
    python3 monitor_aprsis.py KM6ABC-1
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


async def stream(target_call, login_as):
    # q-filter needs at least one qConstruct letter between the slashes;
    # 'CXURrSZI' is every currently defined construct, so any way the gate
    # ends up in the i-path will match.
    filter_expr = f"b/{target_call} q/CXURrSZI/{target_call}"
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
            print(f"[{_ts()}]   TX    = packet you transmitted on RF (source = {target_call})")
            print(f"[{_ts()}]   GATED = packet APRS-IS credits to your gate (what you want to see)")
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
                    # Server comments / keepalives / login response
                    print(f"[{_ts()}] {text}")
                    continue
                tag = "TX   " if text.startswith(tx_prefix) else "GATED"
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

    try:
        asyncio.run(stream(target_call, login_as))
    except KeyboardInterrupt:
        print()
        print("Monitor stopped.")


if __name__ == "__main__":
    main()
