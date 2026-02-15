import asyncio
import serial_connection
import time
import binary_decode
import binary_encode
import aprs_is
import signal

# ... (imports remain) ...

# Global flag for shutdown
SHUTDOWN = False

def user_config():
    config = {}
    print("--- APRS Setup ---")

    # Ask for Callsign first because it is required for IGate login regardless of RX/TX mode
    config['callsign'] = input("Enter Callsign: ").strip().upper()
    
    ssid_input = input("Enter SSID (0-15, leave blank for 0): ").strip()
    config['ssid'] = int(ssid_input) if ssid_input else 0

    mode = input("Select Mode ([R]X only or [B]oth RX/TX): ").strip().lower()
    config['mode'] = 'both' if mode == 'b' else 'rx'

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

async def async_read_serial(tnc_interface):
    """Non-blocking wrapper for reading serial bytes."""
    # Since tnc_interface.read_available_bytes() is non-blocking (returns empty if none),
    # we can run it directly. If it was blocking, we'd use loop.run_in_executor.
    return tnc_interface.read_available_bytes()

async def async_write_serial(tnc_interface, data):
    """Non-blocking wrapper for writing serial bytes."""
    tnc_interface.write_frame(data)

async def async_rx_task(tnc_interface, protocol_decode, gateway_q, callsign):
    """
    Async RX loop.
    Optimized to use bytearray buffers and in-place modification.
    """
    print("--- RX Task Started ---")
    current_data = bytearray() # Mutable buffer
    
    while not SHUTDOWN:
        try:
            new_data = await async_read_serial(tnc_interface)
            
            if new_data:
                current_data.extend(new_data)
            else:
                # Allow other tasks to run if no data
                await asyncio.sleep(0.001)
                continue

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
                    
                    # 3. process the frame in the binary decoder
                    if len(complete_frame) > 2: # ignore empty frames like 0xc0 0xc0
                        try:
                            # We clone complete_frame implicitly by slicing if we needed to, 
                            # but here we pass it. If decode modifies it, we might care, but it doesn't.
                            # It's safer to convert to bytes if unsure, but for speed we try to avoid it.
                            result = protocol_decode.decode_frame(complete_frame)
                            if result and callsign != result['source']:
                                tnc2_str = protocol_decode.to_tnc2(result, callsign)
                                await gateway_q.put(tnc2_str)
                                # Async logging (simulated via print, but it doesn't block the loop logic much)
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
                    payload=payload_str
                )
                kiss_packet = protocol_encode.kiss_stuff(raw_ax25)
                
                # Transmit
                await async_write_serial(tnc_interface, kiss_packet)
                print(f"TX: Complete ({len(kiss_packet)} bytes)")
                
                last_tx_time = current_time
            
            await asyncio.sleep(1) # Check every second
            
        except Exception as e:
            print(f"TX Task Error: {e}")
            await asyncio.sleep(5)

async def main():
    global SHUTDOWN
    
    # 1. Configuration (Sync)
    config = user_config()
    call_ssid = f"{config['callsign']}-{config['ssid']}"

    # 2. Setup Resources
    gateway_q = asyncio.Queue()
    
    # Setup TNC (Sync setup is fine here before loop)
    tnc_interface = serial_connection.SerialTTY(baud_rate=115200)
    if not tnc_interface.ser or not tnc_interface.ser.is_open:
        print("Failed to open serial port. Exiting.")
        return

    print(f"Initialised Serial Port: {tnc_interface.port}")
    
    protocol_decode = binary_decode.BinaryDecoder()
    
    # Setup Async IGate
    passcode = '-1'
    try:
        with open('./cs_token', 'r') as f:
            passcode = f.readline().strip()
    except Exception:
        print("Warning: Could not read cs_token")

    igate = aprs_is.AsyncIGate(call_ssid, passcode, gateway_q)

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
        tnc_interface.close()
        print("Cleanup complete.")

if __name__ == '__main__':
    try:
        try:
            uvloop.install()
            print("Using uvloop for high-performance event loop.")
        except ImportError:
            print("uvloop not found, using standard asyncio loop.")
        except Exception as e:
            print(f"Could not install uvloop: {e}. Using standard asyncio loop.")
            
        asyncio.run(main())
    except KeyboardInterrupt:
        pass # Handled inside main
