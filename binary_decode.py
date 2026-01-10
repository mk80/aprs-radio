import crcmod

class BinaryDecoder:

    def __init__(self):
        # --- KISS Protocol Constants (Hex Values) ---
        self.FEND = b'\xc0'
        self.FESC = b'\xdb'
        self.TFEND = b'\xdc'
        self.TFESC = b'\xdd'


    def decode_frame(self, raw_frame):
        """
        The RX thread calls this. It handles the full pipeline.
        raw_frame is a full [FEND ... FEND] sequence.
        """
        # 1. Step 1: KISS De-stuff (passing content between FENDs)
        # Assuming _kiss_destuff returns (kiss_type, ax25_frame)
        kiss_type, ax25_payload = self._kiss_destuff(raw_frame[1:-1])

        # 2. Check if it's a data frame (Type 0)
        if kiss_type != b'\x00':
            return None

        # 3. Step 2: AX.25 Parse
        # This calls your _parse_ax25_frame logic
        decoded_dict = self._parse_ax25_frame(ax25_payload)
        
        return decoded_dict
    
    def _kiss_destuff(self, stuffed_data):
        """Reverses the KISS byte-stuffing and returns the raw AX.25 frame."""

        # 1. Strip the outer FEND bytes (if they are still present)
        # The data stream should already be delimited by 0xC0
        if stuffed_data.startswith(self.FEND) and stuffed_data.endswith(self.FEND):
            stuffed_data = stuffed_data[1:-1]
        # 2. De-stuff the data using byte replacements
        # This logic must be handled carefully to avoid double-processing

        # Replace FESC + TFEND (0xDB 0xDC) with FEND (0xC0)
        data = stuffed_data.replace(self.FESC + self.TFEND, self.FEND)
        # Replace FESC + TFESC (0xDB 0xDD) with FESC (0xDB)
        data = data.replace(self.FESC + self.TFESC, self.FESC)

        # The first byte is the Type/Port byte, the rest is the AX.25 frame
        kiss_type_byte = data[0:1]
        ax25_frame = data[1:]

        return kiss_type_byte, ax25_frame


    def _get_callsign(self, address_field):
        """
        Parses a 7-byte AX.25 address field
        Returns: (callsign_ssid_str, is_last_address, was_digipeated)
        """
        callsign = b''
        # Extract callsign (first 6 bytes, unshifted)
        for byte in address_field[:6]:
            callsign += bytes([byte >> 1])
        # Extract SSID and Control bits (last byte)
        ssid_byte = address_field[6]
        ssid = (ssid_byte >> 1) & 0x0F          # SSID is bites 1-4 (4 bits total)
        is_last_address = (ssid_byte & 0x01)    # Ea bit is the LSB (bit 0)
        was_digipeated = (ssid_byte & 0x80)     # H bit (has been repeated) si the MSB (bit 7)

        callsign_str = callsign.strip().decode('ascii', errors='ignore')
        callsign_ssid_str = f"{callsign_str}-{ssid}"

        return callsign_ssid_str, is_last_address, was_digipeated


    def _parse_ax25_frame(self, frame_data):
        """
        Dynamically parses an AX.25 frame including a variable number of digipeaters
        """
        current_byte_index = 0
        parsed_addresses = []

        # 1. Parse all Address Fields (Destination, Source, and Digipeaters)
        #   The loop stops when the End of Address (Ea) bit is found (is_last_address == 1)
        is_last_address = 0
        while not is_last_address and current_byte_index + 7 <= len(frame_data):
            address_field = frame_data[current_byte_index : current_byte_index + 7]
            current_byte_index += 7
            # Guard against truncated frames
            if len(address_field) < 7:
                print("Error: truncated AX.25 frame data")
                return
            call_ssid, is_last_address, was_digipeated = self._get_callsign(address_field)
            parsed_addresses.append({
                'call': call_ssid,
                'was_digipeated': was_digipeated
            })
        # If we didn't get at least a Destination and Source, it's invalid
        if len(parsed_addresses) < 2:
            return {'status': 'Error: Truncated Address Field'}
        # Extract Control, PID, and Payload (must have at least 2 bytes remaining)
        if len(frame_data) < current_byte_index + 2:
            return {'status': 'Error: Missing Control/PID'}
        control_field = frame_data[current_byte_index]
        pid_field = frame_data[current_byte_index + 1]
        payload = frame_data[current_byte_index + 2:]
        # Build the output dictionary
        result = {
            'status': 'OK',
            'destination': parsed_addresses[0]['call'],
            'source': parsed_addresses[1]['call'],
            'control': hex(control_field),
            'pid': hex(pid_field),
            'payload': payload.decode('ascii', errors='ignore') if pid_field == 0xF0 else payload.hex(),
            'path': []
        }
        # Add digipeater path if present
        for addr_data in parsed_addresses[2:]:
            marker = '*' if addr_data['was_digipeated'] else ''
            result['path'].append(f"{addr_data['call']}{marker}")
        return result

    def to_tnc2(self, parsed_data):
        """
        Converts parsed dictionary back into TNC2 string for APRS-IS
        
        :param self: self reference
        :param parsed_data: AX.25 dictionary of parsed frame
        """
        src = parsed_data['source']
        dest = parsed_data['destination']
        path = ",".join(parsed_data['path'])
        payload = parsed_data['payload']

        return f"{src}>{dest},{path}:{payload}"
    
    def check_crc(self, frame_bytes):
        """
        Validates the AX.25 Frame Check Sequence (FCS)
        
        :param self: self reference
        :param frame_bytes: raw AX.25 frame (EXCLUDING the KISS 0xc0 flags)
        """
        if len(frame_bytes) < 3:
            return False
        
        # the last 2 bytes are the FCS
        received_fcs = frame_bytes[-2:]
        data_to_check = frame_bytes[:-2]

        # CRC-CCITT (X.25)
        # initial value 0xFFFF, polynomial 0x1021, reflected
        fcs_func = crcmod.predefined.mkPredefinedCrcFun('x-25')
        calculated_fcs = fcs_func(data_to_check)

        # in AX.25, the FCS is stored in little-endian
        # the 'x-25' function returns a value that, when run over the
        # entire frame (data + fcs), should result in a magic constant 0x1D0F
        return fcs_func(frame_bytes) == 0x1D0F