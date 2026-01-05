import serial_connection
import time
import threading
import binary_decode
import binary_encode

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
        # --- COORDINATE INPUT ---
        try:
            raw_coords = input("Enter Dec. Coordinates (e.g. 32.8,-117.1): ").strip()
            lat_dec, lon_dec = map(float, raw_coords.split(','))
            config['lat'], config['lon'] = convert_to_aprs_format(lat_dec, lon_dec)
        except:
            print("Invalid format. Defaulting to 0,0.")
            config['lat'], config['lon'] = "0000.00N", "00000.00W"
        
        # --- ICON SELECTION ---
        print("\nCommon Icons: [H]ome, [B]ike, [C]ar, [J]eep, [S]hip, [P]erson")
        icon_choice = input("Select Icon: ").strip().lower()
        icons = {
            'h': ('/', '-'), 'b': ('/', '<'), 'c': ('/', '>'),
            'j': ('/', 'j'), 's': ('/', 's'), 'p': ('/', '[')
        }
        # default to home if choice is invalid
        config['table'], config['symbol'] = icons.get(icon_choice, ('/', '-'))
        
        config['message'] = input("Enter Beacon Message: ").strip()
        
        interval = input("Beacon interval in minutes (e.g., 10): ").strip()
        config['interval'] = int(interval) * 60 if interval else 600
    return config

def convert_to_aprs_format(lat, lon):
    """
    Converts decimal degrees to APRS DDMM.mmN and DDDMM.mmW format.
    Example: 32.8033, -117.1515 -> ('3248.20N', '11709.09W')
    """
    # Latitude
    lat_dir = "N" if lat >= 0 else "S"
    lat = abs(lat)
    lat_deg = int(lat)
    lat_min = (lat - lat_deg) * 60
    # Format: 2 digits for degrees, 5 chars for MM.mm (zero-padded)
    lat_str = f"{lat_deg:02d}{lat_min:05.2f}{lat_dir}"

    # Longitude
    lon_dir = "E" if lon >= 0 else "W"
    lon = abs(lon)
    lon_deg = int(lon)
    lon_min = (lon - lon_deg) * 60
    # Format: 3 digits for degrees, 5 chars for MM.mm (zero-padded)
    lon_str = f"{lon_deg:03d}{lon_min:05.2f}{lon_dir}"

    return lat_str, lon_str

# --- shared resources for tx and rx ---
serial_lock = threading.Lock() #  CRUCIAL : used to protect the SerialTTY object
FEND = b'\xc0'

def rx_streaming_thread(tnc_interface, protocol_decode, lock):
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
                        if result:
                            print(f"Packet Received: {result['source']} -> {result['destination']}")
                            print(f"Payload: {result['payload']}")
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
        
        # Start the RX streaming thread, passing the shared objects
        rx_thread = threading.Thread(
            target=rx_streaming_thread, 
            args=(tnc_interface, protocol_decode, serial_lock)
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
                    raw_ax25 = protocol_encode.construct_aprs_frame(
                        config['callsign'], 
                        config['ssid'], 
                        payload=payload_str
                    )
                    kiss_packet = protocol_encode.kiss_wrap(raw_ax25)
                    
                    # Transmit
                    tx_beacon(tnc_interface, serial_lock, kiss_packet)
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
