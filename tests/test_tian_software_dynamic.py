import unittest
from tian_software import TianSoftware
from lore_protocol import ContentType, Frame, FrameType

class TianSoftwareDynamicTests(unittest.TestCase):
    def test_two_way_queue_and_recovery(self):
        a, b = TianSoftware(1), TianSoftware(2)
        a.queue_message(b"A" * 800, ContentType.TEXT)
        b.queue_message(b"B" * 400, ContentType.TEXT)

        window = a.begin_next_transfer(); first = True
        while a.outbound_busy:
            responses = []
            for raw in window:
                f = Frame.decode(raw)
                if first and f.frame_type == FrameType.DATA and f.packet_index in {1, 2}:
                    continue
                responses += b.handle_encoded_frame(raw)
            first = False; window = []
            for raw in responses:
                window += a.handle_encoded_frame(raw)
        self.assertEqual(b.received_messages[0].payload, b"A" * 800)

        window = b.begin_next_transfer()
        while b.outbound_busy:
            responses = []
            for raw in window:
                responses += a.handle_encoded_frame(raw)
            window = []
            for raw in responses:
                window += b.handle_encoded_frame(raw)
        self.assertEqual(a.received_messages[0].payload, b"B" * 400)

if __name__ == "__main__":
    unittest.main()
