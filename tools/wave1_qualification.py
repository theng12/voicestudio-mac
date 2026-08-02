#!/usr/bin/env python3
"""Create and validate offline-only Wave 1 qualification draft evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RUN_SCHEMA = "studio.wave1-qualification-run"
DRAFT_SCHEMA = "studio.wave1-qualification-draft"
ALLOWED_STATUSES = {"draft", "pending_execution", "pending_evidence", "pending_review"}
MACHINE_TIERS = (8, 16, 24)
SAFETY = {"provider_calls": 0, "model_downloads_started": 0, "passed_audits_written": 0, "historical_jobs_modified": 0}
QWEN_CUSTOM = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
QWEN_BASE = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
CHATTERBOX = "mlx-community/chatterbox-4bit"
QWEN_VOICES = ("Ryan", "Aiden", "Serena", "Vivian", "Uncle_Fu", "Dylan", "Eric", "Ono_Anna", "Sohee")
CHATTERBOX_LANGUAGES = ("ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh")
CANDIDATES = {
    QWEN_CUSTOM: {"mode": "preset", "voices": QWEN_VOICES, "languages": ()},
    QWEN_BASE: {"mode": "clone", "voices": (), "languages": ()},
    CHATTERBOX: {"mode": "clone", "voices": (), "languages": CHATTERBOX_LANGUAGES},
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _manifest(kind: str) -> dict[str, Any]:
    if kind == "corpus":
        payload = {"schema": "studio.wave1-corpus-manifest", "schema_version": 1, "short_form_policy": "one controlled short form per required voice or language", "long_form_characters": 40000, "long_form_policy": "adapter_managed_long_form", "text_material": "external-controlled-corpus-required-before-execution"}
    else:
        payload = {"schema": "studio.wave1-reference-manifest", "schema_version": 1, "reference_policy": "consented-private-reference-required-before-execution", "source_sha256": None, "transcript_segments_sha256": None, "public_evidence_only": True}
    return {**payload, "manifest_hash": canonical_hash(payload)}


def _case(case_id: str, kind: str, *, voice: str | None = None, language: str | None = None) -> dict[str, Any]:
    case = {"case_id": case_id, "kind": kind, "status": "pending_execution", "evidence": {}}
    if voice:
        case["preset_speaker"] = voice
    if language:
        case["language"] = language
    return case


def expected_cases(repo: str) -> list[dict[str, Any]]:
    info = CANDIDATES[repo]
    if info["mode"] == "preset":
        cases = [_case(f"short-preset-{voice.lower()}", "short_form", voice=voice) for voice in info["voices"]]
    elif info["languages"]:
        cases = [_case(f"short-clone-{language}", "short_form", language=language) for language in info["languages"]]
    else:
        cases = [_case("short-clone", "short_form")]
    language = "en" if repo == CHATTERBOX else None
    return cases + [_case("long-adapter-managed", "long_form", language=language), _case("cancel-long-form", "cancellation", language=language)]


def draft(repo: str, run_id: str) -> dict[str, Any]:
    return {"schema": DRAFT_SCHEMA, "schema_version": SCHEMA_VERSION, "run_id": run_id, "subject": {"model_id": repo}, "status": "draft", "candidate_status": "not_audit", "machine_tiers_gb": list(MACHINE_TIERS), "required_cases": expected_cases(repo), "safety": dict(SAFETY)}


def run_record(run_id: str) -> dict[str, Any]:
    return {"schema": RUN_SCHEMA, "schema_version": SCHEMA_VERSION, "run_id": run_id, "status": "draft", "candidate_status": "not_audit", "machine_tiers_gb": list(MACHINE_TIERS), "corpus_manifest": _manifest("corpus"), "reference_manifest": _manifest("reference"), "candidates": sorted(CANDIDATES), "safety": dict(SAFETY)}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_name(repo: str) -> str:
    return repo.replace("/", "--") + ".draft.json"


def _reject_audit_material(run_dir: Path) -> list[str]:
    errors = [f"audit artifact forbidden: {path}" for path in run_dir.rglob("*.audit.json")]
    for path in run_dir.rglob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if raw.get("audit_status") == "passed" or raw.get("candidate_status") == "passed":
            errors.append(f"passed audit state forbidden: {path}")
    return errors


def _check_manifest(value: Any, expected: dict[str, Any], label: str, errors: list[str]) -> None:
    if value != expected:
        errors.append(f"{label} must match the deterministic Wave 1 manifest")
    elif value.get("manifest_hash") != canonical_hash({k: v for k, v in value.items() if k != "manifest_hash"}):
        errors.append(f"{label} hash mismatch")


def _check_draft(actual: Any, repo: str, run_id: str, errors: list[str]) -> None:
    expected = draft(repo, run_id)
    if not isinstance(actual, dict):
        errors.append(f"draft contract mismatch for {repo}")
        return
    for key in ("schema", "schema_version", "run_id", "subject", "candidate_status", "machine_tiers_gb", "safety"):
        if actual.get(key) != expected[key]:
            errors.append(f"draft contract mismatch for {repo}")
            return
    if actual.get("status") not in ALLOWED_STATUSES:
        errors.append(f"draft status must remain draft/pending for {repo}")
        return
    actual_cases = actual.get("required_cases")
    if not isinstance(actual_cases, list) or len(actual_cases) != len(expected["required_cases"]):
        errors.append(f"draft contract mismatch for {repo}")
        return
    for actual_case, expected_case in zip(actual_cases, expected["required_cases"]):
        if not isinstance(actual_case, dict) or actual_case.get("status") not in ALLOWED_STATUSES:
            errors.append(f"case status must remain draft/pending for {repo}")
            return
        if not isinstance(actual_case.get("evidence"), dict):
            errors.append(f"case evidence must be an object for {repo}")
            return
        for key, value in expected_case.items():
            if key not in {"status", "evidence"} and actual_case.get(key) != value:
                errors.append(f"draft contract mismatch for {repo}")
                return


def validate(run_dir: Path) -> list[str]:
    errors = _reject_audit_material(run_dir)
    try:
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return errors + [f"invalid or missing run.json: {exc}"]
    if run.get("schema") != RUN_SCHEMA or run.get("schema_version") != SCHEMA_VERSION:
        errors.append("run schema/version mismatch")
    if run.get("status") not in ALLOWED_STATUSES or run.get("candidate_status") != "not_audit":
        errors.append("run must remain draft/pending and not_audit")
    if run.get("machine_tiers_gb") != list(MACHINE_TIERS):
        errors.append("machine tiers must be exactly 8/16/24 GB")
    if run.get("candidates") != sorted(CANDIDATES):
        errors.append("candidate list contains unknown or missing model")
    if run.get("safety") != SAFETY:
        errors.append("run safety counters must all be zero")
    _check_manifest(run.get("corpus_manifest"), _manifest("corpus"), "corpus manifest", errors)
    _check_manifest(run.get("reference_manifest"), _manifest("reference"), "reference manifest", errors)
    for repo in CANDIDATES:
        try:
            actual = json.loads((run_dir / _safe_name(repo)).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid or missing draft for {repo}: {exc}")
            continue
        _check_draft(actual, repo, str(run.get("run_id") or ""), errors)
    return errors


def command_plan(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        print(f"refusing non-empty run directory: {run_dir}", file=sys.stderr)
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "run.json", run_record(args.run_id))
    for repo in CANDIDATES:
        _write_json(run_dir / _safe_name(repo), draft(repo, args.run_id))
    errors = validate(run_dir)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"created offline Wave 1 draft plan: {run_dir}")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    errors = validate(Path(args.run_dir).resolve())
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Wave 1 draft plan is valid and remains not_audit.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("plan", command_plan), ("validate", command_validate)):
        sub = commands.add_parser(name)
        sub.add_argument("--run-dir", required=True)
        if name == "plan":
            sub.add_argument("--run-id", required=True)
        sub.set_defaults(handler=handler)
    return args.handler(args) if (args := parser.parse_args(argv)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
