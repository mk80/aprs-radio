import serial
from serial.serialutil import SerialException
import serial.tools.list_ports
import time
import threading

class SerialTTY:

    def __init__(self, port='/dev/ttyACM0', baudrate=9600, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        self.ser = None
        self._running = False
        self._thread = None

        self.available_ports = serial.tools.list_ports.comports()

    def list_ports(self):
        return self.available_ports

    def connect(self):
        if self.ser and self.ser.is_open:
            print("Connection is already open")
            return
        
        print(f"Connecting: {self.port} at {self.baudrate}")
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            time.sleep(2)
            if self.ser.is_open:
                print("Connection established")
                self.ser.flushInput()
                return True
        except SerialException as e:
            print(f"Error connecting : {self.port} : {e}")
            self.ser = None
            return False
        
    def _read_data_loop(self):
        while self._running and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    ## TODO : send this to another class to handle decoding KISS frame
                    print(f"[DATA] {line}")
            except SerialException as e:
                print(f"Serial read error : {e}")
                self._running = False
            except KeyboardInterrupt:
                print("User interrupt : read loop")
                break
            except Exception as e:
                print(f"Unexpected error : {e}")
                break

    def start_streaming(self):
        if self.ser is None or not self.ser.is_open:
            if not self.connect():
                print("No connection established : connect before starting stream")
                return
            
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._read_data_loop)
            self._thread.daemon = True
            self._thread.start()
            print("Streaming")
        else:
            print("Streaming already in progress")

    def stop_streaming(self):
        if self._running:
            self._running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2)
                print("Stream halted")
        
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"Disconnecting: {self.port}")
        elif self.ser:
            print(f"Disconnecting: {self.port} : already closed")
