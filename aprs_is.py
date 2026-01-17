import aprslib
import threading
import time
import queue
import socket

class IGateway(threading.Thread):

    def __init__(self, call, gateway_q):
        # prepares object to behave like a thread
        super().__init__(daemon=True)

        self.server = "rotate.aprs2.net"
        self.port = 14580
        token_file = './cs_token'
        self.passcode = ''
        self.callsign = call.upper()

        try:
            with open(token_file,'r') as f:
                self.passcode = f.readline()
                self.passcode = self.passcode.strip()
        except FileNotFoundError:
            print(f"ERROR : '{token_file}' was not found")
        except Exception as err:
            print(f"ERROR : '{err}' : unexpected error reading file")
        
        #print(f"callsign :: {self.callsign}")
        #print(f"passwd :: {self.passcode}")
        #print(f"host :: {self.server}")
        #print(f"port :: {self.port}")
        self.igate_queue = gateway_q
        self.aprs = aprslib.IS(self.callsign, passwd=self.passcode, host=self.server, port=self.port)

    def run(self): # TODO :: maybe add queue object as an arg
        while True:
            try:
                if not self.aprs._connected:
                    try:
                        print("--- Connecting to APRS-IS ---")
                        self.aprs.connect()
                    except Exception as er:
                        print(f"APRS-IS initial connection failed ({er}) :: retrying in 3s...")
                        time.sleep(3)
                # wait for a packet from the RX thread
                packet_tnc2 = self.igate_queue.get()
                
                # send it to the inter webs
                self.aprs.sendall(packet_tnc2)
                self.igate_queue.task_done()
                print(f"i Gated :: {packet_tnc2}")
            except Exception as err:
                print(f"APRS-IS send packet failed ({err}) :: re-connecting in 3s...")
                time.sleep(3)
    
    # TODO :: this may not be needed.. def not used right now
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