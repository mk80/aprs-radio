

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