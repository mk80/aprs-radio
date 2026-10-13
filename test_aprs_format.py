"""Tests for the TNC2 strings sent to APRS-IS.

These validate the exact text that goes on the wire to rotate.aprs2.net — a
malformed line here is silently dropped by the server and the gate loses
credit for the heard packet. Keep assertions on the full string, not just
substrings, so regressions in delimiter placement are caught.
"""

import unittest

import aprs_is
import binary_decode


class ToTnc2Tests(unittest.TestCase):
    def setUp(self):
        self.decoder = binary_decode.BinaryDecoder()
        self.gate = "N0GATE-10"

    def _parsed(self, path):
        return {
            'status': 'OK',
            'source': 'KM6VOM-9',
            'destination': 'APDW16-0',
            'control': '0x3',
            'pid': '0xf0',
            'payload': '!3247.99N/11701.59W-Test',
            'path': path,
        }

    def test_direct_packet_has_no_double_comma(self):
        """Packet heard direct (no digipeater): must not emit ',,qAR,...'."""
        line = self.decoder.to_tnc2(self._parsed([]), self.gate)
        self.assertNotIn(",,", line)
        self.assertEqual(
            line,
            "KM6VOM-9>APDW16-0,qAR,N0GATE-10:!3247.99N/11701.59W-Test",
        )

    def test_single_digi_path(self):
        line = self.decoder.to_tnc2(self._parsed(['WIDE1-1']), self.gate)
        self.assertEqual(
            line,
            "KM6VOM-9>APDW16-0,WIDE1-1,qAR,N0GATE-10:!3247.99N/11701.59W-Test",
        )

    def test_multi_digi_path_with_repeated_marker(self):
        """A digi that has repeated the packet is marked with '*'."""
        line = self.decoder.to_tnc2(
            self._parsed(['WIDE1-1*', 'WIDE2-1']), self.gate
        )
        self.assertEqual(
            line,
            "KM6VOM-9>APDW16-0,WIDE1-1*,WIDE2-1,qAR,N0GATE-10:"
            "!3247.99N/11701.59W-Test",
        )

    def test_qAR_construct_is_present(self):
        """We register as a bi-directional iGate; the qAR token is required."""
        line = self.decoder.to_tnc2(self._parsed([]), self.gate)
        self.assertIn(",qAR,", line)

    def test_decoded_frame_round_trip(self):
        """End-to-end: a real KISS frame decoded then formatted for APRS-IS.

        Uses the same fixture as test_decode.py. The guarantee under test is
        structural: no empty hop (',,'), qAR present, gate stamped last.
        """
        kiss_hex = (
            "c00082a0aeae6240609692888a644062ae92888a64406303f021343533312e"
            "35324e2f30373333362e3135572d5068696c6164656c7068696120415052532"
            "054657374c0"
        )
        result = self.decoder.decode_frame(bytes.fromhex(kiss_hex))
        self.assertIsNotNone(result)
        line = self.decoder.to_tnc2(result, self.gate)
        self.assertNotIn(",,", line)
        self.assertIn(",qAR,N0GATE-10:", line)
        self.assertTrue(line.split(":", 1)[0].endswith(",qAR,N0GATE-10"))


class CallsignRenderingTests(unittest.TestCase):
    """Standard APRS convention: SSID 0 renders as the bare callsign.
    Non-zero SSIDs render as 'CALL-N'. aprs.fi and other strict consumers
    treat 'APRS-0' as non-standard and may drop or mis-aggregate it.
    """

    def setUp(self):
        self.decoder = binary_decode.BinaryDecoder()

    @staticmethod
    def _encode_address(callsign, ssid, is_last=False):
        """Build a 7-byte AX.25 address field for a given call/SSID."""
        padded = callsign.upper().ljust(6)[:6]
        addr = bytearray(ord(c) << 1 for c in padded)
        ssid_byte = 0x60 | ((ssid & 0x0F) << 1) | (0x01 if is_last else 0x00)
        addr.append(ssid_byte)
        return bytes(addr)

    def test_ssid_zero_renders_bare(self):
        addr = self._encode_address("APRS", 0)
        rendered, _, _ = self.decoder._get_callsign(addr)
        self.assertEqual(rendered, "APRS")

    def test_nonzero_ssid_renders_with_suffix(self):
        addr = self._encode_address("KM6VOM", 9)
        rendered, _, _ = self.decoder._get_callsign(addr)
        self.assertEqual(rendered, "KM6VOM-9")

    def test_igated_packet_has_bare_aprs_destination(self):
        """End-to-end: a packet with APRS/SSID-0 destination (as nearly every
        beacon has) must produce 'APRS', not 'APRS-0', in the TNC2 line
        destined for APRS-IS. Guards the regression that was hiding our
        gated-for-others packets from aprs.fi.
        """
        # Build an AX.25 frame: dest=APRS/0, source=KM6VOM/9, no path,
        # Control=0x03, PID=0xF0, payload='!test'
        dest = self._encode_address("APRS", 0, is_last=False)
        source = self._encode_address("KM6VOM", 9, is_last=True)
        frame = dest + source + b"\x03\xf0" + b"!test"
        kiss_frame = b"\xc0\x00" + frame + b"\xc0"

        result = self.decoder.decode_frame(kiss_frame)
        self.assertIsNotNone(result)
        self.assertEqual(result['destination'], "APRS")
        self.assertEqual(result['source'], "KM6VOM-9")

        line = self.decoder.to_tnc2(result, "N0GATE-10")
        self.assertEqual(line, "KM6VOM-9>APRS,qAR,N0GATE-10:!test")
        self.assertNotIn("APRS-0", line)


class LoginVerifiedParseTests(unittest.TestCase):
    """The guard that refuses to run on an unverified login depends on this
    parse being correct. 'unverified' contains 'verified' as a substring, so
    naive matching would silently flip the guard off — guard the guard here.
    """

    def test_verified(self):
        line = "# logresp N0CALL-10 verified, server T2SJC"
        self.assertIs(aprs_is.AsyncIGate._parse_verified(line), True)

    def test_unverified(self):
        line = "# logresp N0CALL-10 unverified, server T2SJC"
        self.assertIs(aprs_is.AsyncIGate._parse_verified(line), False)

    def test_unknown_line(self):
        self.assertIsNone(aprs_is.AsyncIGate._parse_verified("# javAPRSSrvr 5.0.6"))
        self.assertIsNone(aprs_is.AsyncIGate._parse_verified(""))

    def test_case_insensitive(self):
        self.assertIs(aprs_is.AsyncIGate._parse_verified("UNVERIFIED"), False)
        self.assertIs(aprs_is.AsyncIGate._parse_verified("Verified"), True)


if __name__ == '__main__':
    unittest.main()
