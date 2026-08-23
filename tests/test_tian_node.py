import unittest

from lore_protocol import ContentType, Frame, FrameType
from tian_node import TianNode


class TianNodeTests(unittest.TestCase):
    def move_window(self, sender: TianNode, receiver: TianNode, window: list[bytes]) -> list[bytes]:
        responses: list[bytes] = []
        for encoded in window:
            responses.extend(receiver.handle_encoded_frame(encoded))
        return responses

    def test_node_a_can_send_to_node_b(self):
        a = TianNode(1)
        b = TianNode(2)
        payload = b"hello from node A" * 40

        window = a.start_transfer(payload, ContentType.TEXT, message_id=100)
        response = self.move_window(a, b, window)
        self.assertEqual([Frame.decode(item).frame_type for item in response], [FrameType.COMPLETE])

        followup = self.move_window(b, a, response)
        self.assertEqual(followup, [])
        self.assertFalse(a.outbound_busy)
        self.assertEqual(b.pop_received_messages()[0].payload, payload)

    def test_same_node_b_can_then_send_back_to_node_a(self):
        a = TianNode(1)
        b = TianNode(2)

        first = a.start_transfer(b"A to B", ContentType.TEXT, message_id=101)
        first_response = self.move_window(a, b, first)
        self.move_window(b, a, first_response)

        second = b.start_transfer(b"B to A", ContentType.TEXT, message_id=102)
        second_response = self.move_window(b, a, second)
        self.move_window(a, b, second_response)

        self.assertEqual(a.pop_received_messages()[0].payload, b"B to A")
        self.assertEqual(b.pop_received_messages()[0].payload, b"A to B")
        self.assertFalse(a.outbound_busy)
        self.assertFalse(b.outbound_busy)

    def test_missing_data_generates_nack_and_selective_retry(self):
        a = TianNode(1)
        b = TianNode(2)
        payload = b"X" * 1000

        window = a.start_transfer(payload, ContentType.BINARY, message_id=103)
        filtered: list[bytes] = []
        for encoded in window:
            frame = Frame.decode(encoded)
            if frame.frame_type == FrameType.DATA and frame.packet_index == 3:
                continue
            filtered.append(encoded)

        response = self.move_window(a, b, filtered)
        decoded_response = [Frame.decode(item) for item in response]
        self.assertEqual(decoded_response[0].frame_type, FrameType.NACK)

        retry = self.move_window(b, a, response)
        retry_frames = [Frame.decode(item) for item in retry]
        self.assertEqual(
            [(frame.frame_type, frame.packet_index) for frame in retry_frames],
            [(FrameType.DATA, 3), (FrameType.END, 1)],
        )

        complete = self.move_window(a, b, retry)
        self.assertEqual(Frame.decode(complete[0]).frame_type, FrameType.COMPLETE)
        self.move_window(b, a, complete)
        self.assertEqual(b.pop_received_messages()[0].payload, payload)

    def test_lost_complete_recovers_when_sender_repeats_end(self):
        a = TianNode(1)
        b = TianNode(2)
        payload = b"response loss test" * 20

        initial = a.start_transfer(payload, ContentType.BINARY, message_id=104)
        complete = self.move_window(a, b, initial)
        self.assertEqual(Frame.decode(complete[0]).frame_type, FrameType.COMPLETE)

        # Simulate COMPLETE being lost: do not deliver it to A.
        repeated_end = a.retry_after_timeout()
        second_complete = self.move_window(a, b, repeated_end)
        self.assertEqual(Frame.decode(second_complete[0]).frame_type, FrameType.COMPLETE)
        self.move_window(b, a, second_complete)

        self.assertFalse(a.outbound_busy)
        messages = b.pop_received_messages()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].payload, payload)

    def test_lost_end_recovers_when_sender_repeats_end(self):
        a = TianNode(1)
        b = TianNode(2)
        payload = b"lost end" * 100

        initial = a.start_transfer(payload, ContentType.BINARY, message_id=105)
        without_end = [
            encoded
            for encoded in initial
            if Frame.decode(encoded).frame_type != FrameType.END
        ]
        response = self.move_window(a, b, without_end)
        self.assertEqual(response, [])

        repeated_end = a.retry_after_timeout()
        complete = self.move_window(a, b, repeated_end)
        self.assertEqual(Frame.decode(complete[0]).frame_type, FrameType.COMPLETE)
        self.move_window(b, a, complete)
        self.assertEqual(b.pop_received_messages()[0].payload, payload)


if __name__ == "__main__":
    unittest.main()
