# Subtitles API (Whisper STT) — integration guide

> **Audience:** the Story Studio KH developer (and its Claude session) wiring up
> subtitle generation against Voice Studio KH. Added in Voice Studio **v1.4.0**.

## Why this lives in Voice Studio KH (not a separate app)

The recommendation was to add speech-to-text here rather than stand up a second
service. The reasons, in order of weight:

1. **The engine was already installed.** Voice Studio's `mlx-audio` dependency
   (already required for the MLX TTS engines) ships a complete STT subsystem —
   `mlx_audio.stt` with Whisper and a dozen other ASR models. Adding subtitles
   was wiring, not a new install. `whisper-tiny` was even already in the HF
   cache.
2. **One service, one endpoint, one thing to keep alive.** Same Mac mini, same
   FastAPI server, same Tailscale URL, same HF cache, same download manager,
   same diagnostics. A separate app would double the operational surface for
   zero benefit on a single-machine personal pipeline.
3. **Massive infra reuse.** The STT worker reuses the exact safety machinery we
   built for TTS: the shared GPU lock (so TTS and STT never both spike Metal
   memory → OOM), MLX cache release between jobs, explicit-path model loading
   (immune to HF-cache-layout drift), and the no-silent-download rule.
4. **TTS audio is pristine, so Whisper is near-perfect on it.** Your narration
   comes out of TTS with no background noise and clean articulation — the
   easiest possible input for Whisper. Re-transcription "just works" with very
   low error rates, which is *not* generally true of Whisper on real-world
   recordings.

### What we deliberately did NOT use

`whisperx` (the popular "better word timestamps" wrapper) pins heavy
torch/pyannote dependencies — the same dependency-weight trap that made us skip
Coqui XTTS on the TTS side. Plain `mlx-audio` Whisper is clean, native to Apple
Silicon, and already present. If you ever need perfect word-level alignment,
Voice Studio's `mlx-audio` also ships `qwen3_forced_aligner` (aligns *known
text* to audio — relevant because Story Studio already has the script text),
which we can wire as an upgrade later without new dependencies.

## The API

Base URL is the same Voice Studio modal URL you already use for TTS (Tailscale
IP + `:47870`). No auth — Tailscale handles transport security.

### `GET /api/transcribe/availability`

Call this once before transcribing to learn which Whisper models are cached and
ready. Mirrors the shape of `/api/generate/availability`.

```jsonc
{
  "available": true,                                   // mlx-audio STT importable
  "mlx_audio": true,
  "device": "mps",
  "default_model": "mlx-community/whisper-large-v3-turbo",
  "models": [
    { "repo": "mlx-community/whisper-large-v3-turbo",    "label": "Whisper large-v3 turbo",
      "size_gb": 1.6, "recommended": true,  "cached": false,
      "note": "Recommended. Near-large accuracy at ~8× the speed." },
    { "repo": "mlx-community/whisper-large-v3-turbo-q4", "label": "Whisper large-v3 turbo (4-bit)",
      "size_gb": 0.5, "recommended": false, "cached": false, "note": "..." },
    { "repo": "mlx-community/whisper-small-mlx",          "label": "Whisper small",
      "size_gb": 0.5, "recommended": false, "cached": false, "note": "..." }
    // ... base, tiny, large-v3 full
  ]
}
```

### Download a model (one-time, before first use)

Whisper models download through the **same** generic endpoint as the TTS models
— nothing new to learn:

```bash
curl -X POST http://<modal>:47870/api/downloads \
  -H 'content-type: application/json' \
  -d '{"repo": "mlx-community/whisper-large-v3-turbo"}'
```

Poll `/api/cache/<repo-url-encoded>` or watch `/api/downloads/stream` (same as
TTS) until `cached`. The recommended default (`whisper-large-v3-turbo`, ~1.6 GB)
is the right first download for most cases; `whisper-large-v3-turbo-q4` (~0.5 GB)
is the lean choice for 8 GB Macs.

### `POST /api/transcribe`

`multipart/form-data`. Supply the audio **exactly one** of two ways:

| Field | Type | Notes |
|---|---|---|
| `file` | file upload | Any audio (WAV/MP3/M4A/FLAC). Universal, decoupled. |
| `job_id` | string | Transcribe a **previous TTS job's** output already on the server — **no re-upload of the audio bytes**. The efficient same-machine path. |
| `model` | string | Optional. Whisper repo. Defaults to `default_model` from availability. |
| `language` | string | Optional ISO code (e.g. `en`). Omit for auto-detect. |
| `word_timestamps` | bool | Optional. Adds per-word timings to each segment. Default `false`. |

**Response:**

```jsonc
{
  "text": "Full transcript as one string.",
  "language": "en",
  "duration": 42.31,
  "model": "mlx-community/whisper-large-v3-turbo",
  "elapsed_seconds": 6.4,
  "segments": [
    { "id": 0, "start": 0.0,  "end": 3.2,  "text": "First subtitle line." },
    { "id": 1, "start": 3.2,  "end": 6.5,  "text": "Second subtitle line." }
    // each gets a "words": [{word,start,end}, ...] array if word_timestamps=true
  ],
  "srt": "1\n00:00:00,000 --> 00:00:03,200\nFirst subtitle line.\n\n2\n...",
  "vtt": "WEBVTT\n\n00:00:00.000 --> 00:00:03.200\nFirst subtitle line.\n\n..."
}
```

You get **both `srt` and `vtt` strings ready to write to a file**, plus the raw
`segments` if you want to render/restyle them yourself. No format decision
required up front, no second request.

## Recommended Story Studio flow

The efficient path for your existing pipeline — you already generate TTS and get
back a `job_id`:

```
1. POST /api/generate/txt2speech         → { job_id }
2. poll /api/generate/jobs/{job_id}      → state == "done"
3. (download the WAV as you do today)
4. POST /api/transcribe (job_id=<id>)    → { srt, vtt, segments }   ← no re-upload
5. write result.srt / result.vtt next to your audio
```

Because step 4 references the `job_id`, the audio bytes never travel back over
Tailscale — Voice Studio transcribes the file it already has on disk.

If you're transcribing audio Voice Studio did **not** generate (an imported
clip, a different source), use the `file` upload form instead of `job_id`.

## Wiring it into Story Studio safely (suggested client shape)

This mirrors the existing `voicestudio-client.ts` conventions:

```ts
// voicestudio-client.ts — add alongside submitTxt2Speech/pollJob/downloadAudio

export interface TranscribeResult {
  text: string
  language: string
  duration: number
  model: string
  segments: { id: number; start: number; end: number; text: string }[]
  srt: string
  vtt: string
}

/** Transcribe a previous TTS job's output (no re-upload). */
export async function transcribeJob(
  baseUrl: string,
  jobId: string,
  opts: { model?: string; language?: string; wordTimestamps?: boolean } = {},
): Promise<TranscribeResult> {
  const fd = new FormData()
  fd.append('job_id', jobId)
  if (opts.model) fd.append('model', opts.model)
  if (opts.language) fd.append('language', opts.language)
  if (opts.wordTimestamps) fd.append('word_timestamps', 'true')
  const r = await fetch(`${baseUrl}/api/transcribe`, { method: 'POST', body: fd })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    // 409 == model not downloaded yet → trigger a /api/downloads then retry.
    throw new Error(err.detail || `transcribe failed (${r.status})`)
  }
  return r.json()
}
```

### Safety / correctness notes for the wiring session

- **Gate on availability + cache.** Before transcribing, check
  `/api/transcribe/availability` and confirm the chosen model's `cached: true`.
  If not, POST `/api/downloads` with the repo and wait — **do not** assume the
  model auto-downloads. Voice Studio intentionally returns **HTTP 409** ("not
  cached") instead of silently downloading 1.6 GB mid-request. Treat 409 as
  "download then retry."
- **Pick the model once, store it in settings** — same pattern as the TTS model
  id. Default to `mlx-community/whisper-large-v3-turbo`. Offer the q4 variant
  for low-memory Macs.
- **STT and TTS share one GPU lock on the server.** A transcribe call will queue
  behind any in-flight TTS generation (and vice versa) — this is deliberate, it
  prevents Metal OOM. So don't fire TTS and transcribe in parallel expecting
  both to run at once; they'll serialize. For your pipeline (generate → then
  transcribe) that's exactly the right order anyway.
- **Timeouts.** Transcription of a few-minutes clip on turbo is seconds, but a
  long clip on the full large model can take longer. Set a generous client
  timeout (e.g. 300s) on the transcribe fetch, or chunk very long audio.
- **`language`.** For English YouTube content, pass `language: "en"` — it's
  slightly faster and avoids the rare auto-detect miss on the first words.
- **Output formats.** You already get both `srt` and `vtt`. YouTube accepts
  SRT directly. Write `result.srt` to `<asset>.srt` and you're done.

## Model picking cheat-sheet

| Model | Size | When |
|---|---|---|
| `whisper-large-v3-turbo` | 1.6 GB | **Default.** Best accuracy/speed balance. |
| `whisper-large-v3-turbo-q4` | 0.5 GB | 8 GB Macs / tight disk. Turbo accuracy, smaller. |
| `whisper-large-v3-mlx` | 3.1 GB | Max accuracy, slowest. Noisy/accented audio. |
| `whisper-small-mlx` | 0.5 GB | Fast, fine for clean English TTS audio. |
| `whisper-base-mlx` | 0.15 GB | Very fast drafts. |
| `whisper-tiny` | 0.07 GB | Testing / latency-critical only. |

For transcribing your own (clean) TTS narration, even `small` is usually
excellent. `turbo` is the safe default.
