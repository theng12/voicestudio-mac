"""Read verified sibling model-audit evidence for the public catalog.

Audit files are deliberately separate from the runtime catalog.  A cached
model can exist without an audit, and a passed audit is only a *candidate* for
GenStudio.  Studio Hub remains the authority that decides whether an exact
revision and contract hash is exposed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional


AUDIT_ROOT = Path(__file__).resolve().parents[2] / "model-audits"
_IMMUTABLE_REVISION = re.compile(r"^[0-9a-fA-F]{40,64}$")
_CONTRACT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_AUDIT_STATUSES = {"passed", "conditional", "failed", "revoked"}
_QWEN_17B_BASE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
_QWEN_17B_PRODUCTION_V2_AUDIT_ID = (
    "voicestudio-20260815-qwen3-tts-1.7b-base-production-v2"
)
_QWEN_17B_PRODUCTION_V2_PATH = (
    "2026-08-15-qwen3-17b-production-v2/"
    "mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json"
)


def contract_hash(contract: dict[str, Any]) -> str:
    """Canonical SHA-256 used to bind approval to one exact model contract."""
    encoded = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _valid_record(raw: Any) -> bool:
    if not isinstance(raw, dict) or not isinstance(raw.get("contract"), dict):
        return False
    subject = raw.get("subject")
    candidate = raw.get("genstudio_candidate")
    if not isinstance(subject, dict) or not isinstance(candidate, dict):
        return False
    if not str(subject.get("model_id") or "").strip():
        return False
    if candidate.get("schema") != "studio.model-audit":
        return False
    if candidate.get("schema_version") != 1:
        return False
    if candidate.get("audit_status") not in _AUDIT_STATUSES:
        return False
    if not isinstance(candidate.get("candidate_for_genstudio"), bool):
        return False
    revision = str(candidate.get("runtime_revision") or "")
    if not _IMMUTABLE_REVISION.fullmatch(revision):
        return False
    fingerprint = str(candidate.get("contract_hash") or "")
    if not _CONTRACT_HASH.fullmatch(fingerprint):
        return False
    if fingerprint != contract_hash(raw["contract"]):
        return False
    for key in (
        "runtime_revision",
        "approved_operations",
        "adapter",
        "controls",
        "input_limits",
        "output_limits",
        "hardware",
    ):
        if candidate.get(key) != raw["contract"].get(key):
            return False
    if "capacity" in candidate and candidate.get("capacity") != raw["contract"].get("capacity"):
        return False
    return True


def audit_record(model_id: str) -> Optional[dict[str, Any]]:
    """Return the newest valid audit for ``model_id``, if one is installed.

    This intentionally reads the small record directory on each catalogue
    request.  A newly installed sibling release can therefore publish its
    audit evidence without maintaining a second in-memory authority.
    """
    if not AUDIT_ROOT.exists():
        return None
    for path in sorted(AUDIT_ROOT.glob("*/*.audit.json"), reverse=True):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not _valid_record(raw):
            continue
        if raw["subject"]["model_id"] == model_id:
            return raw
    return None


def candidate_summary(model_id: str) -> Optional[dict[str, Any]]:
    record = audit_record(model_id)
    if record is None:
        return None
    # Return a detached JSON-compatible object so callers cannot mutate the
    # file-backed evidence shared with another request.
    return json.loads(json.dumps(record["genstudio_candidate"]))


def input_limits(model_id: str) -> dict[str, Any]:
    """Return detached, audit-bound input limits for one exact model.

    Runtime adapters use this helper for private execution choices such as
    sentence-section budgets and reference-audio preparation.  An unaudited
    model deliberately returns an empty mapping so the established adapter
    fallback remains in force until grounded evidence lands.
    """
    record = audit_record(model_id)
    if record is None:
        return {}
    value = record.get("contract", {}).get("input_limits")
    return json.loads(json.dumps(value)) if isinstance(value, dict) else {}


def qwen_17b_production_v2_limits(model_id: str) -> dict[str, Any]:
    """Return the exact Qwen production-v2 section policy, or nothing.

    This intentionally does not use ``audit_record()``: the latest valid audit
    may be historical v1 evidence or an unrelated future record, neither of
    which is authority for the Auto 280 policy.
    """
    if model_id != _QWEN_17B_BASE:
        return {}
    try:
        record = json.loads(
            (AUDIT_ROOT / _QWEN_17B_PRODUCTION_V2_PATH).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if (
        not _valid_record(record)
        or record.get("audit_id") != _QWEN_17B_PRODUCTION_V2_AUDIT_ID
        or record.get("subject", {}).get("model_id") != _QWEN_17B_BASE
        or record.get("genstudio_candidate", {}).get("audit_id")
        != _QWEN_17B_PRODUCTION_V2_AUDIT_ID
    ):
        return {}
    limits = record["contract"].get("input_limits")
    if not isinstance(limits, dict):
        return {}
    maximum = limits.get("private_section_max_characters")
    default = limits.get("default_private_section_max_characters")
    if (
        type(maximum) is not int
        or maximum != 400
        or type(default) is not int
        or default != 280
        or not 230 <= default <= maximum
    ):
        return {}
    return {
        "private_section_max_characters": maximum,
        "default_private_section_max_characters": default,
    }
