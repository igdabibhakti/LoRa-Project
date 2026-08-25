# Simulation Haul Up

Branch: `simulation-haul-up`

This branch adds a human-facing chat/image layer to the live two-node Tian simulation while preserving the existing experiment/protocol logs and their order.

## What changed

### 1. Chat-only display mode

Each node can hide backend experiment output and behave more like a simple messaging terminal.

Commands:

```text
/logs off
/logs on
/logs status
/logs last
```

- `/logs off` hides protocol/backend output from the node terminal.
- `/logs on` restores the existing full experiment output.
- `/logs status` shows the current display mode.
- `/logs last` replays the captured backend log for the latest chat/transfer.

Important: chat-only mode is a **display filter only**. Tian still performs encoding, packetization, channel access, DATA/END/NACK/COMPLETE handling, retransmission, decoding, and all existing log generation. Hidden logs are kept in their original chronological order so they can be inspected afterward.

Normal text can still be typed directly at the node prompt. Images are still sent with:

```text
/image /path/to/image.png
```

A typical chat-only node looks conceptually like:

```text
A> gas
[CHAT] You: gas
[CHAT] Node 2: laperrr
A> /image ~/Pictures/test.png
[CHAT] You sent image: test.png
```

The Panel remains an experiment/control terminal and is not changed into chat-only mode.

## 2. Start directly in chat-only mode

The three-terminal launcher now starts `simulation.chat_node` for Node A and Node B.

Normal launch:

```bash
python -m simulation.launch_live_terminals
```

Start both nodes in chat-only mode immediately:

```bash
python -m simulation.launch_live_terminals --chat-only
```

You can switch modes at any time independently on each node:

```text
/logs off
/logs on
```

The original `simulation.interactive_node` module is still present as the legacy/full-debug node entry point.

## 3. Inspect the backend after chatting

When testing the system as two normal users, keep the nodes in chat-only mode:

```text
/logs off
```

After a message or image transfer, run:

```text
/logs last
```

The node prints the stored experiment/backend output for the latest transfer. The existing log ordering is not rearranged by the chat layer.

This is useful for a workflow such as:

1. Talk normally between Node A and Node B.
2. Observe whether the user-facing message/image arrives correctly.
3. Run `/logs last` only when something interesting happens.
4. Inspect the exact protocol behavior, retransmission, NACK, timeout, encode/decode information, etc.

## 4. Per-node received image folders

Received images are separated by node:

```text
received/
├── node_A/
└── node_B/
```

So an image received by Node A is stored under:

```text
received/node_A/
```

and an image received by Node B is stored under:

```text
received/node_B/
```

This prevents both simulated users from mixing received files in one folder.

## 5. Original image filename is transmitted

Previous simulation versions did not transmit the source filename. The receiver therefore had to create names such as:

```text
node_B_from_1_7B6EAE8A.jpg
```

The haul-up branch adds filename metadata to Tian's **encrypted application payload**. The reliability protocol (`DATA`, `END`, `NACK`, `COMPLETE`) does not need to know about the filename.

For example, if Node A sends:

```text
statue of liberty.jpg
```

Node B stores it as:

```text
received/node_B/statue of liberty.jpg
```

Only the basename is accepted on receive, preventing a transmitted filename from escaping the node's receive directory.

### Image format note

Tian's experimental image pipeline still resizes/compresses the visual before transmission. Internally the transport representation is JPEG-based. When the original filename has a common non-JPEG extension such as `.png`, the receiver re-encodes the received visual into that format before saving it under the original filename.

This preserves a valid file/extension relationship rather than writing JPEG bytes into a `.png` file.

Old image payloads that do not contain filename metadata are still accepted and fall back to the generated receive name.

## 6. Terminal image preview

Received images can be previewed in the node terminal using an external renderer.

Commands:

```text
/image-preview auto
/image-preview chafa
/image-preview viu
/image-preview off
/image-preview status
```

`/preview` is also accepted as an alias for `/image-preview`.

### Auto mode

`auto` tries renderers in this order:

1. `chafa`
2. `viu`
3. filename/path-only fallback

If neither renderer is installed, the image is still received and saved normally. The node simply prints the saved path.

### Chafa (recommended for KDE/Konsole)

On Debian/Ubuntu/Pop!_OS based systems:

```bash
sudo apt update
sudo apt install chafa
```

Test manually:

```bash
chafa image.jpg
```

Then use:

```text
/image-preview auto
```

or force it:

```text
/image-preview chafa
```

### viu

If `viu` is installed, the node can use it as another terminal renderer:

```text
/image-preview viu
```

The program checks whether the requested executable exists before trying to launch it.

## 7. Why image preview has a fallback

Image preview is not part of the LoRa/Tian reliability protocol. It is only a user-interface feature after a file has been decoded successfully.

Therefore a missing or unsupported renderer must never break message delivery.

The behavior is:

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
        +--> renderer unavailable -> print saved path only
```

The saved image remains the source of truth.

## 8. Recommended normal-user test

Start the simulation in chat mode:

```bash
python -m simulation.launch_live_terminals --chat-only
```

In Node A:

```text
A> hello B
```

In Node B:

```text
B> hello A
```

Send an image:

```text
A> /image ~/Pictures/test.png
```

After the transfer, inspect what happened underneath:

```text
A> /logs last
```

or on the receiving node:

```text
B> /logs last
```

Return to the researcher/debug view at any time:

```text
/logs on
```

## 9. Existing experiment behavior

This feature intentionally does **not** redesign the protocol logger. Existing log generation, transmission detail, encode/decode traces, delay behavior, scenario playback, and packet-loss simulation remain underneath the chat display layer.

The goal is to provide two views of the same experiment:

```text
NORMAL USER VIEW
text + image conversation

        and

RESEARCH / DEBUG VIEW
encode -> packets -> channel -> loss -> NACK -> retransmission -> COMPLETE -> decode
```

Use `/logs off` and `/logs on` to move between them without restarting the simulation.
