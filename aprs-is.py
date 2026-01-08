import aprslib

class IGateway:

    def __init__(self, call):
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
        
        try:
            self.aprs = aprslib.IS(self.callsign, passwd=self.passcode, host=self.server, port=self.port)
            self.aprs.connect()
        except Exception as err:
            print(f"ERROR : '{err}' : unexpected error connecting to aprs-is")
            

    