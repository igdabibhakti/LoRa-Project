# Panel Channel Scenario Builder

This guide explains the terminal-only channel scenario builder used by the live simulator.

The builder exists so packet-loss experiments can be created without manually editing JSON.

## 1. Node scenario vs channel scenario

Keep these two concepts separate:

```text
NODE SCENARIO
= what Tian A or Tian B wants to send
= text, image, action order, action timing

CHANNEL SCENARIO
= what the simulated shared LoRa medium does
= DATA loss, END loss, NACK loss, COMPLETE loss,
  random seed, contention window, randomized backoff
```

Use the node terminal for a node scenario:

```text
A> /scenario make
B> /scenario make
```

Use the Panel terminal for a channel scenario:

```text
PANEL> /scenario make
```

## 2. Panel scenario commands

The enhanced live Panel supports:

```text
/scenario
/scenario status
/scenario list
/scenario preview
/scenario select <number|name|path>
/scenario make

/protocol ...
```

`/protocol` is an alias for `/scenario`.

Examples:

```text
PANEL> /scenario list
PANEL> /scenario select 2
PANEL> /scenario preview
PANEL> /scenario make
```

Saved scenarios are placed under:

```text
simulation/scenarios/channels/
```

Saving always creates a new JSON file. Existing files are never overwritten.

## 3. Builder menu

Run:

```text
PANEL> /scenario make
```

The menu is:

```text
--- CHANNEL BUILDER MENU ---
1) Preview draft
2) Add transmission sequence
3) Edit a transmission sequence
4) Delete a transmission sequence
5) Set random seed
6) Set contention / backoff settings
7) Rename scenario title
8) SAVE AS NEW JSON + PRELOAD IT
9) Cancel without saving
```

If a channel scenario is already loaded, the builder can copy it into a new draft or start blank.

## 4. What a transmission sequence means

A sequence describes one sender transmission window and the control response associated with that window.

Initial window example:

```text
DATA 0
DATA 1
DATA 2
...
END round=0
```

If DATA is missing, the receiver responds with NACK and the next sender window is a retransmission:

```text
requested DATA only
END round=1
```

Each sender END window consumes the next Panel sequence globally.

If the configured list runs out, the Panel falls back to a clean default sequence.

## 5. DATA loss modes

When adding/editing a sequence, the builder asks:

```text
DATA loss mode:
1) None
2) Manual packet indexes
3) Random exact count
4) Random probability
```

### None

```text
DATA loss = none
```

All DATA frames in that window are passed.

### Manual packet indexes

Example:

```text
1,5,8
```

Packet indexes are zero-based.

Only indexes actually present in the current transmission window can be dropped.

### Random exact count

Example:

```text
count = 6
```

The Panel selects exactly six DATA indexes from the expected DATA indexes for that window, subject to the number of available frames.

Initial transmission uses the DATA frame's `total_packets` field to know all possible indexes before forwarding DATA.

Retransmission uses the delivered NACK indexes to know the retry window before forwarding the retransmitted DATA.

This allows DATA to be streamed immediately instead of being buffered until END.

### Random probability

Example:

```text
20%
```

or:

```text
0.2
```

Each expected DATA index independently has the configured probability of being selected for loss.

## 6. What `Drop END` means

END means:

```text
"I finished this sender transmission window. Check what you received."
```

Normal path:

```text
Sender                  Receiver
DATA ------------------>
DATA ------------------>
END  ------------------>
                        check missing DATA
```

If `Drop END = yes`:

```text
Sender                  Panel                  Receiver
END -------------------> DROP X
```

The receiver never gets the window boundary, so it does not yet send NACK or COMPLETE.

The sender waits for a response, times out, and retries END.

Use this to test END-timeout recovery.

## 7. What `Drop NACK` means

NACK tells the sender exactly which DATA indexes are missing.

Example:

```text
NACK [2,5,9]
```

If `Drop NACK = yes`:

```text
Receiver                Panel                 Sender
NACK [2,5,9] ----------> DROP X
```

The sender hears nothing and does not know which DATA frames are missing.

It times out and retries END.

The receiver still has its receive session, checks again, and sends NACK again.

Use this to test lost-response recovery.

## 8. What `Drop COMPLETE` means

COMPLETE means:

```text
"I have the entire message. This reliable transaction is complete."
```

If `Drop COMPLETE = yes`:

```text
Receiver                Panel                 Sender
COMPLETE --------------> DROP X
```

The receiver is already complete, but the sender does not know that.

The sender times out and retries END.

Because the receiver still has the completed receive session, it answers COMPLETE again.

Use this to test final-acknowledgement loss recovery.

## 9. Recommended basic 6-random-loss experiment

For the first experiment, make two sequences.

Sequence 1:

```text
name          = lose-6-random
DATA loss     = random exact count 6
Drop END      = no
Drop NACK     = no
Drop COMPLETE = no
```

Sequence 2:

```text
name          = clean-retry
DATA loss     = none
Drop END      = no
Drop NACK     = no
Drop COMPLETE = no
```

Expected behavior:

```text
initial DATA window
    -> exactly 6 DATA frames dropped
    -> END passes
    -> receiver sends NACK with the 6 missing indexes

retry DATA window
    -> requested 6 DATA frames pass
    -> END passes
    -> receiver sends COMPLETE
    -> channel released
```

## 10. Example builder keystrokes for 6 random losses

```text
PANEL> /scenario make
```

Start blank if desired.

Add sequence:

```text
Choose: 2
Sequence name: lose-6-random
DATA loss mode: 3
How many DATA packets to lose exactly: 6
Drop END: n
Drop NACK: n
Drop COMPLETE: n
```

Add clean retry:

```text
Choose: 2
Sequence name: clean-retry
DATA loss mode: 1
Drop END: n
Drop NACK: n
Drop COMPLETE: n
```

Preview:

```text
Choose: 1
```

Save:

```text
Choose: 8
New filename: random_6_loss
```

The new file is saved and selected automatically.

## 11. Random seed

The builder can set a random seed.

Blank seed:

```text
seed = null
```

means different pseudorandom choices may be made on different runs.

Fixed seed example:

```text
seed = 12345
```

is useful for reproducible experiments, as long as the scenario and order of random operations are unchanged.

## 12. Contention settings

The Panel also stores:

```text
contention_window_ms
max_backoff_ms
```

`contention_window_ms` is how long the Panel collects near-simultaneous channel requests before choosing a winner.

`max_backoff_ms` is the upper bound for randomized contention backoff.

These values are simulation/MAC controls, not LoRe frame fields.

## 13. Streaming DATA behavior

The current live Panel forwards or drops each DATA frame immediately when it arrives.

Correct timeline with a node TX delay:

```text
A TX DATA 0
Panel PASS/DROP DATA 0
B RX DATA 0 if passed

wait sender TX delay

A TX DATA 1
Panel PASS/DROP DATA 1
B RX DATA 1 if passed
```

The Panel does not wait for END and then burst all DATA to the receiver.

END is only the protocol boundary telling the receiver to evaluate completeness.

## 14. Scenario switching safety

A newly saved or selected channel scenario is intended to become the next active channel configuration.

Do not switch channel scenarios in the middle of an active DATA/END transaction. Finish the current reliable transaction first, then switch scenarios for the next experiment.

## 15. Related documentation

Read together with:

```text
docs/LIVE_SIMULATION.md
docs/PROTOCOL.md
docs/EXPERIMENT_OBSERVABILITY.md
docs/REAL_PACKET_DELAY.md
docs/TROUBLESHOOTING.md
```
