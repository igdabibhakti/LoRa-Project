# Chat UI & Image Preview Update

Branch: `feature/chat-ui-image-preview`

This update adds a human-facing chat/image layer to the live two-node Tian simulation while preserving the existing experiment/protocol logs and their original order.

## 1. Chat-only display mode

Each node can hide backend experiment output and behave like a simple messaging terminal.

```text
/logs off
/logs on
/logs status
/logs last
```

- `/logs off` hides protocol/backend output from the node terminal.
- `/logs on` restores the full experiment output.
- `/logs status` shows the current display mode.
- `/logs last` replays the captured backend log for the latest chat/transfer.

Chat-only mode is a display filter only. Tian still performs encoding, packetization, channel access, DATA/END/NACK/COMPLETE handling, retransmission, decoding, and all existing log generation. Hidden logs remain captured in chronological order for later inspection.

Normal text can still be typed directly at the node prompt. Images are sent with:

```text
/image /path/to/image.png
```

Example chat-only interaction:

```text
A> gas
[CHAT] You: gas
[CHAT] Node 2: laperrr
A> /image ~/Pictures/test.png
[CHAT] You sent image: test.png
```

The Panel remains the experiment/control terminal.

## 2. Start directly in chat-only mode

The three-terminal launcher starts `simulation.chat_node` for Node A and Node B.

Normal launch:

```bash
python -m simulation.launch_live_terminals
```

Start both nodes in chat-only mode:

```bash
python -m simulation.launch_live_terminals --chat-only
```

The original `simulation.interactive_node` module remains available as the full-debug node entry point.

## 3. Inspect the backend after chatting

A useful normal-user testing workflow is:

1. Put the nodes in chat-only mode with `/logs off`.
2. Talk normally or send images.
3. Observe whether the user-facing content arrives correctly.
4. Run `/logs last` if you want to inspect what happened underneath.
5. Return to full researcher/debug view with `/logs on`.

The existing backend log ordering is not rearranged by the chat layer.

## 4. Per-node received image folders

Received images are separated by node:

```text
received/
├── node_A/
└── node_B/
```

An image received by Node A is stored under `received/node_A/`, while one received by Node B is stored under `received/node_B/`.

## 5. Original image filename preservation

Earlier simulation versions did not transmit the source filename, so the receiver had to create generated names.

This update places filename metadata inside Tian's encrypted application payload. The reliability protocol (`DATA`, `END`, `NACK`, `COMPLETE`) does not need to know about filenames.

For example, if Node A sends:

```text
statue of liberty.jpg
```

Node B stores it as:

```text
received/node_B/statue of liberty.jpg
```

Only the basename is accepted on receive, preventing a transmitted path from escaping the node's receive directory.

### Image format note

Tian's experimental image pipeline still resizes/compresses the visual before transmission and uses a JPEG-based internal representation. When the original filename uses a common non-JPEG extension such as `.png`, the receiver re-encodes the received visual into that format before saving it under the original filename.

Old image payloads without filename metadata remain compatible and fall back to a generated receive name.

## 6. Terminal image preview

Received images can be previewed in the node terminal using an external renderer.

```text
/image-preview auto
/image-preview chafa
/image-preview viu
/image-preview off
/image-preview status
```

`/preview` is an alias for `/image-preview`.

### Auto mode

`auto` tries renderers in this order:

1. `chafa`
2. `viu`
3. filename/path-only fallback

If neither renderer is installed, image delivery still succeeds and the saved path is shown.

### Chafa

Recommended for the current KDE/Konsole-oriented workflow.

On Debian/Ubuntu/Pop!_OS based systems:

```bash
sudo apt update
sudo apt install chafa
```

Test it manually with:

```bash
chafa image.jpg
```

Then use:

```text
/image-preview auto
```

or:

```text
/image-preview chafa
```

### viu

If `viu` is installed, force it with:

```text
/image-preview viu
```

## 7. Preview fallback behavior

Image preview is only a user-interface feature after Tian has decoded and saved the file. It is not part of the LoRa reliability protocol.

```text
receive/decode image
        |
        v
save to received/node_A or node_B
        |
        v
try configured terminal renderer
        |
        +--> renderer exists -> show preview
        |
        +--> renderer unavailable -> show saved path
```

A missing image renderer therefore never causes the actual Tian transfer to fail.

## 8. Research/debug behavior remains available

This update intentionally does not redesign the existing protocol logger. Encoding traces, packet/frame details, retransmission information, delays, scenario playback, packet-loss simulation, and decoding traces remain underneath the chat display layer.

The two views are therefore:

```text
NORMAL USER VIEW
text + image conversation

        and

RESEARCH / DEBUG VIEW
encode -> packets -> channel -> loss -> NACK -> retransmission -> COMPLETE -> decode
```

Use `/logs off` and `/logs on` to move between them without restarting the simulation.
