#!/usr/bin/env python3
"""Benchmark local TTS models on THIS machine and write a comparable JSON result.

Run the same command on every fleet Mac; the JSON files can then be diffed to
compare chips and memory tiers directly.

    conda_env/bin/python tools/bench_tts.py --machine <machine-id>

What it measures, per model:
  * peak unified memory (mx.get_peak_memory) — the number that decides the
    catalogue's min_unified_memory_gb, and the reason a model does or doesn't
    fit a tier. NOT process RSS: MLX allocates through Metal, so RSS badly
    under-reports (measured 1.45 GB RSS against an 18.35 GB MLX peak).
  * wall time and real-time factor at the model's PRODUCTION section size, not
    a toy sentence — Echo's cost is per-call rather than per-character, so a
    short line makes it look ~4x worse than it is.
  * word coverage, by transcribing the output back with Whisper. A model that
    silently drops text still produces clean-sounding audio of a plausible
    length; only transcribe-back catches it. This is what disqualified
    Ming-omni-tts (63% coverage at 174 chars, 0% at 191).
  * swap delta across the run — if a model exceeds the machine, the timings are
    swap-degraded and must not be quoted as the model's speed. NOTE this is
    machine-wide swap, not this process's: on a busy Mac another app can move
    the number. Treat a positive delta as "check this", not proof, and prefer a
    machine that is otherwise idle.

Deliberately bypasses Voice Studio's memory guard: the guard refuses a model
whose declared floor exceeds the machine, but "does it actually fit?" is
exactly the question here. An OOM/abort is a valid, recorded result.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HF_HOME = REPO_ROOT / "cache" / "HF_HOME"

# text ~= the production section cap for each family (long_form_policy.py)
SECTION_TEXT = (
    "Morning light settled across the quiet harbor while fishing boats moved "
    "steadily beyond the stone pier. Along the market road, bakers opened their "
    "doors and neighbors greeted one another with patient smiles. Beyond the "
    "town, green fields climbed toward low hills."
)

MODELS = {
    "audio8": {
        "repo": "mlx-community/Audio8-TTS-Preview-0.6b-bf16",
        "section_chars": 280,
        "kwargs": {"temperature": 0.7, "top_p": 0.9, "top_k": 50, "max_tokens": 512},
        "clone": "ref_pair",     # needs ref_audio + ref_text
    },
    "echo": {
        "repo": "mlx-community/echo-tts-base",
        "section_chars": 300,
        "kwargs": {},
        "clone": "ref_audio_only",
    },
    "kokoro": {  # cheap control: proves the harness itself is sane on this box
        "repo": "mlx-community/Kokoro-82M-bf16",
        "section_chars": 300,
        "kwargs": {"voice": "af_heart"},
        "clone": None,
    },
}


def sh(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def swap_used_gb() -> float:
    m = re.search(r"used\s*=\s*([\d.]+)([MG])", sh(["sysctl", "-n", "vm.swapusage"]))
    if not m:
        return 0.0
    v = float(m.group(1))
    return v / 1024 if m.group(2) == "M" else v


def machine_info() -> dict:
    return {
        "hostname": platform.node(),
        "chip": sh(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "model_id": sh(["sysctl", "-n", "hw.model"]),
        "memory_gb": round(int(sh(["sysctl", "-n", "hw.memsize"]) or 0) / 1e9, 1),
        "macos": platform.mac_ver()[0],
    }


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", default="", help="fleet machine id, for labelling results")
    ap.add_argument("--models", default="kokoro,audio8,echo",
                    help="comma-separated subset of: " + ",".join(MODELS))
    ap.add_argument("--ref-audio", default="", help="reference clip for cloning")
    ap.add_argument("--ref-text", default="", help="its exact transcript")
    ap.add_argument("--hf-home", type=Path, default=DEFAULT_HF_HOME)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--results-dir", type=Path, default=None,
                    help="where to write JSON + audio (default: the SSD if mounted)")
    ap.add_argument("--allow-download", action="store_true",
                    help="permit fetching missing models (off by default — a "
                         "benchmark should measure what is staged, not download it)")
    ap.add_argument("--skip-coverage", action="store_true",
                    help="skip Whisper transcribe-back (faster, less informative)")
    args = ap.parse_args()

    import os
    os.environ.setdefault("HF_HOME", str(args.hf_home))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # see chatstudio-download-stall
    if not args.allow_download:
        # A benchmark must measure what is actually staged on the machine. Left
        # online, a missing model is silently pulled from the Hub — minutes of
        # download folded into the "load" time, and gigabytes over someone's
        # connection. Offline turns that into an immediate, obvious error.
        os.environ["HF_HUB_OFFLINE"] = "1"

    # Results (JSON + the audio, so it can be listened to later) default to the
    # SSD when it is plugged in, so they don't have to be hunted for per machine.
    results_dir = args.results_dir
    if results_dir is None:
        ssd = Path("/Volumes/UGREEN-1TB/voicestudio-bench")
        results_dir = ssd if ssd.parent.is_dir() else REPO_ROOT / "bench-results"

    import mlx.core as mx
    import soundfile as sf
    from mlx_audio.tts.generate import generate_audio
    from mlx_audio.tts.utils import load

    info = machine_info()
    results = {
        "schema": "voicestudio.tts-bench",
        "schema_version": 1,
        "machine_id": args.machine or info["hostname"],
        "machine": info,
        "text_chars": None,
        "models": {},
    }
    print(f"== {results['machine_id']}  {info['chip']}  {info['memory_gb']} GB ==\n")

    stt = None
    if not args.skip_coverage:
        try:
            from mlx_audio.stt.utils import load_model as load_stt
            from transformers import WhisperTokenizer
            snaps = sorted((args.hf_home / "hub" /
                            "models--mlx-community--whisper-large-v3-turbo" /
                            "snapshots").glob("*"))
            stt = load_stt(snaps[0])
            if getattr(stt, "_processor", None) is None:
                # mlx-community whisper repos ship no HF processor; attach a
                # tokenizer from the upstream repo (same fix as transcription.py).
                class _P:
                    def __init__(self, t): self.tokenizer = t
                stt._processor = _P(WhisperTokenizer.from_pretrained(
                    "openai/whisper-large-v3-turbo"))
        except Exception as e:
            print(f"  (coverage disabled: {type(e).__name__}: {e})\n")
            stt = None

    for key in [k.strip() for k in args.models.split(",") if k.strip()]:
        spec = MODELS.get(key)
        if spec is None:
            print(f"unknown model '{key}' — skipped")
            continue

        text = SECTION_TEXT[: spec["section_chars"]].rsplit(" ", 1)[0]
        results["text_chars"] = len(text)
        entry: dict = {"repo": spec["repo"], "text_chars": len(text)}
        print(f"-- {key}  ({spec['repo']})")

        # Fail fast and clearly if the model was never staged, instead of
        # letting the loader turn it into a surprise multi-GB download.
        cache_dir = args.hf_home / "hub" / ("models--" + spec["repo"].replace("/", "--"))
        if not cache_dir.is_dir() and not args.allow_download:
            entry.update({"ok": False, "error": "not staged on this machine",
                          "skipped": True})
            results["models"][key] = entry
            print("   NOT PRESENT — run the restore step first (skipping, no download)\n")
            continue

        swap0 = swap_used_gb()
        try:
            mx.reset_peak_memory()
            t0 = time.time()
            model = load(spec["repo"])
            entry["load_seconds"] = round(time.time() - t0, 2)
            entry["peak_gb_after_load"] = round(mx.get_peak_memory() / 1e9, 2)

            kw = dict(spec["kwargs"])
            if spec["clone"] and args.ref_audio:
                kw["ref_audio"] = args.ref_audio
                if spec["clone"] == "ref_pair" and args.ref_text:
                    kw["ref_text"] = args.ref_text
            entry["mode"] = "clone" if "ref_audio" in kw else "zero-shot"

            import tempfile
            out_dir = Path(tempfile.mkdtemp())
            mx.reset_peak_memory()
            t0 = time.time()
            generate_audio(model=model, text=text, output_path=str(out_dir),
                           join_audio=True, verbose=False, **kw)
            gen_s = time.time() - t0

            wav = sorted(out_dir.glob("*.wav"))[0]
            i = sf.info(str(wav))
            dur = i.frames / i.samplerate

            # Keep the audio — the numbers say whether it ran, only listening
            # says whether it sounds right.
            audio_dir = results_dir / results["machine_id"]
            audio_dir.mkdir(parents=True, exist_ok=True)
            kept = audio_dir / f"{key}-{entry['mode']}.wav"
            shutil.copy2(wav, kept)
            entry["audio_file"] = str(kept)
            entry.update({
                "generation_seconds": round(gen_s, 2),
                "audio_seconds": round(dur, 2),
                "realtime_factor": round(gen_s / dur, 2) if dur else None,
                "peak_gb": round(mx.get_peak_memory() / 1e9, 2),
                "sample_rate_hz": i.samplerate,
                "channels": i.channels,
                "swap_delta_gb": round(swap_used_gb() - swap0, 2),
            })

            if stt is not None:
                heard = getattr(stt.generate(str(wav)), "text", "") or ""
                src, got = words(text), words(heard)
                entry["word_coverage"] = round(
                    sum(1 for w in src if w in got) / max(1, len(src)), 3)
                entry["transcript"] = heard.strip()[:300]

            entry["ok"] = True
            print(f"   peak={entry['peak_gb']}GB  {entry['generation_seconds']}s "
                  f"-> {entry['audio_seconds']}s audio  RTF={entry['realtime_factor']}x"
                  + (f"  coverage={entry['word_coverage']*100:.0f}%"
                     if "word_coverage" in entry else "")
                  + (f"  SWAP+{entry['swap_delta_gb']}GB"
                     if entry.get("swap_delta_gb", 0) > 0.2 else ""))
            if entry.get("swap_delta_gb", 0) > 0.2:
                print("   ! swapped — treat the timing as a floor, not the model's speed")

            del model
            mx.clear_cache()
        except Exception as e:
            entry.update({"ok": False, "error": f"{type(e).__name__}: {e}",
                          "traceback": traceback.format_exc()[-800:],
                          "swap_delta_gb": round(swap_used_gb() - swap0, 2)})
            print(f"   FAILED: {type(e).__name__}: {e}")

        results["models"][key] = entry
        print()

    results_dir.mkdir(parents=True, exist_ok=True)
    out = args.out or results_dir / f"bench-{results['machine_id']}.json"
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"results : {out}")
    audio_dir = results_dir / results["machine_id"]
    if audio_dir.is_dir():
        print(f"audio   : {audio_dir}")
    if str(results_dir).startswith("/Volumes/"):
        print("(on the SSD — carry it to the next machine, nothing to hunt for)")
    else:
        print("(SSD not mounted, so these were written locally)")


if __name__ == "__main__":
    main()
