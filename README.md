# Asyncio APRS Radio

An asynchronous Python APRS iGate and beacon station. It uses [Dire Wolf](https://github.com/wb2osz/direwolf) as the software TNC: Dire Wolf demodulates the radio audio and exposes a KISS TNC over TCP. This app reads AX.25 frames from that socket, gates them to APRS-IS as a bi-directional (`qAR`) iGate, and can optionally transmit periodic position beacons.

## How it works

```
Radio ──audio──> Digirig ──> Dire Wolf ──KISS/TCP :8001──> main.py ──TCP──> APRS-IS
                                 ^                            │
                                 └──── TX beacons (KISS) ─────┘
```

*   **RX:** `kiss_tcp.py` connects to Dire Wolf on `127.0.0.1:8001`. Each KISS frame is decoded by `binary_decode.py` and converted to a TNC2 line (`SRC>DEST,PATH,qAR,YOURCALL-SSID:payload`).
*   **iGate:** `aprs_is.py` logs in to APRS-IS and sends each line straight away. If the server says the login is unverified, the app exits at startup, because APRS-IS silently drops uplink from unverified clients.
*   **TX (optional):** `binary_encode.py` builds an AX.25 position beacon and sends it back to Dire Wolf over the same KISS socket to be transmitted.
*   **Filtering:**
    *   Packets from your own `CALL-SSID` are not re-gated.
    *   Third-party packets (payload starting with `}`) are not gated, because the APRS spec forbids it and APRS-IS drops them anyway.
*   **Latency:**
    *   Both sockets use `TCP_NODELAY`.
    *   RX is driven by events (no polling).
    *   Each gated packet prints its processing and network time, plus a running median.

## Requirements

### Hardware
*   A 2 m radio tuned to your local APRS frequency (144.390 MHz in North America).
*   An audio/PTT interface. The included `direwolf.conf` is set up for a **Digirig + Baofeng HT**.

### Software
*   Python 3.7+
*   Linux
*   Dire Wolf (`sudo apt install direwolf`, or build from source)

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/mk80/aprs-radio.git
    cd aprs-radio
    ```

2.  **Create a virtual environment** (recommended):
    ```bash
    python3 -m venv env
    source env/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    *   `crcmod` is used by the frame decoder.
    *   `aprslib` is used to generate passcodes.
    *   `pyserial` is only needed by `serial_connection.py`, the fallback for a hardware serial KISS TNC.

4.  **Optional: install uvloop**. It is used automatically if present. On RISC-V you may need to build `libuv` yourself, but the standard asyncio loop works fine without it.
    ```bash
    pip install uvloop
    ```

5.  **APRS-IS passcode**: put your passcode in `./cs_token`. Generate it from your **base** callsign (no SSID):
    ```bash
    python3 -c "import aprslib; print(aprslib.passcode('YOURCALL'))" > cs_token
    ```
    `cs_token` is gitignored. If it's missing, the app logs in with `-1`, which is unverified, so startup will stop.

## Configuration

### Dire Wolf (`direwolf.conf`)

Edit these for your hardware:

| Setting | Default | Notes |
|---|---|---|
| `ADEVICE` | `plughw:1,0 plughw:1,0` | Sound card for RX/TX (`arecord -l` to list) |
| `PTT` | `/dev/ttyUSB0 RTS` | Digirig keys PTT using RTS on its serial port |
| `TXDELAY` / `TXTAIL` | `30` / `10` | Padding for slow-switching HTs (units of 10 ms) |
| `KISSPORT` | `8001` | Must match the port in `main.py` |

### App (`config.json`)

The first time you run the app, it asks a few setup questions and saves the answers to `./config.json` (gitignored, since it contains your lat/lon). Later runs load that file and print a one-line summary. **To reconfigure, delete `config.json`**, or edit it directly.

| Key | Prompt | Notes |
|---|---|---|
| `callsign` | Callsign | Your base call |
| `ssid` | SSID (0–15) | e.g. `1` or `10` for an iGate |
| `mode` | `[R]X only` / `[B]oth` | `rx` = iGate only; `both` = iGate + beacons |
| `aprs_is_server` | APRS-IS server | Default `noam.aprs2.net` |
| `lat`, `lon` | Degrees + minutes | *Both mode only.* Saved in APRS format (`3247.99N`, `11701.59W`). The wizard assumes N/W. |
| `table`, `symbol` | Icon | *Both mode only.* Home, bike, car, jeep, ship, person, gateway |
| `message` | Beacon message | *Both mode only.* Comment text |
| `interval` | Beacon interval (min) | *Both mode only.* Stored in seconds (default 600) |
| `device_code` | Device code | *Both mode only.* AX.25 destination / tocall. Default `APRS`; use your registered `APxxxx` or an experimental `APZxxx` |

Example:
```json
{
  "callsign": "N0CALL",
  "ssid": 10,
  "mode": "both",
  "aprs_is_server": "noam.aprs2.net",
  "lat": "3247.99N",
  "lon": "11701.59W",
  "table": "/",
  "symbol": "&",
  "message": "Asyncio iGate",
  "interval": 600,
  "device_code": "APZXXX"
}
```

### Choosing an APRS-IS server

Use a regional pool (e.g. `noam.aprs2.net`), not `rotate.aprs2.net`. `rotate` can connect you to a server on another continent. The extra round-trip time can then let another iGate's copy of the same packet reach APRS-IS first, so the packet is credited to them instead of you.

For a one-off override, without editing `config.json`, set `APRS_IS_SERVER`. It takes precedence over the config file:
```bash
APRS_IS_SERVER=t2sjc.aprs2.net python3 main.py
```

## Usage

1.  **Start Dire Wolf**:
    ```bash
    direwolf -c direwolf.conf
    ```

2.  **Start the app** in another terminal:
    ```bash
    python3 main.py
    ```

Example output:
```
RX: N0ABC-9 -> APDR16
iGated [1.2ms proc=0.09 net=1.11  median(20)=0.9ms] >> N0ABC-9>APDR16,WIDE1-1,qAR,N0CALL-10:=3247.00N/11700.00W$
```

Stop with `Ctrl+C`. The app shuts down cleanly on SIGINT and SIGTERM.

## Monitoring gate credit

`monitor_aprsis.py` is a separate, read-only APRS-IS client. It shows which packets APRS-IS credited to your gate and which nearby packets were credited to another iGate. It opens its own connection, so it doesn't affect the gate's latency. It logs in as `<base>-15` with passcode `-1`, or as whatever you pass to `--login-as`.

```bash
python3 monitor_aprsis.py N0CALL-10 --range 32.80,-117.03,100
```

*   `[MINE ]`: a packet your gate iGated
*   `[->X]`: a nearby packet that iGate `X` got credit for
*   `[TX   ]`: your own beacon coming back from APRS-IS

Without `--range`, you only see your own beacons.

## Tests

```bash
python3 -m unittest test_aprs_format   # TNC2 output sent to APRS-IS
python3 test_decode.py                 # decode a known KISS frame (its CRC section reports FAILED; see below)
python3 verify_packets.py              # encode → decode round trip
```

The CRC check in `test_decode.py` fails because the sample frame has no FCS. Dire Wolf strips the FCS before sending frames over KISS, so `check_crc()` isn't used at runtime.

## Troubleshooting

*   **`Failed to connect to Dire Wolf KISS TCP`**: Dire Wolf isn't running, or `KISSPORT` isn't 8001.
*   **`APRS-IS login is UNVERIFIED — refusing to start`**: `cs_token` is missing or wrong. Generate the passcode from your base callsign (see Installation).
*   **`Login by user not allowed`**: APRS-IS rejects placeholder callsigns such as `N0CALL`. Use a real callsign.
*   **Packets show `RX:` but never appear on aprs.fi**: Run `monitor_aprsis.py` with `--range`. Another iGate may be getting the credit, often because your APRS-IS server is far away.
*   **Permission denied on `/dev/ttyUSB0` (PTT) or the audio device**:
    ```bash
    sudo usermod -a -G dialout,audio $USER
    # Log out and back in for this to take effect.
    ```
*   **uvloop install fails**: install the build tools (`sudo apt install build-essential python3-dev`), or skip uvloop. It's optional.
