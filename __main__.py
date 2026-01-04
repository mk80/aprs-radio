import serial_connection
import time
import threading
import binary_decode

# --- shared resources for tx and rx ---
serial_lock = threading.Lock() #  CRUCIAL : used to protect the SerialTTY object
FEND = b'\xc0'


def rx_streaming_thread(tnc_interface, protocol_handler, lock):
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
                        result = protocol_handler.decode_frame(complete_frame)
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


def tx_function_example(tnc_interface, kiss_frame):
    """
    Example of a TX function that can be called from the main thread.
    """
    print("Attempting TX...")
    # 1. WRITE: Use the lock when accessing the shared resource (tnc_interface)
    with serial_lock:
        tnc_interface.write_frame(kiss_frame)
        print(f"TX complete: {len(kiss_frame)} bytes written.")


# --- APRS iGate Application Entry Point ---
if __name__ == '__main__':
    try:
        # Initialize the shared objects
        tnc_interface = serial_connection.SerialTTY(baud_rate=115200)
        print(f"visible ports : {tnc_interface.available_ports}")
        protocol_handler = binary_decode.BinaryDecoder()
        
        # Start the RX streaming thread, passing the shared objects
        rx_thread = threading.Thread(
            target=rx_streaming_thread, 
            args=(tnc_interface, protocol_handler, serial_lock)
        )
        rx_thread.daemon = True
        rx_thread.start()

        # Main thread loop (where you can schedule or trigger TX)
        while rx_thread.is_alive():
            time.sleep(0.01)
            # Example TX call:
            # tx_function_example(tnc_interface, b'\xc0\x00TX DATA HERE\xc0')

    except Exception as e:
        print(f"Application error: {e}")
    except KeyboardInterrupt:
        print("\n user interrupt")
    finally:
        if 'tnc_interface' in locals():
            tnc_interface.close()
