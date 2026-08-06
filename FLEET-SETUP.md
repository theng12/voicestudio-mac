# Fleet setup — stage a Mac, then walk away

You only do **three steps** per machine. The testing is dispatched centrally
from Studio Hub afterwards, so there is nothing to run and nothing to collect
by hand.

Every command below is **identical on every machine**. Nothing to edit.

---

## Where do I type these?

In **Terminal** — the macOS app, not inside Voice Studio.

1. Press `⌘ + Space`, type `Terminal`, press Return.
2. A window opens with a line ending in `%` — that's the prompt, waiting for you.
3. Copy a command block below, paste it in (`⌘ + V`), press **Return**.
4. Wait for the prompt (`%`) to come back before pasting the next one. Some
   steps take several minutes — no output for a while is normal.

**If something looks wrong, nothing is broken yet.** These commands only copy
files. Stop, and send me what the terminal printed.

---

## Step 1 — update Voice Studio

Gets the newest scripts. **Do this before Step 2** — the older copy on these
machines has a bug that would copy far too much.

```bash
cd ~/pinokio/api/voicestudio-mac.git && git pull
```

---

## Step 2 — copy the models (SSD plugged in)

```bash
cd ~/pinokio/api/voicestudio-mac.git && conda_env/bin/python tools/organize_models.py --restore --src /Volumes/UGREEN-1TB/voicestudio-models
```

**It works out what this Mac can run by itself** — it reads how much memory the
machine has and only copies models that fit.

What the output means:

- `machine: 16.0 GB unified memory` — what it detected
- `already complete, left alone` — you had it; untouched
- `local copy is partial, replacing` — you had a broken half-download; it's
  repairing it (good)
- `skipped — needs more memory than this Mac has` — expected, not an error
- ends with `3 new, 1 repaired/replaced, 20 already complete`

Safe to run twice. It never deletes a model that is complete.

### The two 8 GB machines (terranash-0002, terranash-0006)

On **those two only**, add `--all` — we are deliberately testing whether Audio8
really needs 16 GB, so it has to be forced onto an 8 GB machine:

```bash
cd ~/pinokio/api/voicestudio-mac.git && conda_env/bin/python tools/organize_models.py --restore --src /Volumes/UGREEN-1TB/voicestudio-models --all
```

Needs ~48 GB free. If the disk is tight, skip `--all` there and tell me.

---

## Step 3 — start Voice Studio and leave it running

In Pinokio, open Voice Studio and click **Update** (or Stop → Start).

**Leave it running.** This is the part that matters: I reach each machine over
its Voice Studio API to run the tests. A machine that is powered off, asleep,
or has Voice Studio stopped can't be tested.

Check it's up — this should print `{"ok":true...`:

```bash
curl -s http://127.0.0.1:47870/api/health
```

---

## That's it — tell me when the machines are staged

I'll do the rest from here through Studio Hub: dispatch the tests to each
machine, collect the numbers, and pull back the audio so you can listen.

Tell me which machines are up and I'll take it from there.

---

## What each machine should end up with

| Machine | Chip / RAM | Gets | Question it answers |
|---|---|---|---|
| `terranash-0002` | M1 · 8 GB | + Audio8 (forced) | does the 16 GB floor hold? M1 baseline |
| `terranash-0006` | M2 · 8 GB | + Audio8 (forced) | same, M1 vs M2 at 8 GB |
| `terranash-0007` | M2 · 16 GB | Audio8 | production speed at 16 GB |
| `terranash-0201` | M2 · 16 GB | Audio8 | reproduces 0007 on identical hardware |
| `terranash-0204` | M4 · 24 GB | Audio8 **and** Echo-TTS | Echo's real speed, unswapped |

Codecs travel with their model automatically — Echo can't arrive without its
Fish codec.

---

## If something goes wrong

**`No such file or directory` on the `/Volumes/...` path**
The SSD isn't mounted. Check Finder.

**`command not found`**
The `cd ~/pinokio/api/voicestudio-mac.git &&` at the start of each command
handles this — make sure you copied the whole line.

**Disk full on the 8 GB machines**
`--all` needs ~48 GB free. Skip it there and tell me; we can copy just Audio8.

**Anything else** — copy what the terminal printed and send it. Don't delete
things in `cache/` by hand; that's the model cache and it's easy to break.

---

## Running a test yourself (optional)

You don't need this — but if you ever want to benchmark a machine directly
without waiting for me:

```bash
cd ~/pinokio/api/voicestudio-mac.git && conda_env/bin/python tools/bench_tts.py --ref-audio "/Volumes/UGREEN-1TB/voicestudio-models/_reference-voice/aiden.mp3" --ref-text "$(cat '/Volumes/UGREEN-1TB/voicestudio-models/_reference-voice/aiden.txt')"
```

Results and the generated audio go to `/Volumes/UGREEN-1TB/voicestudio-bench/`.
It never downloads anything: a model that isn't staged is reported as
`NOT PRESENT` and skipped.

This local script also **bypasses the app's memory guard**, which the Hub route
does not — so it is the only way to test whether a model runs on a machine
below its declared floor.
