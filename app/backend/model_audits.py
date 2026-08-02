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
