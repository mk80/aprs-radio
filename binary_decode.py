

class BinaryDecoder:

    def __init__(self):
        # --- KISS Protocol Constants (Hex Values) ---
        FEND = b'\xc0'
        FESC = b'\xdb'
        TFEND = b'\xdc'
        TFESC = b'\xdd'

    def kiss_destuff(stuffed_data):
        """Reverses the KISS byte-stuffing and returns the raw AX.25 frame."""

        # 1. Strip the outer FEND bytes (if they are still present)
        # The data stream should already be delimited by 0xC0
        if stuffed_data.startswith(FEND) and stuffed_data.endswith(FEND):
            stuffed_data = stuffed_data[1:-1]
        # 2. De-stuff the data using byte replacements
        # This logic must be handled carefully to avoid double-processing

        # Replace FESC + TFEND (0xDB 0xDC) with FEND (0xC0)
        data = stuffed_data.replace(FESC + TFEND, FEND)
        # Replace FESC + TFESC (0xDB 0xDD) with FESC (0xDB)
        data = data.replace(FESC + TFESC, FESC)

        # The first byte is the Type/Port byte, the rest is the AX.25 frame
        kiss_type_byte = data[0:1]
        ax25_frame = data[1:]

        return kiss_type_byte, ax25_frame


    def get_callsign(address_field):
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


    def parse_ax25_frame(frame_data):
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
            call_ssid, is_last_address, was_digipeated = get_callsign(address_field)
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
