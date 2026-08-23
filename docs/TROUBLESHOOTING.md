# Troubleshooting

This guide covers common problems with the current Tian Software live simulator.

## 1. Missing Python dependencies

If you see `ModuleNotFoundError` for Pillow, cryptography, or pyserial:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Verify:

```bash
python3 -c "from PIL import Image; print('Pillow OK')"
python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print('cryptography OK')"
```

Start `lore_sim.py` from the same activated environment so the spawned terminals use the same Python executable.

## 2. Panel waits forever for A and B

Check the A and B terminals for exceptions.

Common causes:

- missing dependency
- one node crashed
- port mismatch
- another old Panel is still using port 8765

Check the port:

```bash
ss -ltnp | grep 8765
```

## 3. Connection refused

Start the Panel first when launching manually.

For live mode the normal launcher now uses:

```bash
python3 -m simulation.live_panel --live --scenario simulation/scenarios/live_channel.json
```

Then start A and B.

Normally use `./RUN_ME.sh` or `python3 lore_sim.py` instead of manual startup.

## 4. Image path not found

Use an absolute path if unsure:

```bash
realpath ~/Pictures/test.png
```

The node scenario builder validates image paths when adding an image action.

## 5. Received image is JPEG instead of original PNG

Expected.

Current image path is:

```text
input image
-> RGB
-> max 240x240
-> JPEG quality 50
-> zlib
-> timestamp
-> AES-GCM
```

The receiver reconstructs the processed JPEG. Exact original-file transfer is not implemented yet.

## 6. Short text cannot test many packet losses

A short text may produce only one DATA frame.

If you want to test six random DATA losses, use an image or a sufficiently large payload with more than six DATA frames.

Watch:

```text
[TX] DATA index=... total=...
```

or the `[EXPRIMT]` transmission summary to see how many DATA frames exist.

## 7. Manual loss index is ignored

Manual DATA loss only applies to indexes actually expected in that transmission window.

Example:

```text
retry window = [2,5]
manual configured loss = [1,2,5]
```

Only 2 and 5 can be selected because DATA 1 is not transmitted in that retry window.

## 8. `random exact count` drops fewer than requested

The requested count is clamped to the number of DATA frames available in the current window.

Example:

```text
retry window = [2,5]
random exact count = 6
```

Only two DATA frames exist, so at most two can be dropped.

## 9. Receiver used to burst all DATA after sender finished

That was caused by the old Panel buffering complete DATA windows until END.

The current live Panel streams each DATA frame immediately:

```text
sender TX DATA
-> Panel PASS/DROP
-> receiver RX if passed
```

If you still see the receiver silent during all sender DATA and then receiving everything only after END, confirm you are running the latest branch and that live mode launched `simulation.live_panel`/the current `simulation.panel` engine.

## 10. `/delay slow` affects sender but receiver still looks instant

`/delay` is real inter-frame sender spacing.

Current presets:

```text
normal    0s
slow      0.25s
very-slow 1s
```

Because DATA is now streamed through the Panel, the receiver should follow those transmitted frames as they arrive.

Do not confuse this with `/pacing`, which controls spacing between scripted scenario actions/messages.

## 11. Scenario builder menu ignores my choice / repeats `Choose [1]`

An older live-node implementation had two threads calling `input()` at the same time. Keystrokes could be stolen by the normal `A>` prompt.

The current implementation gives the node `stdin_worker` exclusive keyboard ownership. `/scenario make` runs inside that same stdin thread while the network loop continues separately.

If you still reproduce the old behavior, update to the latest branch version before debugging the builder itself.

## 12. Node scenario vs channel scenario confusion

Use Tian A/B builders for what a node sends:

```text
A> /scenario make
B> /scenario make
```

Use the Panel builder for packet/channel behavior:

```text
PANEL> /scenario make
```

Node scenarios do not contain packet-loss controls.

Channel scenarios do not contain Tian text/image actions.

## 13. What does `Drop END` do?

END tells the receiver the sender finished the current TX/retry window.

If END is dropped:

```text
receiver has DATA but no END
-> receiver does not respond yet
-> sender gets no NACK/COMPLETE
-> sender timeout
-> sender retries END
```

This is expected timeout-recovery behavior.

## 14. What does `Drop NACK` do?

The receiver detects missing DATA and sends NACK, but the Panel drops it.

Expected:

```text
sender hears nothing
-> timeout
-> sender retries END
-> receiver still knows the same DATA is missing
-> receiver sends NACK again
```

## 15. What does `Drop COMPLETE` do?

Receiver already has the complete message but COMPLETE is dropped.

Expected:

```text
sender hears nothing
-> timeout
-> sender retries END
-> receiver remains complete
-> receiver sends COMPLETE again
```

See `docs/CHANNEL_SCENARIO_BUILDER.md` for diagrams and builder examples.

## 16. Why do I see `default-N` sequences?

The configured channel sequence list ended before the experiment finished.

After configured sequences are exhausted, the Panel uses clean default channel behavior for later windows.

For a controlled retry experiment, add enough sequences to cover the expected initial/retry/timeout windows.

## 17. Why sequence numbers do not restart when B sends

Channel sequence indexing is global to the Panel.

If A consumes sequences 1-3, the next window from B consumes sequence 4.

This is current design.

## 18. Same side wins channel twice

Contention uses randomized backoff, not strict round-robin scheduling.

After a delivered COMPLETE releases the channel, any side with pending messages may request again. The previous winner can therefore win again.

## 19. Random results change every run

A blank seed means the random generator is not intentionally fixed for reproducible loss/contention choices.

For repeatable experiments, use a fixed integer seed, for example:

```text
12345
```

Keep the scenario and ordering the same as well, because changing which random calls occur changes later choices.

## 20. Panel scenario builder: save/select behavior

`PANEL> /scenario make` saves a **new** JSON file under:

```text
simulation/scenarios/channels/
```

Existing scenario files are not overwritten.

The new scenario becomes the selected/preloaded channel configuration.

Use:

```text
/scenario list
/scenario select <number|name|path>
/scenario preview
```

for switching/inspection.

Avoid switching the channel configuration halfway through an active DATA/END transaction.

## 21. Node scenario builder: save/select behavior

Node scenarios are saved under:

```text
simulation/scenarios/nodes/
```

Saving creates a new file and preloads it into that Tian process.

Use:

```text
/scenario list
/scenario select <number|name|path>
/scenario preview
/run
```

## 22. Panel metadata is too noisy

Use:

```text
/metadata off
```

for concise output.

Use:

```text
/metadata current
```

to inspect the latest snapshot once without enabling automatic dumps.

Use:

```text
/metadata on
```

only when you want full metadata for every transmission/retry sequence.

## 23. Why node logs use `[EXPRIMT]`

`[EXPRIMT]` is the shortened high-level experiment prefix.

Per-frame information is intentionally prioritized as:

```text
[TX] DATA ...
[RX] DATA ...
[RX] NACK ...
[TX] END ...
[RX] COMPLETE ...
```

The old duplicate per-frame experiment line was removed to keep TX/RX and protocol commands visually dominant.

## 24. `CRC mismatch`

`Frame.decode()` detected corrupted encoded frame bytes.

CRC corruption detection works at protocol level. Real RF integration should catch malformed-frame errors, log/drop bad frames and allow END/NACK reliability recovery to handle missing DATA.

The live fault-injection builder currently focuses on frame loss, not arbitrary bit corruption.

## 25. AES key warning

`tian_payload.py` currently uses a fixed demo/test AES-GCM key.

Do not treat it as production key management.

## 26. Automatic terminal launcher fails

The launcher checks for:

```text
konsole
gnome-terminal
xterm
```

If none is available, it prints the manual commands.

Start the enhanced live Panel, not the old predefined Panel command, for the current live workflow.

## 27. Test suite

Run:

```bash
python3 -m unittest discover -s tests -v
```

Also manually exercise the current live features because recent terminal/UI behavior is integration-heavy:

```text
clean text
clean image
6 random DATA loss + clean retry
lost END
lost NACK
lost COMPLETE
A/B both queue messages
/metadata current/on/off
node builder
Panel builder
/delay slow
```

## 28. If the simulator appears stuck

Inspect all three terminals:

```text
Did both nodes connect?
Was the message queued?
Did a Tian process request the channel?
Did the Panel grant an owner?
Are DATA frames being streamed PASS/DROP?
Did END pass?
Did the receiver send NACK or COMPLETE?
Was that response deliberately dropped?
Did sender timeout and retry END?
Was COMPLETE eventually delivered?
Did the Panel release channel ownership?
```

These questions usually identify which protocol state is waiting.
