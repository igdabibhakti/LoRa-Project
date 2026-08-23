# Troubleshooting

This guide covers common problems with the current Tian Software simulator branch.

## 1. `ModuleNotFoundError: No module named 'PIL'`

Cause: Pillow is not installed in the Python environment used by the Tian child terminals.

Recommended fix:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 lore_sim.py
```

Verify:

```bash
python3 -c "from PIL import Image; print('Pillow OK')"
```

Expected:

```text
Pillow OK
```

Important: activate the virtual environment before running `lore_sim.py`, because the launcher uses the same Python executable for the three spawned terminals.

## 2. `ModuleNotFoundError` for cryptography

Run:

```bash
python3 -m pip install -r requirements.txt
```

Verify:

```bash
python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print('cryptography OK')"
```

## 3. Panel says `waiting for A and B` forever

Example:

```text
[PANEL] listening 127.0.0.1:8765; waiting for A and B
```

This means one or both Tian Software child processes did not connect.

Check the A and B terminals for Python exceptions.

Common causes:

- missing Pillow
- missing cryptography
- wrong Python environment
- panel/node port mismatch
- a node process crashed while preparing an image

## 4. Image path not found

Quick Test checks the path before saving the scenario.

Use an absolute path if unsure:

```bash
realpath ~/Pictures/test.png
```

Then paste that result.

Remember that `~` expansion works in the Quick Test input because Python expands the user path.

## 5. Image sends but received file is JPEG

This is expected in the current implementation.

Image mode does:

```text
input -> RGB -> max 240x240 -> JPEG quality 50 -> zlib -> encrypt
```

The receiver saves the reconstructed processed JPEG.

It is not intended to preserve the original PNG file byte-for-byte.

## 6. Message seems too small to test packet loss

Text mode now sends the real message once.

A short text may produce only one DATA frame.

If you configure:

```text
5
```

but the message has only DATA index 0, packet 5 cannot be dropped because it is not present.

Use:

- a longer text, or
- an image that produces more DATA frames.

Watch the sender trace:

```text
DATA index=0 total=7
```

to see how many DATA indexes actually exist.

## 7. Why manual loss index is ignored

Manual loss is intersected with the DATA indexes actually present in the current TX window.

Example:

```text
retry window = [2,5]
configured manual loss = [1,2,5]
```

Only 2 and 5 are candidates because DATA 1 was not transmitted in that window.

## 8. Why I see `default-2`

Example:

```text
[PANEL] SEQ 2 default-2 PASS ...
```

You did not configure enough sequences for all required retransmission windows.

After the sequence list ends, the panel uses a clean default sequence with no DATA loss.

Add more `|` stages if you want explicit control of later retries.

## 9. Why sequence numbers do not restart when B sends

Current sequence indexing is global for the simulation panel.

If A consumes sequences 1-3, B's first TX window uses sequence 4.

This is current behavior, not a bug.

Use one-direction tests for precisely controlled retry experiments, or design enough sequences for the expected global order.

## 10. Why the same side can win channel twice

The current arbitration uses randomized backoff, not strict round-robin scheduling.

After COMPLETE, channel ownership is released. Any Tian Software process with queued data may request again.

The previous winner can therefore win the next contention too.

## 11. Both-send test finished `1/1`, not `2/2`

Check how many messages were actually configured.

If you selected:

```text
1) A -> B
```

or:

```text
2) B -> A
```

only one message exists, so:

```text
DONE completed=1/1
```

is correct.

Choose:

```text
3) A and B both send
```

for two configured messages. A healthy finish should show:

```text
DONE completed=2/2
```

## 12. Why the panel terminal closes or returns to shell

The panel exits after all configured messages complete.

This is normal.

The terminal launcher appends `exec bash`, so the terminal window usually remains open at a shell prompt for inspection.

## 13. Address already in use / port 8765 busy

A previous panel may still be running.

On Linux:

```bash
ss -ltnp | grep 8765
```

or:

```bash
lsof -i :8765
```

Stop the old process, then restart.

## 14. Node gets connection refused

The panel is not listening yet or crashed.

Run the panel first when starting processes manually:

```bash
python3 -m simulation.panel --scenario simulation/scenarios/example.json
```

Then A and B.

## 15. Automatic three-terminal launcher does not work

The launcher searches for:

```text
konsole
gnome-terminal
xterm
```

If none is available, run manually:

```bash
python3 -m simulation.panel --scenario simulation/scenarios/example.json
```

```bash
python3 -m simulation.node_process --name A --id 1
```

```bash
python3 -m simulation.node_process --name B --id 2
```

For the current live mode, the Panel process is:

```bash
python3 -m simulation.live_panel --scenario simulation/scenarios/live_channel.json
```

and the two endpoints are `simulation.interactive_node`.

## 16. KDE/Konsole opens but child process uses wrong Python

Activate the venv before starting:

```bash
source .venv/bin/activate
which python3
python3 lore_sim.py
```

`launch_three_terminals.py` uses `sys.executable`, so it should propagate the Python executable running the launcher.

The live launcher also uses the current `sys.executable`.

## 17. `CRC mismatch`

`Frame.decode()` detected corrupted encoded data.

At unit-test level this is expected when corruption is deliberately injected.

For future real RF use, corrupt frames should be caught, logged, discarded, and recovered through normal missing-DATA/NACK behavior.

The current live simulator is not yet hardened around arbitrary malformed incoming frame exceptions.

## 18. Lost END causes timeout

This is expected.

If END is deliberately dropped:

```text
sender waits for NACK/COMPLETE
no response arrives
~1.2 s runtime timeout
sender retries END
```

The receiver then evaluates already-stored DATA.

## 19. Lost NACK causes timeout

Also expected.

Sender does not know the NACK existed, so it retries END. Receiver recalculates the same missing indexes and sends NACK again.

## 20. Lost COMPLETE causes timeout

Expected.

Sender retries END. Receiver already has the whole message and sends COMPLETE again.

## 21. Random test is different every run

You left the random seed blank.

Enter a fixed number such as:

```text
48291
```

when you want reproducible random contention/loss behavior.

## 22. Same seed still seems confusing

A seed controls a deterministic pseudorandom sequence, but the actual choices depend on the order in which random numbers are requested.

Changing the scenario, number of messages, contention order, or sequence structure can change later random results even with the same seed.

For reproducibility, keep both scenario and seed unchanged.

## 23. `random:3` selected fewer than three indexes

The current panel clamps the requested count to the number of DATA frames present in that TX window.

Example:

```text
window contains [2,5]
random:3
```

can only choose two frames.

## 24. Receiver text is encrypted garbage

That should not occur during a normal same-branch run because both sides use the same demo AES key and payload format.

Possible causes:

- mismatched code versions on A and B
- modified `SHARED_KEY`
- corrupted payload that somehow bypassed frame validation
- manually using incompatible payload data with `ContentType.TEXT`

Make sure A and B run from the same checkout.

## 25. AES key warning

The current hard-coded key in `tian_payload.py` is only for development/testing.

Do not treat it as secure production key management.

## 26. Tests fail after editing code

Run the full suite:

```bash
python3 -m unittest discover -s tests -v
```

If protocol tests fail, inspect `lore_protocol.py` first.

If payload tests fail, inspect `tian_payload.py` and dependencies.

If serial tests fail, inspect `serial_transport.py`.

## 27. Quick diagnostic commands

Environment:

```bash
which python3
python3 --version
python3 -m pip --version
python3 -m pip list | grep -E 'Pillow|cryptography|pyserial'
```

Files:

```bash
ls -la
ls -la simulation
ls -la simulation/scenarios
```

Port:

```bash
ss -ltnp | grep 8765
```

Tests:

```bash
python3 -m unittest discover -s tests -v
```

## 28. If a simulation appears stuck

Inspect all three terminals and answer these questions:

```text
Did A connect?
Did B connect?
Was a message queued?
Did a side REQUEST_CHANNEL?
Did the panel GRANT someone?
Was END delivered?
Was NACK/COMPLETE delivered?
Did sender timeout and retry END?
Did the panel release channel after COMPLETE?
```

Those lines usually identify which state stopped progressing.

---

## 29. Sender is slow but receiver suddenly bursts after END

This was the behavior of an earlier live Panel implementation that buffered all DATA until END.

Current live mode should **not** do this.

Expected current behavior with `/delay slow`:

```text
A TX DATA 0
Panel PASS/DROP DATA 0
B RX DATA 0 if passed

~0.25 s later

A TX DATA 1
Panel PASS/DROP DATA 1
B RX DATA 1 if passed
```

If the receiver still bursts after END, make sure you are running the latest branch and that live mode launches:

```text
simulation.live_panel
```

not an older checkout.

## 30. `/delay` seems to slow messages instead of packets

Current meaning:

```text
/delay = actual inter-frame transmission delay
```

Examples:

```text
/delay normal      0 s
/delay slow        0.25 s
/delay very-slow   1 s
/delay 0.5         custom 0.5 s
```

Scenario message/action timing is now controlled by:

```text
/pacing
```

Do not use `/pacing` when you are trying to slow DATA packets themselves.

## 31. Scenario builder menu ignores my number or steals text

This was caused by two Python `input()` calls reading the same terminal simultaneously.

Current code fixes this by giving the stdin worker exclusive ownership of keyboard input.

When you run:

```text
A> /scenario make
```

or:

```text
B> /scenario make
```

the same stdin thread temporarily owns the entire builder interaction.

If you still see input being stolen, verify you are running the latest `simulation/interactive_node.py` from this branch.

## 32. How do I create packet loss without editing JSON?

Use the Panel terminal, not Tian A/B:

```text
PANEL> /scenario make
```

Tian A/B node scenarios describe **what to send**.

The Panel channel scenario describes **what happens to frames**.

See:

```text
docs/CHANNEL_SCENARIO_BUILDER.md
```

## 33. What do Drop END / Drop NACK / Drop COMPLETE mean?

They inject loss of protocol-control frames.

### Drop END

Receiver does not see the sender's window boundary. Sender eventually times out and retries END.

### Drop NACK

Receiver detects missing DATA and sends NACK, but sender never receives it. Sender times out and retries END; receiver sends NACK again.

### Drop COMPLETE

Receiver has the whole message and sends COMPLETE, but sender never receives it. Sender times out and retries END; receiver sends COMPLETE again.

For a basic random-DATA-loss test, normally leave all three as `no`.

## 34. Random exact count in live streaming mode

The live Panel no longer needs to buffer DATA to choose an exact random count.

Initial window:

```text
first DATA tells Panel total_packets
Panel preselects exactly N indexes
DATA is then streamed PASS/DROP immediately
```

Retransmission window:

```text
Panel observes delivered NACK indexes
those indexes become the expected retry set
Panel can preselect exactly N retry losses
```

If requested `N` is larger than the number of available indexes, it is clamped to the available count.

## 35. Panel scenario switching during a transfer

Do not intentionally switch the channel scenario halfway through an active reliable transaction.

Finish the current DATA/END/NACK/COMPLETE transaction, then select the next scenario.

Commands:

```text
PANEL> /scenario list
PANEL> /scenario select <number>
PANEL> /scenario preview
```

## 36. Panel metadata is too verbose

Use:

```text
/metadata off
```

for concise Panel output.

Use:

```text
/metadata current
```

to inspect only the latest snapshot once.

Use:

```text
/metadata on
```

only when you want full sequence metadata continuously.

## 37. Why node output uses `[EXPRIMT]`

`[EXPRIMT]` is the shortened prefix for high-level experiment/process summaries.

Per-frame protocol direction remains prioritized as:

```text
[TX] DATA ...
[RX] DATA ...
[TX] END ...
[RX] NACK ...
[RX] COMPLETE ...
```

The node intentionally avoids printing each frame twice as both an experiment row and a TX/RX row.

## 38. Recommended first live reliability test

Use an image large enough to create many DATA frames.

On both Tian terminals:

```text
/delay slow
```

On Panel create/select:

```text
Sequence 1:
random exact DATA loss = 6
Drop END = no
Drop NACK = no
Drop COMPLETE = no

Sequence 2:
DATA loss = none
all control drops = no
```

Then verify:

```text
sender TX progresses gradually
Panel PASS/DROP follows each packet
receiver RX follows each passed packet
END arrives
receiver sends NACK for missing indexes
sender selectively retransmits
receiver sends COMPLETE
channel releases
```
