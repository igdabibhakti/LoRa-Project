import io
import unittest

from lore_protocol import ContentType, make_data_frames
from serial_transport import (
    FramedSerialTransport,
    SerialTransportError,
    decode_serial_envelope,
    encode_serial_envelope,
)


class MemoryStream(io.BytesIO):
    def flush(self) -> None:
        pass


class SerialTransportTests(unittest.TestCase):
    def test_envelope_round_trip(self):
        frame = make_data_frames(
            b"hello",
            ContentType.TEXT,
            source_node_id=1,
            message_id=1,
        )[0].encode()
        envelope = encode_serial_envelope(frame)
        self.assertEqual(decode_serial_envelope(envelope), frame)

    def test_transport_reads_one_complete_frame(self):
        frame = make_data_frames(
            b"payload",
            ContentType.BINARY,
            source_node_id=1,
            message_id=2,
        )[0].encode()
        stream = MemoryStream(encode_serial_envelope(frame))
        transport = FramedSerialTransport(stream)
        self.assertEqual(transport.receive_frame(), frame)

    def test_invalid_length_is_rejected(self):
        with self.assertRaises(SerialTransportError):
            decode_serial_envelope(b"\x00\x05abc")


if __name__ == "__main__":
    unittest.main()
