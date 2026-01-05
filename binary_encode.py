

class BinaryEncoder:

    def __init__(self):
        # --- KISS Protocol Constants (Hex Values) ---
        self.FEND = b'\xc0'
        self.FESC = b'\xdb'
        self.TFEND = b'\xdc'
        self.TFESC = b'\xdd'

    def encode_callsign(self, callsign, ssid=0, is_last=False):
        """
        turns callsign and ssid into a 7-byte AX.25 address field
        
        :param self: reference constructor
        :param callsign: tx as callsign
        :param ssid: ssid for callsign (at the end); ie. W1ABC-1
        :param is_last: 
        """
        # normalize callsign: uppercase and pad to exactly 6 chars with spaces
        callsign = callsign.upper().ljust(6)

        # shift each char left by 1 bit
        encoded_addr = bytearray()
        for char in callsign[:6]:
            encoded_addr.append(ord(char) << 1)
        
        # ssid byte (7th byte) - defaults to 0 if not provided
        # using 0x60 as a base (binary 01100000) for compatability
        ssid_byte = (0x60 | (ssid << 1))
        
        # sed extension bit (bit 0)
        # 0 = more addresses follow (destination or digipeaters)
        # 1 = this is the LAST address in the header (usually the source)
        if is_last:
            ssid_byte |= 0x01

        encoded_addr.append(ssid_byte)

        return bytes(encoded_addr)
    
    def construct_ax25_frame(self, my_call, my_ssid=0, dest="APRS", dest_ssid=0, payload=""):
        """
        builds the raw ax.25 frame (unstuffed)
        
        :param self: reference constructor
        :param my_call: tx as callsign
        :param my_ssid: optional ssid on callsign
        :param dest: optional destination for beacon
        :param dest_ssid: optional ssid of destination
        :param payload: optional payload; ie. lattitude and longitude, azimuth, speed, message
        """
        # encode destination (e-bit = 0)
        dest_bytes = self.encode_callsign(dest, dest_ssid, is_last=False)

        # encode source (e-bit = 1 because on digipeaters are used here)
        source_bytes = self.encode_callsign(my_call, my_ssid, is_last=True)

        # standard APRS header markers
        control_pid = b'\x03\xf0'

        # make the sandwich
        return dest_bytes + source_bytes + control_pid + payload.encode('ascii')
    
    def kiss_stuff(self, ax25_frame):
        """
        prepare AX.25 frame for serial port by adding KISS metadata and stuffing
        
        :param self: reference constructor
        :param ax25_frame: output from construct_ax25_frame function
        """
        # KISS command byte (0x00 = data on port 0)
        kiss_payload = b'\x00' + ax25_frame

        # escape any special bytes in the payload
        # 0xDB -> 0xDB 0xDD
        # 0xC0 -> 0xDB 0xDC
        kiss_payload = kiss_payload.replace(b'\xdb', b'\xdb\xdd')
        kiss_payload = kiss_payload.replace(b'\xc0', b'\xdb\xdc')

        # wrap in FENDs
        return self.FEND + kiss_payload + self.FEND
    
