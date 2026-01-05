import binary_decode

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