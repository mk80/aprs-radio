import aprslib

class IGateway:

    def __init__(self):
        server = "rotate.aprs2.net"
        port = 14580
        token_file = './cs_token'
        passcode = ''

        try:
            with open(token_file,'r') as f:
                passcode = f.readline()
                passcode = passcode.strip()
        except FileNotFoundError:
            print(f"ERROR : '{token_file}' was not found")
        except Exception as err:
            print(f"ERROR : '{err}' : unexpected error reading file")

    