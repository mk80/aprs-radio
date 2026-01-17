import serial_connection
import time
import threading
import binary_decode
import binary_encode
import aprs_is
import queue
import multiprocessing

def user_config():
    config = {}
    print("--- APRS Setup ---")

    mode = input("Select Mode ([R]X only or [B]oth RX/TX): ").strip().lower()
    config['mode'] = 'both' if mode == 'b' else 'rx'

    if config['mode'] == 'both':
        config['callsign'] = input("Enter Callsign: ").strip().upper()
        
        ssid_input = input("Enter SSID (0-15, leave blank for 0): ").strip()
        config['ssid'] = int(ssid_input) if ssid_input else 0
        
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

# --- shared resources for tx and rx ---
serial_lock = threading.Lock() #  CRUCIAL : used to protect the SerialTTY object
FEND = b'\xc0'

def rx_streaming_thread(tnc_interface, protocol_decode, lock, rx_gate_q, user_conf):
    """
    RX streaming logic: External function, manages concurrency and framing.
    """
    current_data = b'' # Buffer to collect bytes

    while True:
        try:
            # 1. READ: Use the lock when accessing the shared resource (tnc_interface)
            with lock:
                new_data = tnc_interface.read_available_bytes()

            if new_data:
                current_data += new_data

            # 2. KISS Frame Delimitation/Processing loop (Find [FEND ... FEND])
            # ... (Logic to slice and process complete frames from current_data) ...
            while FEND in current_data:
                # sync: find the first FEND
                first_fend = current_data.find(FEND)

                # if FEND is not at the start (index 0), discard the junk before it
                if first_fend > 0:
                    current_data = current_data[first_fend:]
                    continue
                
                # now the buffer definitely starts with 0xc0
                # look for a second 0xc0 (the end of the frame)
                # start the search at index 1 to avoid finding the first FEND again
                second_fend = current_data.find(FEND, 1)

                if second_fend != -1:
                    # we found a complete frame
                    # extract the frame (including both FENDs)
                    complete_frame = current_data[:second_fend + 1]

                    # 3. process the frame in the binary decoder
                    if len(complete_frame) > 2: # ignore empty frames like 0xc0 0xc0
                        result = protocol_decode.decode_frame(complete_frame)
                        if result and user_conf['callsign'] not in result['source']:
                            print(f"Packet Received: {result['source']} -> {result['destination']}")
                            print(f"Payload: {result['payload']}")
                            tnc2_str = protocol_decode.to_tnc2(result)
                            rx_gate_q.put(tnc2_str)
                        elif result['source'] == user_conf['callsign']:
                            print(f"Packet Duplicate :: callsign :: {result['source']} :: {user_conf['callsign']}")
                        else:
                            print("Packet Decode failed!")
                    # remove the processed frame from the buffer
                    current_data = current_data[second_fend + 1:]
                else:
                    # we have the start of a packet, but the end hasn't arrived yet
                    # break the inner while loop and wait for more serial data
                    break
            time.sleep(0.01) # Yield control

        except Exception as e:
            print(f"RX Thread Error: {e}")
            break


def tx_beacon(tnc_interface, kiss_frame, lock):
    """
    Example of a TX function that can be called from the main thread.
    """
    print("Attempting TX...")
    # 1. WRITE: Use the lock when accessing the shared resource (tnc_interface)
    with lock:
        tnc_interface.write_frame(kiss_frame)
        print(f"TX complete: {len(kiss_frame)} bytes written.")


# --- APRS iGate Application Entry Point ---
if __name__ == '__main__':
    # get config
    config = user_config()

    try:
        # Initialize the shared objects
        tnc_interface = serial_connection.SerialTTY(baud_rate=115200)
        print(f"visible ports : {tnc_interface.available_ports}")
        protocol_decode = binary_decode.BinaryDecoder()
        gateway_q_instance = queue.Queue()
        igate_thread = aprs_is.IGateway(config['callsign'], gateway_q=gateway_q_instance)
        igate_thread.daemon = True
        igate_thread.start()
        
        # Start the RX streaming thread, passing the shared objects
        rx_thread = threading.Thread(
            target=rx_streaming_thread, 
            args=(tnc_interface, protocol_decode, serial_lock, gateway_q_instance, config)
        )
        rx_thread.daemon = True
        rx_thread.start()

    except Exception as e:
        print(f"Application error: {e}")
    

    print(f"\n--- System Started in {config['mode'].upper()} mode ---")

    # tx loop if enabled
    if config['mode'] == 'both':
        protocol_encode = binary_encode.BinaryEncoder()
        last_tx_time = 0 # force immediate first transmission
        
        # Format: !3248.20N/11709.09W>Message
        # Note: The 'Table' sits between Lat and Lon, the 'Symbol' sits after Lon.
        payload_str = f"!{config['lat']}{config['table']}{config['lon']}{config['symbol']}{config['message']}"

        try:
            while True:
                current_time = time.time()
                if current_time - last_tx_time >= config['interval']:
                    # Build and wrap the packet
                    raw_ax25 = protocol_encode.construct_ax25_frame(
                        config['callsign'], 
                        config['ssid'], 
                        payload=payload_str
                    )
                    kiss_packet = protocol_encode.kiss_stuff(raw_ax25)
                    
                    # Transmit
                    tx_beacon(tnc_interface, kiss_packet, serial_lock)
                    last_tx_time = current_time
                
                time.sleep(1) # Check timer every second
        except Exception as e:
            print(f"Application error :: tx loop :: {e}")
        except KeyboardInterrupt:
            print("\n user interrupt : shutting down...")
        finally:
            if 'tnc_interface' in locals():
                tnc_interface.close()
    else:
        # RX Only Mode: Just keep the main thread alive
        try:
            while True:
                time.sleep(0.01)
        except Exception as e:
            print(f"Application error :: rx loop :: {e}")
        except KeyboardInterrupt:
            print("\n user interrupt : shutting down...")
        finally:
            if 'tnc_interface' in locals():
                tnc_interface.close()
