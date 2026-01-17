import binary_decode
import crcmod

protocol_decode = binary_decode.BinaryDecoder()

# This is a raw KISS frame (hex) for an APRS packet
test_hex = "c00082a0aeae6240609692888a644062ae92888a64406303f021343533312e35324e2f30373333362e3135572d5068696c6164656c7068696120415052532054657374c0"
test_bytes = bytes.fromhex(test_hex)
print("Testing Decoder with known packet...")
result = protocol_decode.decode_frame(test_bytes)

if result:
    print(f"SUCCESS!")
    print(f"Source: {result['source']}")
    print(f"Payload: {result['payload']}")
else:
    print("FAILED: Decoder returned None.")

def test_crc(test_bs):
    fcs_func = crcmod.predefined.mkPredefinedCrcFun('x-25')
    
    # This is a real AX.25 frame (Source: KM6VOM, Dest: APDW16)
    # The last two bytes (0x23, 0x82) are the FCS.
    test_frame = bytearray([
        0x82, 0xa0, 0x88, 0xae, 0x62, 0x60, 0x60, 0x96, 0x9a, 0x6c, 0xac, 0x9e, 0x9a, 0xe1, 
        0x03, 0xf0, 0x21, 0x33, 0x32, 0x34, 0x37, 0x2e, 0x39, 0x39, 0x4e, 0x2f, 0x31, 0x31, 
        0x37, 0x30, 0x31, 0x2e, 0x35, 0x39, 0x57, 0x2d, 0x54, 0x65, 0x73, 0x74, 
        0x23, 0x82 # <--- FCS
    ])

    result = fcs_func(test_frame)
    print(f"CRC Result: {hex(result)}")
    
    if result == 0x1d0f:
        print("SUCCESS: Magic Constant Found!")
    else:
        print("FAILED: Logic is incorrect.")

    fcs_func_diy = crcmod.mkCrcFun(0x11021, rev=True, initCrc=0xFFFF, xorOut=0xFFFF)
    calculated = fcs_func_diy(test_bs)
    test_frame_int = test_bs[0] | (test_bs[1] << 0)

    print(f"calculated :: {calculated}")
    print(f"test_frame_int :: {test_frame_int}")

test_crc(test_bytes)