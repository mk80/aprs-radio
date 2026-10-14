import asyncio
import json
import os
import kiss_tcp
import time
import binary_decode
import binary_encode
import aprs_is
import signal

# Global flag for shutdown
SHUTDOWN = False

CONFIG_PATH = './config.json'
DEFAULT_APRS_IS_SERVER = 'noam.aprs2.net'
# Legacy generic destination — picked as the default because this project is
# generic; operators register their own APZxxx experimental code (or a
# registered device ID) via the startup prompt or by editing config.json.
DEFAULT_DEVICE_CODE = 'APRS'

def user_config():
    config = {}
    print("--- APRS Setup ---")

    # Ask for Callsign first because it is required for IGate login regardless of RX/TX mode
    config['callsign'] = input("Enter Callsign: ").strip().upper()

    ssid_input = input("Enter SSID (0-15, leave blank for 0): ").strip()
    config['ssid'] = int(ssid_input) if ssid_input else 0

    mode = input("Select Mode ([R]X only or [B]oth RX/TX): ").strip().lower()
    config['mode'] = 'both' if mode == 'b' else 'rx'

    server = input(f"APRS-IS server [{DEFAULT_APRS_IS_SERVER}]: ").strip()
    config['aprs_is_server'] = server or DEFAULT_APRS_IS_SERVER

    if config['mode'] == 'both':
        print("\n--- Position Information ---")
        print("\n[GPS Latitude: e.g., 32 degrees 47.99']")
        lat_d = int(input("  Degrees: "))
        lat_m = float(input("  Minutes: "))

        print("\n[GPS Longitude: e.g., 117 degrees 01.59']")
        lon_d = int(input("  Degrees: "))
        lon_m = float(input("  Minutes: "))

        config['lat'], config['lon'] = format_gps_to_aprs(lat_d, lat_m, lon_d, lon_m)

        # --- ICON SELECTION ---
        print("\nCommon Icons: [H]ome, [B]ike, [C]ar, [J]eep, [S]hip, [P]erson, [G]ateway")
        icon_choice = input("Select Icon: ").strip().lower()
        icons = {
            'h': ('/', '-'), 'b': ('/', '<'), 'c': ('/', '>'),
            'j': ('/', 'j'), 's': ('/', 's'), 'p': ('/', '['),
            'g': ('/', '&')
        }
        # default to home if choice is invalid
        config['table'], config['symbol'] = icons.get(icon_choice, ('/', '-'))

        config['message'] = input("Enter Beacon Message: ").strip()

        interval = input("Beacon interval in minutes (e.g., 10): ").strip()
        config['interval'] = int(interval) * 60 if interval else 600

        device_code = input(f"Device code [{DEFAULT_DEVICE_CODE}]: ").strip().upper()
        config['device_code'] = device_code or DEFAULT_DEVICE_CODE

    return config


def load_or_create_config():
    """Load ./config.json if present; otherwise run the wizard and persist.

    Reconfigure by deleting the file. Secrets (cs_token) live elsewhere and
    aren't touched here; config.json is .gitignored because it still carries
    lat/lon which is modestly sensitive.
    """
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        # One-line summary so you can see what you're about to run with.
        call_ssid = f"{config.get('callsign')}-{config.get('ssid')}"
        summary = f"{call_ssid}, {config.get('mode')}, APRS_IS={config.get('aprs_is_server')}"
        if config.get('mode') == 'both':
            summary += f", device={config.get('device_code')}"
        print(f"Loaded {CONFIG_PATH}: {summary}")
        print(f"(delete {CONFIG_PATH} to re-run the wizard)")
        return config

    config = user_config()
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"Saved config to {CONFIG_PATH}.")
    return config

def format_gps_to_aprs(lat_deg, lat_min, lon_deg, lon_lon_min):
    """
    Takes GPS Degrees/Minutes and formats them directly for APRS.
    Example: 32, 47.9900, 117, 01.5932
    """
    # Latitude: DDMM.mmN (8 characters)
    # %02d = 32, %05.2f = 47.99 -> '3247.99N'
    lat_str = f"{int(lat_deg):02d}{lat_min:05.2f}N"

    # Longitude: DDDMM.mmW (9 characters)
    # %03d = 117 (or 011), %05.2f = 01.59 -> '11701.59W'
    lon_str = f"{int(abs(lon_deg)):03d}{lon_lon_min:05.2f}W"

    return lat_str, lon_str

# --- shared resources ---
FEND = b'\xc0'

async def async_rx_task(tnc_interface, protocol_decode, gateway_q, callsign):
    """
    Async RX loop. Reads from Dire Wolf's KISS TCP socket; asyncio's StreamReader
    wakes this task the instant bytes arrive (epoll), so there is no polling floor.
    """
    print("--- RX Task Started ---")
    current_data = bytearray() # Mutable buffer

    while not SHUTDOWN:
        try:
            new_data = await tnc_interface.read(4096)
            if not new_data:
                # EOF — Dire Wolf closed the connection
                print("RX Task: Dire Wolf closed the KISS connection.")
                return
            current_data.extend(new_data)

            # 2. KISS Frame Delimitation/Processing loop (Find [FEND ... FEND])
            while FEND in current_data:
                # sync: find the first FEND
                first_fend = current_data.find(FEND)

                # if FEND is not at the start (index 0), discard the junk before it
                if first_fend > 0:
                    del current_data[:first_fend]
                    # Loop again to find the FEND at 0
                    continue
                
                # now the buffer definitely starts with 0xc0
                # look for a second 0xc0 (the end of the frame)
                # start the search at index 1 to avoid finding the first FEND again
                second_fend = current_data.find(FEND, 1)

                if second_fend != -1:
                    # we found a complete frame
                    # extract the frame (including both FENDs)
                    # Note: Slicing bytearray returns bytearray. binary_decode should handle it.
                    complete_frame = current_data[:second_fend + 1]
                    # Timestamp as early as possible: the moment we have a
                    # complete KISS frame in hand. Everything after this is
                    # our own processing + network cost.
                    t_rx = time.perf_counter_ns()

                    # 3. process the frame in the binary decoder
                    if len(complete_frame) > 2: # ignore empty frames like 0xc0 0xc0
                        try:
                            result = protocol_decode.decode_frame(complete_frame)
                            if result and callsign != result['source']:
                                if result.get('payload', '').startswith('}'):
                                    # 3rd-party packet. The APRS spec forbids
                                    # iGates from uplinking these to APRS-IS;
                                    # aprsc silently drops them with
                                    # rx_errs[10] = party_3rd_ip. Skipping here
                                    # saves a wasted round trip to the server.
                                    print(f"RX: {result['source']} -> {result['destination']} (3rd-party, not iGating)")
                                else:
                                    tnc2_str = protocol_decode.to_tnc2(result, callsign)
                                    t_formatted = time.perf_counter_ns()
                                    await gateway_q.put((tnc2_str, t_rx, t_formatted))
                                    print(f"RX: {result['source']} -> {result['destination']}")
                            elif callsign == result['source']:
                                print(f"Packet Duplicate :: callsign :: {result['source']} :: {callsign}")
                            else:
                                pass # decode failed, ignore silently
                        except Exception:
                            pass # decode error, ignore

                    # remove the processed frame from the buffer
                    del current_data[:second_fend + 1]
                else:
                    # we have the start of a packet, but the end hasn't arrived yet
                    break
            
            # Yield occasionally even if we processed data to be fair to TX/Net tasks
            # await asyncio.sleep(0) 

        except Exception as e:
            print(f"RX Task Error: {e}")
            await asyncio.sleep(1)

async def async_tx_task(tnc_interface, config):
    """
    Async TX loop for beaconing.
    """
    print("--- TX Task Started ---")
    protocol_encode = binary_encode.BinaryEncoder()
    
    # Format Payload once if it doesn't change (simplification)
    # Format: !3248.20N/11709.09W>Message
    # Note: The 'Table' sits between Lat and Lon, the 'Symbol' sits after Lon.
    payload_str = f"!{config['lat']}{config['table']}{config['lon']}{config['symbol']}{config['message']}"
    
    # Immediate first beacon
    last_tx_time = 0 
    
    while not SHUTDOWN:
        try:
            current_time = time.time()
            if current_time - last_tx_time >= config['interval']:
                print("TX: Sending Beacon...")
                # Build and wrap the packet
                raw_ax25 = protocol_encode.construct_ax25_frame(
                    config['callsign'],
                    config['ssid'],
                    dest=config.get('device_code', DEFAULT_DEVICE_CODE),
                    payload=payload_str
                )
                kiss_packet = protocol_encode.kiss_stuff(raw_ax25)
                
                # Transmit
                await tnc_interface.write_frame(kiss_packet)
                print(f"TX: Complete ({len(kiss_packet)} bytes)")
                
                last_tx_time = current_time
            
            await asyncio.sleep(1) # Check every second
            
        except Exception as e:
            print(f"TX Task Error: {e}")
            await asyncio.sleep(5)

async def main():
    global SHUTDOWN
    
    # 1. Configuration (Sync) — loaded from ./config.json or built via wizard
    #    on first run; see load_or_create_config().
    config = load_or_create_config()
    call_ssid = f"{config['callsign']}-{config['ssid']}"

    # 2. Setup Resources
    gateway_q = asyncio.Queue()

    # Connect to Dire Wolf's KISS TCP interface (configured in direwolf.conf: KISSPORT 8001).
    tnc_interface = kiss_tcp.KissTCP(host='127.0.0.1', port=8001)
    try:
        await tnc_interface.connect()
    except Exception as e:
        print(f"Failed to connect to Dire Wolf KISS TCP: {e}")
        print("Is `direwolf -c direwolf.conf` running?")
        return

    protocol_decode = binary_decode.BinaryDecoder()
    
    # Setup Async IGate
    passcode = '-1'
    try:
        with open('./cs_token', 'r') as f:
            passcode = f.readline().strip()
    except Exception:
        print("Warning: Could not read cs_token")

    # APRS-IS host precedence: APRS_IS_SERVER env var > config.json > default.
    # The env var lets you one-off override (e.g. probe a different T2 server)
    # without editing config. For dedupe-race work the lowest-RTT endpoint
    # matters a lot — the regional pool round-robins across servers with wide
    # RTT variance (T2BC 44.135.208.225, T2LANE 44.26.110.252, T2SJC
    # 44.10.10.10 all measured well from SoCal).
    aprs_host = (
        os.environ.get('APRS_IS_SERVER')
        or config.get('aprs_is_server')
        or DEFAULT_APRS_IS_SERVER
    )
    igate = aprs_is.AsyncIGate(call_ssid, passcode, gateway_q, host=aprs_host)

    # Connect to APRS-IS up front so we can verify the passcode before launching
    # any tasks. Unverified logins have their iGate uplink silently dropped by
    # the server, so running on would gate nothing for hours without any error.
    try:
        await igate.connect()
    except Exception as e:
        print(f"APRS-IS connection failed: {e}")
        await tnc_interface.close()
        return

    if igate.verified is False:
        print("")
        print("ERROR: APRS-IS login is UNVERIFIED — refusing to start.")
        print(f"  Logged in as {call_ssid} with passcode '{passcode}'.")
        print("  APRS-IS silently drops iGate uplink from unverified clients,")
        print("  so you would receive packets off the air and get no gate credit.")
        print("")
        print("  Fix: generate your passcode (base callsign, no SSID) and save it to ./cs_token:")
        print("    python3 -c \"import aprslib; print(aprslib.passcode('YOURCALL'))\" > ./cs_token")
        print("  or use https://apps.magicbug.co.uk/passcode/")
        print("")
        await tnc_interface.close()
        return

    # 3. Create Tasks
    tasks = []
    
    # RX Task
    tasks.append(asyncio.create_task(async_rx_task(tnc_interface, protocol_decode, gateway_q, call_ssid)))
    
    # IGate Tasks
    tasks.append(asyncio.create_task(igate.send_loop()))
    tasks.append(asyncio.create_task(igate.keepalive()))
    
    # TX Task (if enabled)
    if config['mode'] == 'both':
        tasks.append(asyncio.create_task(async_tx_task(tnc_interface, config)))

    print(f"\n--- System Running in {config['mode'].upper()} mode (Asyncio) ---")
    print("Press Ctrl+C to stop.")

    # 4. Wait for tasks (or shutdown signal)
    try:
        # Use a future to wait for a shutdown signal
        stop_event = asyncio.Event()
        
        loop = asyncio.get_running_loop()
        def signal_handler():
            print("\nShutdown signal received...")
            stop_event.set()
        
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
            
        await stop_event.wait()
        
    except asyncio.CancelledError:
        pass
    finally:
        print("Stopping tasks...")
        SHUTDOWN = True
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await tnc_interface.close()
        print("Cleanup complete.")

if __name__ == '__main__':
    try:
        try:
            import uvloop
            uvloop.install()
            print("Using uvloop for high-performance event loop.")
        except ImportError:
            print("uvloop not found, using standard asyncio loop.")

        asyncio.run(main())
    except KeyboardInterrupt:
        pass # Handled inside main
