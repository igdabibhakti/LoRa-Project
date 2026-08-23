# ESP32 Integration Guide

This document describes how the current Tian Software branch is intended to connect to an ESP32 and, later, a real LoRa radio.

## 1. Integration goal

The final physical link is intended to look like:

```text
Laptop A
  |
USB serial
  |
ESP32 A
  |
LoRa A
  |
RF
  |
LoRa B
  |
ESP32 B
  |
USB serial
  |
Laptop B
```

Tian Software continues to own the reliability protocol on the laptops.

## 2. What must stay inside Tian Software

Tian Software should continue to handle:

- text/image application preparation
- encryption/decryption
- LoRe frame creation/parsing
- DATA/END/NACK/COMPLETE
- CRC checking
- receive-session tracking
- missing-index detection
- selective retransmission
- timeout behavior
- message queue
- reconstruction and output

The reason is simple: this logic is already testable and working on the laptop. Moving it into ESP32 firmware would duplicate protocol state and make debugging harder.

## 3. What the ESP32 should do

At the simplest bridge stage, ESP32 should:

### Laptop -> radio

```text
read 2-byte serial length
read exactly N frame bytes
transmit those N bytes through LoRa
```

### Radio -> laptop

```text
receive one LoRa packet
measure received byte count N
write 2-byte big-endian N
write N frame bytes to USB serial
```

The ESP32 should treat the LoRe frame as opaque bytes.

## 4. Current serial envelope

`serial_transport.py` defines:

```text
[uint16 big-endian length][frame bytes]
```

Example for a 198-byte frame:

```text
00 C6   <198 encoded LoRe frame bytes>
```

because decimal 198 is hexadecimal `0x00C6`.

Serial length prefix size:

```text
2 bytes
```

Current configured maximum serial frame size:

```text
1024 bytes
```

Current maximum LoRe DATA frame:

```text
198 bytes
```

so the current LoRe protocol fits comfortably inside the serial envelope.

## 5. Why a length prefix is needed

USB serial is a byte stream. It does not preserve application message boundaries.

Without framing, receiving:

```text
FRAME_A bytes + FRAME_B bytes
```

would give the ESP32 no reliable way to know where A ends and B begins.

With the prefix:

```text
[length A][frame A][length B][frame B]
```

both sides can recover exact frame boundaries.

## 6. Recommended ESP32 receive state machine

For laptop serial input:

```text
WAIT_LENGTH
  |
  | receive 2 bytes
  v
READ_FRAME
  |
  | receive exactly frame_length bytes
  v
FRAME_READY
  |
  | queue/send to LoRa
  v
WAIT_LENGTH
```

Do not assume one serial `read()` returns a whole frame.

## 7. Recommended radio state behavior

One LoRa radio is half duplex.

A practical ESP32 radio state model is:

```text
RX_LISTEN
TX_FRAME
WAIT_TX_DONE
RX_LISTEN
```

When Tian Software asks to transmit an encoded frame, ESP32 temporarily leaves RX mode, sends the frame, waits for radio TX completion, then returns to RX.

## 8. Important transaction detail

The LoRe transaction alternates direction:

```text
A -> B DATA/END
B -> A NACK or COMPLETE
A -> B retry if needed
B -> A final COMPLETE
```

ESP32 therefore must switch radio direction quickly and predictably after each transmitted LoRa packet/window.

It does not need to know why a frame is DATA or NACK unless later hardware-level scheduling requires control metadata.

## 9. Channel arbitration today vs later

### Today in simulation

The panel centrally decides which side acquires the shared channel.

### Later with real hardware

A real decentralized link cannot rely on one central Python panel.

A future hardware design needs a real channel-access mechanism such as:

```text
listen / Channel Activity Detection
-> if busy, wait
-> randomized backoff
-> listen again
-> if clear, transmit transaction
```

Exact behavior depends on the LoRa transceiver/library and whether CAD/channel-busy information is available and reliable for the selected radio settings.

The current branch intentionally keeps this abstract rather than hard-coding a radio-specific solution too early.

## 10. Possible Tian <-> ESP32 control extension

The current serial transport only defines raw LoRe-frame envelopes.

For real channel arbitration, the serial link may later need a small control plane in addition to data frames.

Possible future control messages include:

```text
CHANNEL_STATUS
TX_REQUEST
TX_GRANTED / BUSY
TX_DONE
RX_FRAME
RADIO_ERROR
```

Do not add these until the chosen ESP32 LoRa module/library behavior is known.

The stable concept to preserve is that the actual encoded LoRe frame remains an opaque payload passed between Tian Software and ESP32.

## 11. First hardware milestone: no LoRa yet

Before connecting the LoRa module, test only:

```text
Laptop Tian Software
<-> USB serial
<-> ESP32
```

A useful first ESP32 firmware can simply echo complete length-prefixed frames back.

Test:

```text
Tian sends frame
ESP32 reads length + frame
ESP32 returns same length + same frame
Tian verifies bytes are identical
```

This proves serial framing independently of radio behavior.

## 12. Second hardware milestone: two ESP32s with wired/alternate bridge if useful

Next, verify that two ESP32s can move opaque frame bytes between two laptops using whatever temporary physical path is easiest.

The objective remains:

```text
encoded bytes out == encoded bytes in
```

Do not debug image compression, NACK logic, and RF at the same time if you can isolate layers first.

## 13. Third hardware milestone: LoRa raw-frame bridge

Then connect:

```text
Laptop A -> ESP32 A -> LoRa A
LoRa B -> ESP32 B -> Laptop B
```

At first use a clean single-direction test:

```text
A -> B
no deliberate simulation loss
```

Verify that B receives valid LoRe frames and CRC decode succeeds.

## 14. Fourth hardware milestone: protocol responses

After one-way raw transport works, allow B to send NACK/COMPLETE back to A.

Test:

```text
A sends message
B COMPLETE
```

Then deliberately create missing frames if possible and verify:

```text
B NACK
A selective retransmission
B COMPLETE
```

## 15. Fifth hardware milestone: both-send contention

Only after basic reliability works should both sides initiate messages.

Test:

```text
A queued
B queued
channel acquisition
winner sends one transaction
release
next queued sender acquires
```

Compare this behavior with the Python simulation reference.

## 16. ESP32 buffer requirements

The current maximum encoded LoRe DATA frame is 198 bytes.

A buffer such as:

```text
uint8_t frame[1024]
```

matches the current Python serial maximum, although a smaller carefully validated buffer can be used if desired.

Always validate the received serial length before reading into a fixed buffer.

Reject:

```text
length == 0
length > allowed maximum
```

## 17. Serial byte order

The length prefix is big-endian.

If the two received prefix bytes are:

```text
high
low
```

then:

```text
length = (high << 8) | low
```

## 18. LoRa packet-size consideration

The current maximum LoRe frame is 198 bytes, which was intentionally kept below a typical LoRa PHY payload ceiling used by many configurations/libraries.

However, actual usable LoRa payload size depends on radio chip, library, region/settings, implicit/explicit header behavior, and PHY configuration.

Before real transmission, confirm that the chosen module/library can send the full encoded LoRe frame at your selected settings.

If not, the LoRe `CHUNK_SIZE` must be reduced so an encoded frame fits safely.

## 19. CRC responsibility

ESP32 does not need to calculate the LoRe CRC if it transports the full encoded frame unchanged.

Tian Software's `Frame.decode()` verifies the application protocol CRC.

The radio itself may also have a PHY CRC. These are separate layers:

```text
LoRa PHY CRC
LoRe application-frame CRC
```

Both can be useful.

## 20. Error handling recommendation

ESP32 should distinguish at least:

```text
serial framing error
radio TX failure
radio RX failure/timeout
buffer overflow/invalid length
```

It should not silently modify frame bytes.

Tian Software should later catch malformed LoRe frames, log/drop them, and let normal reliability mechanisms recover missing DATA.

## 21. Timing

Current Python node runtime uses a response timeout of about:

```text
1.2 seconds
```

by default.

Real LoRa airtime can be much longer depending on spreading factor, bandwidth, coding rate, frame size, and duty-cycle constraints.

Therefore this timeout is a simulation/runtime value, not a guaranteed correct hardware timeout.

Before real radio testing, calculate/measure worst-case message-window and response timing and adjust timeout logic accordingly.

## 22. Regulatory/duty-cycle note

Real LoRa operation must follow the legal frequency plan, transmit power, duty-cycle/channel-access rules, and certification constraints for the country/region and radio module.

The Python simulator has no regulatory timing model.

## 23. What not to change during first ESP32 integration

Try not to redesign all layers simultaneously.

Keep these stable first:

```text
LoRe frame binary format
180-byte protocol chunk size unless radio demands smaller
DATA/END/NACK/COMPLETE semantics
Tian receive/retransmission logic
2-byte serial length envelope
```

Change only the transport underneath.

## 24. Success criteria for the ESP32 bridge

The first ESP32 milestone is successful when:

```text
1. Tian produces an encoded LoRe frame.
2. ESP32 receives exactly the same bytes over serial.
3. ESP32 can forward those bytes.
4. Remote Tian receives exactly the same encoded frame.
5. Frame.decode() succeeds.
6. Existing Tian reliability behavior works unchanged.
```

That proves the abstraction boundary is working correctly.
