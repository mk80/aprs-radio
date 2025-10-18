import serial_connection
import time

aprs_stream = serial_connection.SerialTTY(baudrate=115200)

try:
    print(f"visible ports : {aprs_stream.available_ports}")

    aprs_stream.start_streaming()
    while aprs_stream._running:
        time.sleep(0.1)

except KeyboardInterrupt:
    print("\n user interrupt")
finally:
    aprs_stream.stop_streaming()
    
