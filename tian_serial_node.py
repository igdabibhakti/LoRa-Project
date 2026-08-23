"""Interactive bidirectional Tian node over a framed serial link.

The same program runs at both ends. Each instance can initiate transfers and
receive transfers. The serial peer can later be an ESP32 bridge implementing the
same 2-byte length-prefixed envelope from serial_transport.py.
"""

from __future__ import annotations

import argparse
import threading
import time

import serial

from lore_protocol import ContentType, Frame, FrameType, ProtocolError
from serial_transport import FramedSerialTransport, SerialTransportError
from tian_node import TianNode


class TianSerialRuntime:
    def __init__(
        self,
        node_id: int,
        port: str,
        baudrate: int,
        response_timeout: float,
    ) -> None:
        self.node = TianNode(node_id)
        self.response_timeout = response_timeout
        self.serial = serial.Serial(port, baudrate=baudrate, timeout=0.5)
        self.transport = FramedSerialTransport(self.serial)
        self.running = True
        self.tx_lock = threading.Lock()
        self.last_tx_time = 0.0

    def trace(self, direction: str, encoded: bytes, note: str = "") -> None:
        frame = Frame.decode(encoded)
        if frame.frame_type == FrameType.DATA:
            detail = f"DATA #{frame.packet_index}/{frame.total_packets - 1}"
        elif frame.frame_type == FrameType.NACK:
            detail = f"NACK page #{frame.packet_index}/{frame.total_packets - 1}"
        elif frame.frame_type == FrameType.END:
            detail = f"END round={frame.packet_index}"
        else:
            detail = frame.frame_type.name
        suffix = f" {note}" if note else ""
        stamp = time.strftime("%H:%M:%S")
        print(
            f"[{stamp}] {direction:<2} node={frame.source_node_id:<5} "
            f"msg=0x{frame.message_id:08X} {detail}{suffix}"
        )

    def send_window(self, frames: list[bytes], note: str = "") -> None:
        with self.tx_lock:
            for encoded in frames:
                self.trace("TX", encoded, note)
                self.transport.send_frame(encoded)
            if frames:
                self.last_tx_time = time.monotonic()

    def receiver_loop(self) -> None:
        while self.running:
            try:
                encoded = self.transport.receive_frame()
            except SerialTransportError:
                continue
            except (OSError, serial.SerialException) as exc:
                if self.running:
                    print(f"[SERIAL ERROR] {exc}")
                break

            try:
                self.trace("RX", encoded)
                response = self.node.handle_encoded_frame(encoded)
                if response:
                    self.send_window(response, "protocol response")
                self._print_received_messages()
            except ProtocolError as exc:
                print(f"[PROTOCOL ERROR] {exc}")

    def timeout_loop(self) -> None:
        while self.running:
            time.sleep(0.1)
            if not self.node.outbound_busy or not self.last_tx_time:
                continue
            if time.monotonic() - self.last_tx_time < self.response_timeout:
                continue
            try:
                retry = self.node.retry_after_timeout()
                self.send_window(retry, "response timeout -> repeat END")
            except ProtocolError as exc:
                print(f"[TIMEOUT ERROR] {exc}")

    def _print_received_messages(self) -> None:
        for message in self.node.pop_received_messages():
            if message.content_type == ContentType.TEXT:
                try:
                    value = message.payload.decode("utf-8")
                except UnicodeDecodeError:
                    value = repr(message.payload)
                print(
                    f'\n[RECEIVED TEXT] from node {message.source_node_id} '
                    f'msg=0x{message.message_id:08X}: "{value}"\n'
                )
            else:
                print(
                    f"\n[RECEIVED {message.content_type.name}] "
                    f"from node {message.source_node_id} "
                    f"msg=0x{message.message_id:08X}: {len(message.payload)} bytes\n"
                )

    def send_text(self, text: str) -> None:
        window = self.node.start_transfer(text.encode("utf-8"), ContentType.TEXT)
        self.send_window(window, "new transfer")

    def run(self) -> None:
        print(
            f"Tian Node {self.node.node_id} connected to {self.serial.port} "
            f"at {self.serial.baudrate} baud"
        )
        print("Commands: send <text> | status | quit")
        print("Do not start transfers from both nodes simultaneously yet.\n")

        receiver = threading.Thread(target=self.receiver_loop, daemon=True)
        timeout_worker = threading.Thread(target=self.timeout_loop, daemon=True)
        receiver.start()
        timeout_worker.start()

        try:
            while self.running:
                command = input(f"node-{self.node.node_id}> ").strip()
                if not command:
                    continue
                if command == "quit":
                    break
                if command == "status":
                    print(
                        "outbound="
                        + ("WAITING_FOR_RESPONSE" if self.node.outbound_busy else "IDLE")
                    )
                    continue
                if command.startswith("send "):
                    try:
                        self.send_text(command[5:])
                    except ProtocolError as exc:
                        print(f"[ERROR] {exc}")
                    continue
                print("Unknown command. Use: send <text> | status | quit")
        finally:
            self.running = False
            self.serial.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bidirectional Tian LoRe serial node")
    parser.add_argument("--node-id", type=int, required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--response-timeout", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = TianSerialRuntime(
        node_id=args.node_id,
        port=args.port,
        baudrate=args.baud,
        response_timeout=args.response_timeout,
    )
    runtime.run()


if __name__ == "__main__":
    main()
