

def kiss_destuff(stuffed_data):
    """Reverses the KISS byte-stuffing and returns the raw AX.25 frame."""
    
    # 1. Strip the outer FEND bytes (if they are still present)
    # The data stream should already be delimited by 0xC0
    if stuffed_data.startswith(b'\xc0') and stuffed_data.endswith(b'\xc0'):
        stuffed_data = stuffed_data[1:-1]
    # 2. De-stuff the data using byte replacements
    # This logic must be handled carefully to avoid double-processing
    
    # Replace FESC + TFEND (0xDB 0xDC) with FEND (0xC0)
    data = stuffed_data.replace(b'\xdb\xdc', b'\xc0')
    # Replace FESC + TFESC (0xDB 0xDD) with FESC (0xDB)
    data = data.replace(b'\xdb\xdd', b'\xdb')
    
    # The first byte is the Type/Port byte, the rest is the AX.25 frame
    kiss_type_byte = data[0:1]
    ax25_frame = data[1:]
    
    return kiss_type_byte, ax25_frame

def unshift_callsign(address_field):
    """Converts the 6-byte shifted AX.25 callsign to readable ASCII."""
    callsign = b''
    # The callsign is the first 6 bytes of the 7-byte address field
    for byte in address_field[:6]:
        # Unshift: (byte >> 1) to get the original ASCII character
        callsign += bytes([byte >> 1])

    # The SSID is in the last byte (SSID is bits 1-4, so mask with 0b01111000 and shift)
    # We also check the End-of-Address (Ea) bit (LSB)
    ssid_byte = address_field[6]
    ssid = (ssid_byte >> 1) & 0x0F # extract the 4-bit SSID

    return f"{callsign.strip().decode('ascii')}-{ssid}"

def parse_ax25_frame(frame_data):
    """Decodes the main parts of the AX.25 frame."""
    # AX.25 is byte-oriented, so we can use slicing
    dest_addr_field = frame_data[0:7]
    src_addr_field = frame_data[7:14]

    dest_call = unshift_callsign(dest_addr_field)
    src_call = unshift_callsign(src_addr_field)

    # Simple example assumes no digipeaters, so Control field starts at byte 14
    control_field = frame_data[14]
    pid_field = frame_data[15]

    # The rest is the payload/information field
    payload = frame_data[16:]

    print(f"Destination : {dest_call} :: Source : {src_call} :: Control (Hex) : {hex(control_field)} :: PID (Hex) : {hex(pid_field)}")

    # if PID is 0xF0 (no protocol), the payload is often ASCII text
    if pid_field == 0xF0:
        print(f"    Message : {payload.decode('ascii', errors='ignore')}"
    else:
        print(f"    Raw Payload : {payload.hed()}")

