import serial
from serial.serialutil import SerialException
import serial.tools.list_ports
import time

class SerialTTY:

    def __init__(self, port='/dev/ttyACM0', baud_rate=9600, timeout=0):
        self.port = port
        self.baudrate = baud_rate
        self.timeout = timeout
        print(f"Opening serial port: {self.port} at {self.baudrate}")
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
        except SerialException as e:
            print(f"Error connecting : {self.port} : {e}")
            self.ser = None

        self._running = True
        self._thread = None

        self.available_ports = serial.tools.list_ports.comports()

    def list_ports(self):
        return self.available_ports

    def read_available_bytes(self):
        bytes_to_read = self.ser.in_waiting
        if bytes_to_read > 0:
            return self.ser.read(bytes_to_read)
        return b''

    def write_frame(self, kiss_frame):
        self.ser.write(kiss_frame)
        self.ser.flush()

    def close(self):
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
