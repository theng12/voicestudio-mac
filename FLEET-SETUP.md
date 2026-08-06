# Fleet setup — copy models to a Mac and benchmark it

Every command on this page is **identical on every machine**. Nothing to edit,
nothing to fill in. Do them in order, top to bottom, on each Mac.

---

## Where do I type these?

In **Terminal** — the macOS app, not inside Voice Studio.

1. Press `⌘ + Space`, type `Terminal`, press Return.
2. A window opens with a line ending in `%` — that's the prompt, waiting for you.
3. Copy a command block below, paste it in (`⌘ + V`), press **Return**.
4. Wait for the prompt (`%`) to come back before pasting the next one. Some
   steps take several minutes — no output for a while is normal.

You can paste a whole block at once even when it spans multiple lines.

**If something looks wrong, nothing is broken yet.** These commands only copy
files and run tests. Stop, and send me what the terminal printed.

---

## Step 0 — plug in the SSD

Plug the **UGREEN-1TB** drive in and wait for it to appear in Finder. Confirm
the Mac can see it:

```bash
ls /Volumes/UGREEN-1TB/voicestudio-models
```

You should see a list of family folders (`Echo-TTS (MLX)`, `Qwen3-TTS (MLX)`, …).
If you get `No such file or directory`, the drive isn't mounted yet — unplug,
replug, wait for Finder, try again.

---

## Step 1 — update Voice Studio on this machine

Gets the newest scripts. **Do this before Step 2** — the older copy on these
machines has a bug that would copy far too much.

```bash
cd ~/pinokio/api/voicestudio-mac.git && git pull
```

---

## Step 2 — copy the models onto this machine

```bash
cd ~/pinokio/api/voicestudio-mac.git && conda_env/bin/python tools/organize_models.py --restore --src /Volumes/UGREEN-1TB/voicestudio-models
```

**It works out what this Mac can run by itself** — it reads how much memory the
machine has and only copies models that fit. You don't tell it anything.

What it prints:

- `machine: 16.0 GB unified memory` — what it detected
- one line per model as it copies
- `already complete, left alone` — you already had it, untouched
- `local copy is partial, replacing` — you had a broken half-download; it's
  repairing it (this is good)
- `skipped — needs more memory than this Mac has` — expected, not an error
- a final `3 new, 1 repaired/replaced, 20 already complete`

Safe to run twice. It never deletes a model that is complete.

### Exception: the two 8 GB machines (terranash-0002 and terranash-0006)

On **those two only**, use this instead. We are deliberately testing whether
Audio8 really needs 16 GB, so we have to force it onto an 8 GB machine:

```bash
cd ~/pinokio/api/voicestudio-mac.git && conda_env/bin/python tools/organize_models.py --restore --src /Volumes/UGREEN-1TB/voicestudio-models --all
```

---

## Step 3 — restart Voice Studio

So it notices the new models. In the Pinokio sidebar for Voice Studio, click
**Update**. (Or Stop then Start.)

---

## Step 4 — run the benchmark

```bash
cd ~/pinokio/api/voicestudio-mac.git && conda_env/bin/python tools/bench_tts.py --ref-audio "/Volumes/UGREEN-1TB/voicestudio-models/_reference-voice/aiden.mp3" --ref-text "$(cat '/Volumes/UGREEN-1TB/voicestudio-models/_reference-voice/aiden.txt')"
```

It names the results after the machine automatically. Takes a few minutes; it
prints a line per model like:

```
   peak=9.44GB  27.7s -> 16.8s audio  RTF=1.65x  coverage=98%
```

`FAILED: ...` on a model is **a valid result, not a mistake** — on the 8 GB
machines we expect the bigger models to fail, and that failure is the answer.
Let it finish.

**It will not download anything.** If a model isn't on the machine it prints
`NOT PRESENT — run the restore step first` and moves on, instead of quietly
pulling gigabytes and folding the download time into the results.

### Where the results go

**Straight onto the SSD**, so there's nothing to hunt for and you can listen to
the audio later:

```
/Volumes/UGREEN-1TB/voicestudio-bench/
    bench-<machine>.json          <- the numbers
    <machine>/
        kokoro-zero-shot.wav      <- the actual audio, keep for listening
        audio8-clone.wav
        echo-clone.wav
```

If the SSD isn't plugged in, it falls back to a `bench-results/` folder inside
the repo and tells you so.

---

## Step 5 — nothing to send

The JSON and the audio are already on the SSD. Bring it back and I'll read
them. If you'd rather paste the numbers directly:

```bash
cat /Volumes/UGREEN-1TB/voicestudio-bench/bench-*.json
```

---

## What each machine should end up with

| Machine | Chip / RAM | Gets | Expect |
|---|---|---|---|
| `terranash-0002` | M1 · 8 GB | + Audio8 (forced, `--all`) | Audio8 likely fails or swaps hard |
| `terranash-0006` | M2 · 8 GB | + Audio8 (forced, `--all`) | same, but shows M1 vs M2 at 8 GB |
| `terranash-0007` | M2 · 16 GB | Audio8 | should pass |
| `terranash-0201` | M2 · 16 GB | Audio8 | should match 0007 |
| `terranash-0204` | M4 · 24 GB | Audio8 **and** Echo-TTS | only machine that can run Echo |

Codecs travel with their model automatically — Echo can't arrive without its
Fish codec.

---

## If something goes wrong

**`No such file or directory` on the `/Volumes/...` path**
The SSD isn't mounted. Check Finder.

**`command not found: conda_env/bin/python`**
You're not in the right folder. The `cd ~/pinokio/api/voicestudio-mac.git &&`
part at the start of each command handles this — make sure you copied the
whole line.

**The benchmark says `coverage disabled`**
Whisper isn't on that machine yet. The speed and memory numbers are still
valid; only the word-accuracy check is missing.

**Disk is full**
The 8 GB machines using `--all` need ~48 GB free. If that's a problem, skip
`--all` there and tell me — we can copy just Audio8 by hand instead.

**Anything else** — copy what the terminal printed and send it. Don't try to
fix it by deleting files in `cache/`; that's the model cache and it's easy to
break by hand.
