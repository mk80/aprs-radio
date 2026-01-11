import aprslib
import threading
import queue
import time

class IGateway(threading.Thread):

    def __init__(self, call, gate_queue):
        self.server = "rotate.aprs2.net"
        self.port = 14580
        token_file = './cs_token'
        self.passcode = ''
        self.callsign = call

        try:
            with open(token_file,'r') as f:
                passcode = f.readline()
                passcode = passcode.strip()
        except FileNotFoundError:
            print(f"ERROR : '{token_file}' was not found")
        except Exception as err:
            print(f"ERROR : '{err}' : unexpected error reading file")
        
        super().__init__(daemon=True)
        self.aprs = aprslib.IS(self.callsign, passwd=self.passcode, host=self.server, port=self.port)
        self.queue = gate_queue

    def run(self):
        while True:
            try:
                # connect to the global network
                self.aprs.connect()
                print("--- Connected to APRS-IS ---")

                while True:
                    # wait for a packet from the RX thread
                    packet_tnc2 = self.queue.get()
                    # send it to the inter webs
                    self.aprs.sendall(packet_tnc2)
                    print(f"i Gated :: {packet_tnc2}")
            except Exception as err:
                print(f"APRS-IS connection lost ({err}) :: retrying in 3s...")
                time.sleep(3)
            
    def gate_to_internet(self, raw_packet_string):
        """
        Sending packet to APRS-IS
        
        :param self: self reference
        :param raw_packet_string: TNC2 formatted string :: 'CALL>DEST,PATH:PAYLOAD'
        """
        try:
            self.aprs.sendall(raw_packet_string)
            print(f"uploaded to APRS-IS :: {raw_packet_string}")
        except Exception as err:
            print(f"ERROR :: failed to upload :: {err}")

    def disconnect(self):
        """
        Disconnect from APRS-IS server
        
        :param self: self reference
        """
        self.aprs.close()