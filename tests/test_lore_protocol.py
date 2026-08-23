import unittest

from lore_protocol import (
    CHUNK_SIZE,
    HEADER_SIZE,
    ContentType,
    Frame,
    FrameType,
    ProtocolError,
    ReceiveSession,
    SenderSession,
    decode_missing_indexes,
    make_data_frames,
    simulate_half_duplex_transfer,
)


class FrameTests(unittest.TestCase):
    def test_header_has_documented_size(self):
        self.assertEqual(HEADER_SIZE, 16)

    def test_frame_round_trip(self):
        original = Frame(
            frame_type=FrameType.DATA,
            content_type=ContentType.TEXT,
            source_node_id=7,
            message_id=0x428F983A,
            total_packets=300,
            packet_index=299,
            payload=b"hello",
        )
        self.assertEqual(Frame.decode(original.encode()), original)

    def test_crc_detects_corruption(self):
        packet = bytearray(
            Frame(
                frame_type=FrameType.DATA,
                content_type=ContentType.BINARY,
                source_node_id=1,
                message_id=1,
                total_packets=1,
                packet_index=0,
                payload=b"payload",
            ).encode()
        )
        packet[-3] ^= 0x01
        with self.assertRaisesRegex(ProtocolError, "CRC mismatch"):
            Frame.decode(bytes(packet))

    def test_payload_cannot_exceed_radio_protocol_limit(self):
        with self.assertRaisesRegex(ProtocolError, "maximum is 180"):
            Frame(
                frame_type=FrameType.NACK,
                content_type=ContentType.BINARY,
                source_node_id=1,
                message_id=1,
                total_packets=1,
                packet_index=0,
                payload=b"A" * 182,
            )

    def test_packet_index_is_16_bit_not_8_bit(self):
        payload = bytes(range(256)) * 220
        frames = make_data_frames(
            payload,
            ContentType.BINARY,
            source_node_id=1,
            message_id=9,
        )
        self.assertGreater(len(frames), 256)
        encoded = frames[256].encode()
        self.assertEqual(Frame.decode(encoded).packet_index, 256)


class ReliabilityTests(unittest.TestCase):
    def test_receiver_detects_missing_packets(self):
        frames = make_data_frames(
            b"A" * (CHUNK_SIZE * 8),
            ContentType.BINARY,
            message_id=105,
        )
        receiver = ReceiveSession.from_frame(frames[0])
        for index in (1, 2, 4, 5, 7):
            receiver.accept(frames[index])

        self.assertEqual(receiver.missing_indexes(), [3, 6])
        nack = receiver.response_frames(responder_node_id=2)
        self.assertEqual(len(nack), 1)
        self.assertEqual(nack[0].frame_type, FrameType.NACK)
        self.assertEqual(decode_missing_indexes(nack[0].payload), [3, 6])

    def test_sender_only_retransmits_nacked_packets_then_end(self):
        frames = make_data_frames(
            b"A" * (CHUNK_SIZE * 8),
            ContentType.BINARY,
            message_id=105,
        )
        sender = SenderSession(frames)
        sender.initial_window()

        receiver = ReceiveSession.from_frame(frames[0])
        for index in (1, 2, 4, 5, 7):
            receiver.accept(frames[index])
        response = receiver.response_frames(responder_node_id=2)
        retry_window = sender.handle_response(response)

        self.assertEqual(
            [(frame.frame_type, frame.packet_index) for frame in retry_window],
            [
                (FrameType.DATA, 3),
                (FrameType.DATA, 6),
                (FrameType.END, 1),
            ],
        )

    def test_half_duplex_simulation_recovers_data_loss(self):
        payload = bytes(range(256)) * 5
        result = simulate_half_duplex_transfer(
            payload,
            ContentType.BINARY,
            message_id=105,
            drop_data_once={3, 6},
        )
        self.assertEqual(result.reconstructed_payload, payload)
        self.assertEqual(result.retransmission_rounds, 1)
        self.assertTrue(
            any(event.frame_type == FrameType.NACK for event in result.events)
        )
        self.assertEqual(result.events[-1].frame_type, FrameType.COMPLETE)

    def test_lost_end_is_repeated_after_timeout(self):
        payload = b"test" * 200
        result = simulate_half_duplex_transfer(
            payload,
            ContentType.BINARY,
            message_id=1,
            drop_first_end=True,
        )
        self.assertEqual(result.reconstructed_payload, payload)
        end_events = [
            event for event in result.events if event.frame_type == FrameType.END
        ]
        self.assertEqual(len(end_events), 2)
        self.assertFalse(end_events[0].delivered)
        self.assertTrue(end_events[1].delivered)

    def test_lost_response_is_repeated_after_timeout(self):
        payload = b"test" * 200
        result = simulate_half_duplex_transfer(
            payload,
            ContentType.BINARY,
            message_id=1,
            drop_first_response=True,
        )
        self.assertEqual(result.reconstructed_payload, payload)
        complete_events = [
            event
            for event in result.events
            if event.frame_type == FrameType.COMPLETE
        ]
        self.assertEqual(len(complete_events), 2)
        self.assertFalse(complete_events[0].delivered)
        self.assertTrue(complete_events[1].delivered)

    def test_large_nack_is_split_into_pages(self):
        frames = make_data_frames(
            b"A" * (CHUNK_SIZE * 200),
            ContentType.BINARY,
            message_id=7,
        )
        receiver = ReceiveSession.from_frame(frames[199])
        nacks = receiver.response_frames(responder_node_id=2)
        self.assertEqual(len(nacks), 3)
        self.assertEqual([frame.packet_index for frame in nacks], [0, 1, 2])
        self.assertTrue(all(frame.total_packets == 3 for frame in nacks))

    def test_source_node_cannot_change_mid_message(self):
        frames = make_data_frames(
            b"A" * (CHUNK_SIZE * 2),
            ContentType.BINARY,
            source_node_id=1,
            message_id=7,
        )
        receiver = ReceiveSession.from_frame(frames[0])
        wrong_source = Frame(
            frame_type=FrameType.DATA,
            content_type=ContentType.BINARY,
            source_node_id=99,
            message_id=7,
            total_packets=2,
            packet_index=1,
            payload=frames[1].payload,
        )
        with self.assertRaisesRegex(ProtocolError, "source node changed"):
            receiver.accept(wrong_source)

    def test_simulator_rejects_out_of_range_drop_index(self):
        with self.assertRaisesRegex(ProtocolError, "outside this message"):
            simulate_half_duplex_transfer(
                b"one packet",
                ContentType.BINARY,
                drop_data_once={3},
            )


if __name__ == "__main__":
    unittest.main()
