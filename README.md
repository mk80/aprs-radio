# Asyncio APRS Radio

A high-performance, asynchronous Python application for sending and receiving APRS (Automatic Packet Reporting System) packets via a KISS TNC and an APRS-IS connection.

## Features

*   **High Performance**: Built on `asyncio` and `uvloop` (a drop-in replacement for the event loop, 2-4x faster than standard Python asyncio).
*   **Low Latency**:
    *   **Network**: Uses `TCP_NODELAY` to disable Nagle's algorithm for immediate packet transmission.
    *   **Serial**: Non-blocking serial I/O with optimized polling.
*   **Efficient Memory Usage**: Uses `bytearray` buffers and zero-copy slicing to minimize garbage collection overhead during high-traffic packet decoding.
*   **Concurrency**: Handles Serial RX, Serial TX (Beaconing), and Network I/O (IGate) simultaneously without threading locks.
*   **Resilience**: Automatic reconnection to APRS-IS and graceful shutdown handling.

## Requirements

### Hardware
*   A Radio capable of AX.25 / APRS.
*   A TNC (Terminal Node Controller) in KISS mode connected via Serial/USB (e.g., `/dev/ttyACM0`).

### Software
*   Python 3.7+
*   Linux (recommended for `uvloop` support)

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/mk80/aprs-radio.git
    cd aprs-radio
    ```

2.  **Create a Virtual Environment (Optional but recommended)**:
    ```bash
    python3 -m venv env
    source env/bin/activate
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    *Dependencies include `pyserial`, `aprslib`, `uvloop`, and `crcmod`.*

4.  **APRS-IS Passcode**:
    Create a file named `cs_token` in the root directory containing your APRS-IS passcode (integer).
    ```bash
    echo "12345" > cs_token
    ```

## Usage

1.  **Connect your TNC** and ensure it is available at `/dev/ttyACM0` (or modify `serial_connection.py` if different).

2.  **Run the Application**:
    ```bash
    python3 main.py
    ```

3.  **Configuration Wizard**:
    Upon start, the application will ask for:
    *   **Callsign**: Your amateur radio callsign (e.g., `N0CALL`).
    *   **SSID**: Station ID (e.g., `0` for home, `9` for mobile).
    *   **Mode**:
        *   `[R]X only`: Receive from radio and IGate to internet.
        *   `[B]oth`: Receive AND transmit beacons (Digipeater/Tracker).
    *   **Location** (If TX enabled): Latitude/Longitude in Degrees/Minutes.
    *   **Icon/Symbol**: Select from common symbols (House, Car, etc.).
    *   **Beacon Message/Interval**: Text implementation and frequency of beacons.

## Troubleshooting

*   **Permission Denied (`/dev/tty...`)**:
    Ensure your user is in the `dialout` group.
    ```bash
    sudo usermod -a -G dialout $USER
    # You must log out and back in for this to take effect.
    ```

*   **uvloop Install Failure**:
    `uvloop` requires a C compiler or pre-built wheel. If installation fails, ensure you have build essentials:
    ```bash
    sudo apt install build-essential python3-dev
    ```
