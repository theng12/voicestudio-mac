#!/usr/bin/env python3
"""Dispatch the same TTS jobs to several fleet Macs and collect comparable results.

Runs each machine's own Voice Studio job engine over Tailscale (fleet token
auth), so the numbers come from the app's real generation path and its own
resource telemetry — not a side-channel script. Downloads every artifact so the
audio can actually be listened to, which is the only way to judge voice quality.

    python tools/fleet_test.py --out "/Volumes/UGREEN-1TB/voicestudio-bench"

Machines and models are declared below; a model that isn't cached on a machine
is skipped rather than triggering a download mid-measurement.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

AIDEN = "a9aedc5c6bd3"  # same voice id across the fleet

MACHINES = [
    # id, tailscale ip, RAM. The leading two digits of the id select which
    # controller's fleet token authenticates the request (see TOKENS_FILE) —
    # 00xx, 01xx and 02xx are separate sites with separate tokens.
    {"id": "terranash-0000", "ip": "100.83.69.73",   "ram_gb": 17.2},
    {"id": "terranash-0001", "ip": "100.78.224.16",  "ram_gb": 8.6},
    {"id": "terranash-0002", "ip": "100.119.47.106", "ram_gb": 8.6},
    {"id": "terranash-0003", "ip": "100.75.145.115", "ram_gb": 8.6},
    {"id": "terranash-0004", "ip": "100.102.177.25", "ram_gb": 8.6},
    {"id": "terranash-0005", "ip": "100.71.193.102", "ram_gb": 8.6},
    {"id": "terranash-0006", "ip": "100.72.219.83",  "ram_gb": 8.6},
    {"id": "terranash-0007", "ip": "100.95.11.119",  "ram_gb": 17.2},
    {"id": "terranash-0100", "ip": "100.76.231.48",  "ram_gb": 17.2},
    {"id": "terranash-0101", "ip": "100.117.8.43",   "ram_gb": 8.6},
    {"id": "terranash-0102", "ip": "100.69.120.98",  "ram_gb": 8.6},
    {"id": "terranash-0103", "ip": "100.88.96.113",  "ram_gb": 8.6},
    {"id": "terranash-0104", "ip": "100.101.15.42",  "ram_gb": 8.6},
    {"id": "terranash-0105", "ip": "100.65.38.87",   "ram_gb": 8.6},
    {"id": "terranash-0200", "ip": "100.91.195.122", "ram_gb": 25.8},
    {"id": "terranash-0201", "ip": "100.75.249.107", "ram_gb": 17.2},
    {"id": "terranash-0202", "ip": "100.96.171.120", "ram_gb": 17.2},
    {"id": "terranash-0203", "ip": "100.98.173.75",  "ram_gb": 8.6},
    {"id": "terranash-0206", "ip": "100.76.16.94",   "ram_gb": 8.6},
]

# Tokens live OUTSIDE the repo so they can never be committed. chmod 600.
TOKENS_FILE = Path.home() / ".voicestudio-fleet-tokens.json"


def token_for(machine_id: str, tokens: dict) -> str:
    """00xx / 01xx / 02xx are separate sites with separate fleet tokens."""
    block = machine_id.replace("terranash-", "")[:2]
    return (tokens.get(block) or {}).get("token", "")

# One production-sized section each, so real-time factors are comparable and
# not distorted by a toy sentence (Echo's cost is per-call, not per-character).
TEXT = ("Morning light settled across the quiet harbor while fishing boats moved "
        "steadily beyond the stone pier. Along the market road, bakers opened "
        "their doors and neighbors greeted one another with patient smiles.")

MODELS = [
    {"key": "kokoro", "repo": "mlx-community/Kokoro-82M-bf16",
     "params": {"voice": "af_heart"}, "clone": False},
    {"key": "audio8", "repo": "mlx-community/Audio8-TTS-Preview-0.6b-bf16",
     "params": {"audio8_temperature": 0.7, "audio8_top_p": 0.9,
                "audio8_top_k": 50, "audio8_max_tokens": 512}, "clone": True},
    {"key": "echo", "repo": "mlx-community/echo-tts-base",
     "params": {"echo_num_steps": 40}, "clone": True},
    {"key": "omnivoice", "repo": "mlx-community/OmniVoice-bfloat16",
     "params": {"omnivoice_num_steps": 32, "omnivoice_guidance_scale": 2.0},
     "clone": True},
    # Qwen Base is the clone tier. It runs Voice Studio's quality guardrails
    # (Whisper transcript validation + up to one retry), so a slower wall time
    # here is partly validation, not just synthesis.
    {"key": "qwen-0.6b-base", "repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
     "params": {}, "clone": True},
    {"key": "qwen-1.7b-base", "repo": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
     "params": {}, "clone": True},
    # Fish S2 Pro's floor is now measured at 16 GB and agrees across the
    # catalogue, the qualification harness and the Hub baseline.
    {"key": "fish-s2-pro", "repo": "mlx-community/fish-audio-s2-pro-8bit",
     "params": {"fish_temperature": 0.7, "fish_top_p": 0.7,
                "fish_top_k": 30, "fish_max_tokens": 4096}, "clone": True},
    # The remaining clone-capable models already cached on the fleet. Without
    # these the comparison only covers the models already judged by ear, which
    # cannot say whether anything else deserves to be stocked.
    {"key": "voxcpm2-4bit", "repo": "mlx-community/VoxCPM2-4bit",
     "params": {}, "clone": True},
    # Chatterbox refuses to run without an explicit language code -- there is
    # no default. Omitting it fails the job outright rather than guessing.
    {"key": "chatterbox-4bit", "repo": "mlx-community/chatterbox-4bit",
     "params": {"language": "en"}, "clone": True},
    {"key": "chatterbox-turbo-4bit", "repo": "mlx-community/chatterbox-turbo-4bit",
     "params": {"language": "en"}, "clone": True},
    {"key": "moss-tts-nano", "repo": "mlx-community/MOSS-TTS-Nano-100M",
     "params": {}, "clone": True},
]


def req(url: str, token: str, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"X-Hub-Token": token,
                                        "content-type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def machine_facts(ip: str, token: str) -> dict:
    """Chip and memory as the machine reports them — never hardcoded, so an
    M1/M2 comparison can't be wrong because a table drifted."""
    try:
        d = req(f"http://{ip}:47870/api/system", token, timeout=20)
        return {"chip": d.get("chip"), "chip_tier": d.get("chip_tier"),
                "unified_memory_gb": d.get("unified_memory_gb"),
                "arch": d.get("arch")}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def cached_models(ip: str, token: str) -> dict:
    try:
        d = req(f"http://{ip}:47870/api/catalog", token, timeout=30)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}
    if not isinstance(d, dict) or "models" not in d:
        return {"_error": str(d)[:120]}
    return {m["repo"]: (m.get("cache") or {}).get("state")
            for m in d["models"] if m.get("kind") != "cloud"}


def run_one(mach: dict, model: dict, token: str, out_root: Path) -> dict:
    ip = mach["ip"]
    entry = {"model": model["key"], "repo": model["repo"]}
    body = {"repo": model["repo"], "text": TEXT, "speed": 1.0, "seed": 23,
            **model["params"]}
    if model["clone"]:
        body["voice_library_id"] = AIDEN
    t0 = time.time()
    try:
        j = req(f"http://{ip}:47870/api/generate/txt2speech", token,
                "POST", body, timeout=120)
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        entry.update(ok=False, error=f"HTTP {e.code}: {detail}")
        return entry
    except Exception as e:
        entry.update(ok=False, error=f"{type(e).__name__}: {e}")
        return entry

    job = j.get("job", j)
    jid = job.get("id")
    if not jid:
        entry.update(ok=False, error=f"no job id: {str(j)[:160]}")
        return entry

    # Poll. Generous ceiling: a swapping machine is slow, and "slow" is a result.
    state = job.get("state")
    while state in ("queued", "running", None):
        if time.time() - t0 > 1800:
            entry.update(ok=False, error="timed out after 30 min")
            return entry
        time.sleep(5)
        try:
            job = req(f"http://{ip}:47870/api/generate/jobs/{jid}", token,
                      timeout=30).get("job", {})
            state = job.get("state")
        except Exception:
            continue

    entry["wall_seconds"] = round(time.time() - t0, 1)
    entry["state"] = state
    entry["error"] = job.get("error")
    entry["audio_seconds"] = job.get("audio_duration_s")
    entry["sample_rate_hz"] = job.get("sample_rate_hz")
    ru = job.get("resource_usage") or {}
    entry["resource_usage"] = ru
    if entry["audio_seconds"]:
        entry["realtime_factor"] = round(entry["wall_seconds"] / entry["audio_seconds"], 2)
    entry["ok"] = state == "done"

    if state == "done":
        try:
            audio = req(f"http://{ip}:47870/api/generate/jobs/{jid}/audio",
                        token, timeout=300)
            d = out_root / mach["id"]
            d.mkdir(parents=True, exist_ok=True)
            ext = "mp3" if isinstance(audio, bytes) and audio[:3] == b"ID3" else "wav"
            f = d / f"{model['key']}.{ext}"
            f.write_bytes(audio)
            entry["audio_file"] = str(f)
        except Exception as e:
            entry["artifact_error"] = f"{type(e).__name__}: {e}"
    return entry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=Path("/Volumes/UGREEN-1TB/voicestudio-bench"))
    ap.add_argument("--hub", default="http://127.0.0.1:47873")
    ap.add_argument("--only", default="", help="comma-separated machine ids")
    ap.add_argument("--models", default="",
                    help="comma-separated model keys, for re-testing one model "
                         "without repeating a 15-minute sweep")
    args = ap.parse_args()
    wanted = {k.strip() for k in args.models.split(",") if k.strip()}
    selected_models = [m for m in MODELS if not wanted or m["key"] in wanted]
    if wanted and not selected_models:
        raise SystemExit(f"no model keys matched: {sorted(wanted)}")

    if TOKENS_FILE.exists():
        tokens = json.loads(TOKENS_FILE.read_text())
    else:  # fall back to just this site's token
        tokens = {"02": {"token": req(f"{args.hub}/api/hub/fleet", "")["token"]}}
    out = args.out if args.out.parent.is_dir() else Path("bench-results")
    out.mkdir(parents=True, exist_ok=True)

    wanted = {m.strip() for m in args.only.split(",") if m.strip()}
    results = {"schema": "voicestudio.fleet-test", "created_at": time.time(),
               "text_chars": len(TEXT), "machines": {}}

    for mach in MACHINES:
        if wanted and mach["id"] not in wanted:
            continue
        token = token_for(mach["id"], tokens)
        facts = machine_facts(mach["ip"], token)
        chip = facts.get("chip") or "?"
        print(f"\n=== {mach['id']}  {chip}  {mach['ram_gb']} GB ===")
        rec = {"machine": {**mach, **facts}, "models": {}}
        cache = cached_models(mach["ip"], token)
        if "_error" in cache:
            print(f"  unreachable / no access: {cache['_error']}")
            rec["error"] = cache["_error"]
            results["machines"][mach["id"]] = rec
            continue

        for model in selected_models:
            st = cache.get(model["repo"])
            if st != "cached":
                print(f"  {model['key']:8} skipped — not staged ({st or 'absent'})")
                rec["models"][model["key"]] = {"skipped": True, "cache_state": st}
                continue
            print(f"  {model['key']:8} running…", flush=True)
            e = run_one(mach, model, token, out)
            rec["models"][model["key"]] = e
            if e.get("ok"):
                ru = e.get("resource_usage") or {}
                mlx = (ru.get("mlx") or {}).get("peak_active_gb")
                print(f"           {e['wall_seconds']}s -> {e.get('audio_seconds')}s audio "
                      f"RTF={e.get('realtime_factor')}x peak={mlx}")
            else:
                print(f"           FAILED: {str(e.get('error'))[:140]}")
        results["machines"][mach["id"]] = rec

    f = out / "fleet-test.json"
    f.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()
