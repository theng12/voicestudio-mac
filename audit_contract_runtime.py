#!/usr/bin/env python3
"""Contract-vs-runtime audit: compare audit-record claims to the adapter code.

Why this exists
---------------
Every other check in the model-audit pipeline is a SELF-CONSISTENCY check:

  * ``model_audits.contract_hash`` matches because it is computed *over* the
    contract it is checking.
  * ``genstudio_candidate`` mirrors ``contract`` because it was copied from it.
  * GenStudio's ``normalise_controls`` derives the supported modes *from* the
    controls the record declares.

Every one of those passes for a record copied wholesale from a different
model.  The pipeline is best at passing exactly the forgeries that matter.
Nothing in the chain has ever compared the document to the adapter it claims
to describe.

That is not hypothetical.  The superseded OmniVoice record
(``voicestudio-20260808-omnivoice-6119f707-section288``) validated perfectly
and shipped in v1.32.8 with four contract fields contradicted by this
repository's own code — three of them the Qwen3-TTS Base record's values:

  * an 8 / 12 / 15 s reference window (actual: 3-10 s)
  * ``private_join_pause_milliseconds`` 180 (actual: 120)
  * a 10-value ``controls.language`` enum (the adapter sets no language kwarg
    and the catalog enumerates no languages)
  * ``controls.voice_clone.required`` true (the adapter raises only when the
    reference *and* the design prompt are both absent)

This module derives each expectation from the code and compares.

Derivation chain (no retyped constants)
---------------------------------------
    record.subject.model_id
      -> catalog.py   ModelEntry(repo=..., family=..., languages=...)
      -> generation.py MLX_AUDIO_FAMILIES[family]["mode"]
      -> generation.py `if mode == "<mode>": return self._mlx_kwargs_<fn>(...)`
      -> generation.py the body of `_mlx_kwargs_<fn>`

The record's own ``contract.adapter.engine_mode`` is cross-checked against the
mode the catalog+dispatch chain resolves, when the record declares one.  The
long-form budgets are taken from ``long_form_policy.policy_for()`` called with
*no* audit override, so the expectation is the family default rather than the
audited value being checked (calling it with the override would be one more
self-consistency check).

Non-coverage
------------
This validator reports what it does NOT verify, in the returned result and in
the printed report.  A validator that says "passed" without naming its blind
spots manufactures the same false confidence that shipped the bad record.  See
``NOT_COVERED``.

Usage
-----
    python3 audit_contract_runtime.py           # human-readable report
    python3 audit_contract_runtime.py --strict  # exit non-zero on any mismatch
    python3 audit_contract_runtime.py --json    # machine-readable result

Run from the app root.  No third-party deps (so it works without the venv).
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Optional

from app.backend.model_audits import contract_hash


# The only audit-backed section override admitted by this source-side validator.
# Keep this independent from the audit record: a copied passed/evidence block
# must continue to compare against the runtime default.
_MEASURED_SECTION_PROVENANCE = {
    "voicestudio-20260814-qwen3-tts-1.7b-base-production-v1": {
        "model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        "contract_hash": "sha256:c9be3368abdb8817369cc09a01231c8f1f5a7d68b936a0494920a918b3b8a38a",
        "runtime_revision": "e7dd0585652209fa0d7783659aad4e8a324de11c",
        "supersedes_audit_id": "voicestudio-20260814-qwen3-tts-1.7b-base-bootstrap-v1",
        "canary_commit": "433fccebf08583aa8a61e88fc8804541ec61818b",
        "canary_target": "terranash-0201",
        "canary_batch_id": "dc6fc58779",
        "canary_job_id": "0df456ec1ed0",
        "section_max_characters": 400,
    },
    "voicestudio-20260815-qwen3-tts-1.7b-base-production-v2": {
        "model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        "contract_hash": "sha256:feb681902d12102dd111932a3c0839df7a804c1f9058f00795cd664c9d419d42",
        "runtime_revision": "e7dd0585652209fa0d7783659aad4e8a324de11c",
        "supersedes_audit_id": "voicestudio-20260814-qwen3-tts-1.7b-base-production-v1",
        "canary_commit": "433fccebf08583aa8a61e88fc8804541ec61818b",
        "canary_target": "terranash-0201",
        "canary_batch_id": "dc6fc58779",
        "canary_job_id": "0df456ec1ed0",
        "section_max_characters": 400,
        "auto_default_section_max_characters": 280,
    },
    # v3 raises the REQUEST ceiling (text_max_characters 5,000 -> 10,000) and
    # changes nothing about sectioning. The canary fields below are v2's on
    # purpose: the 400 maximum and the 280 Auto default were measured on that
    # run, and v3 inherits them rather than re-deriving them. Copying the
    # anchor forward is what keeps `check_section_budget` comparing against a
    # measured number instead of falling back to the family default -- which is
    # OmniVoice's 288 and has never been this engine's.
    "voicestudio-20260826-qwen3-tts-1.7b-base-production-v3": {
        "model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        "contract_hash": "sha256:323047e52c2000fd359ab6557ac89a91bcdb0b3b411a961bdb6874575a636ec8",
        "runtime_revision": "e7dd0585652209fa0d7783659aad4e8a324de11c",
        "supersedes_audit_id": "voicestudio-20260815-qwen3-tts-1.7b-base-production-v2",
        "canary_commit": "433fccebf08583aa8a61e88fc8804541ec61818b",
        "canary_target": "terranash-0201",
        "canary_batch_id": "dc6fc58779",
        "canary_job_id": "0df456ec1ed0",
        "section_max_characters": 400,
        "auto_default_section_max_characters": 280,
    },
}


# ─── what this validator deliberately does not check ───────────────────────

NOT_COVERED: list[dict[str, str]] = [
    {
        "field": "genstudio_candidate.audit_status",
        "reason": (
            "Whether an audit passed is a human verdict. No code in this "
            "repository can confirm or refute it."
        ),
    },
    {
        "field": "contract.hardware.*, evidence.memory_qualification, evidence.throughput",
        "reason": (
            "Hardware qualification is a fleet measurement. This validator "
            "contacts no machine and cannot re-derive peak memory, safe latent "
            "frames, or real-time factors from source."
        ),
    },
    {
        "field": "evidence.human_quality_review, evidence.section_budget_quality_gate",
        "reason": (
            "Quality comparisons (\"on par with Fish Audio S2.1 Pro\") and "
            "transcribe-back coverage are listening and measurement results. "
            "The section budget's NUMBER is checked against the runtime; the "
            "judgement that the number is good enough is not."
        ),
    },
    {
        "field": "contract.license.*, voice permission_acknowledged",
        "reason": (
            "Licence terms and clone-permission attestations are legal and "
            "ownership facts asserted by the owner. They are authoritative "
            "input to this validator, never an output of it."
        ),
    },
    {
        "field": "contract.input_limits.text_max_characters (the chosen value)",
        "reason": (
            "A commercial ceiling, not a technical one. The only thing checked "
            "is that the ceiling is reachable through the API's own hard cap "
            "(text_max_within_api_cap). Where the contract chooses to sell "
            "BELOW that cap is an owner decision — a contract deliberately "
            "narrower than the code allows is correct, not incomplete, and "
            "this validator will never call it a gap."
        ),
    },
    {
        "field": "evidence.cache.sites_cached, evidence.qualification_run",
        "reason": "Fleet state and provenance. Not derivable from source.",
    },
    {
        "field": "contract.adapter.version, contract.adapter.runtime",
        "reason": (
            "No adapter-version registry exists in code; the version string is "
            "an authoring choice."
        ),
    },
]


# ─── AST helpers ───────────────────────────────────────────────────────────

def _literal(node: ast.AST) -> Any:
    """Return a Python literal for `node`, or `_UNKNOWN` when it is not one."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _UNKNOWN


class _Unknown:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unknown>"


_UNKNOWN = _Unknown()

_LANGUAGE_KWARG_KEYS = {
    "language",
    "languages",
    "lang",
    "lang_code",
    "language_code",
    "locale",
    "speaker_language",
}

# Local names an adapter uses for "a reference clip was supplied".
_REFERENCE_FLAG_NAMES = {
    "has_reference",
    "has_ref",
    "has_ref_audio",
    "reference",
    "ref_audio",
    "reference_audio",
}

_REFERENCE_MAX_KWARG = "ref_audio_max_duration_s"


def _gen_kwargs_assignments(fn: ast.FunctionDef) -> dict[str, list[Any]]:
    """Collect every ``gen_kwargs["key"] = value`` inside `fn`.

    Returns key -> list of assigned literals (``_UNKNOWN`` for computed
    values). The key set alone answers "does this adapter pass a language
    parameter at all"; the values answer "what does it pin it to".
    """
    out: dict[str, list[Any]] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Subscript):
            continue
        if not (isinstance(target.value, ast.Name) and target.value.id == "gen_kwargs"):
            continue
        key = _literal(target.slice)
        if not isinstance(key, str):
            continue
        out.setdefault(key, []).append(_literal(node.value))
    return out


def _reference_requirement(fn: ast.FunctionDef) -> Optional[bool]:
    """Is a reference clip on its own mandatory for this adapter?

    Reads the guard clauses that raise when inputs are missing:

      * ``if not has_reference: raise ...``                    -> required
      * ``if not instruct and not has_reference: raise ...``    -> NOT required
        (the reference is one of several ways to satisfy the guard)

    Returns True / False, or None when no such guard is recognisable.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if not _raises(node.body):
            continue
        test = node.test
        operands = test.values if isinstance(test, ast.BoolOp) and isinstance(
            test.op, ast.And
        ) else [test]

        mentions_reference = any(_is_absence_of_reference(op) for op in operands)
        if not mentions_reference:
            continue
        # A single-operand guard means the reference alone gates the call.
        # A conjunction means some other input can satisfy the guard instead.
        return len(operands) == 1
    return None


def _is_absence_of_reference(node: ast.expr) -> bool:
    """True for ``not has_reference``-shaped operands."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = node.operand
        if isinstance(inner, ast.Name) and inner.id in _REFERENCE_FLAG_NAMES:
            return True
    return False


def _raises(stmts: list[ast.stmt]) -> bool:
    return any(
        isinstance(sub, ast.Raise)
        for stmt in stmts
        for sub in ast.walk(stmt)
    )


# ─── source readers ────────────────────────────────────────────────────────

class CatalogSource:
    """``repo -> {family, languages}`` read from catalog.py ModelEntry calls."""

    def __init__(self, catalog_path: Path):
        tree = ast.parse(catalog_path.read_text(encoding="utf-8"))
        self.entries: dict[str, dict[str, Any]] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "ModelEntry":
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            repo = _literal(kwargs["repo"]) if "repo" in kwargs else _UNKNOWN
            if not isinstance(repo, str):
                continue
            family = _literal(kwargs["family"]) if "family" in kwargs else _UNKNOWN
            languages: Any = None
            if "languages" in kwargs:
                value = _literal(kwargs["languages"])
                if isinstance(value, (tuple, list)):
                    languages = list(value)
            self.entries[repo] = {
                "family": family if isinstance(family, str) else None,
                "languages": languages,
            }

    def get(self, repo: str) -> Optional[dict[str, Any]]:
        return self.entries.get(repo)


class AdapterSource:
    """generation.py: family -> engine mode -> the kwarg builder's AST."""

    def __init__(self, generation_path: Path):
        self.tree = ast.parse(generation_path.read_text(encoding="utf-8"))
        self.family_modes = self._family_modes()
        self.mode_functions = self._mode_functions()
        self.functions = {
            node.name: node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef)
        }

    def _family_modes(self) -> dict[str, str]:
        """Read ``MLX_AUDIO_FAMILIES = {family: {"mode": ...}}``."""
        out: dict[str, str] = {}
        for node in self.tree.body:
            targets: list[ast.expr] = []
            value: Optional[ast.expr] = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if not targets or value is None:
                continue
            target = targets[0]
            if not (isinstance(target, ast.Name) and target.id == "MLX_AUDIO_FAMILIES"):
                continue
            if not isinstance(value, ast.Dict):
                continue
            for key_node, value_node in zip(value.keys, value.values):
                family = _literal(key_node) if key_node is not None else _UNKNOWN
                config = _literal(value_node)
                if isinstance(family, str) and isinstance(config, dict):
                    mode = config.get("mode")
                    if isinstance(mode, str):
                        out[family] = mode
        return out

    def _mode_functions(self) -> dict[str, str]:
        """Read the dispatcher's ``if mode == "X": return self._mlx_kwargs_Y(...)``."""
        out: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.If):
                continue
            mode = self._mode_from_test(node.test)
            if mode is None:
                continue
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    if not isinstance(sub, ast.Call):
                        continue
                    func = sub.func
                    if isinstance(func, ast.Attribute) and func.attr.startswith(
                        "_mlx_kwargs_"
                    ):
                        out[mode] = func.attr
        return out

    @staticmethod
    def _mode_from_test(test: ast.expr) -> Optional[str]:
        if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
            return None
        if not isinstance(test.ops[0], ast.Eq):
            return None
        if not (isinstance(test.left, ast.Name) and test.left.id == "mode"):
            return None
        value = _literal(test.comparators[0])
        return value if isinstance(value, str) else None

    def resolve(self, family: str) -> tuple[Optional[str], Optional[ast.FunctionDef]]:
        mode = self.family_modes.get(family)
        if mode is None:
            return None, None
        name = self.mode_functions.get(mode)
        if name is None:
            return mode, None
        return mode, self.functions.get(name)


def read_api_text_cap(main_path: Path) -> Optional[int]:
    """The request model's own hard text cap: ``text: str = Field(max_length=N)``."""
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or stmt.value is None:
                continue
            if not (isinstance(stmt.target, ast.Name) and stmt.target.id == "text"):
                continue
            call = stmt.value
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
                continue
            if call.func.id != "Field":
                continue
            for kw in call.keywords:
                if kw.arg == "max_length":
                    value = _literal(kw.value)
                    if isinstance(value, int):
                        return value
    return None


def load_long_form_policy(app_root: Path):
    """Import long_form_policy.py directly (stdlib-only, no package import)."""
    path = app_root / "app" / "backend" / "long_form_policy.py"
    spec = importlib.util.spec_from_file_location(
        "_voicestudio_long_form_policy", path
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise FileNotFoundError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves field types through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ─── check result helpers ──────────────────────────────────────────────────

OK = "ok"
MISMATCH = "mismatch"
NOT_CHECKABLE = "not_checkable"


def _check(
    check_id: str,
    status: str,
    *,
    severity: str,
    claimed: Any = None,
    expected: Any = None,
    derived_from: str = "",
    detail: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "severity": severity,
        "claimed": claimed,
        "expected": expected,
        "derived_from": derived_from,
        "detail": detail,
    }


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ─── the checks ────────────────────────────────────────────────────────────

def check_reference_window(
    contract: dict[str, Any], fn: Optional[ast.FunctionDef]
) -> dict[str, Any]:
    """The declared reference window vs the duration the adapter actually pins."""
    severity = "high"
    claimed = {
        "controls.voice_clone.maximum_duration_seconds": (
            contract.get("controls", {}).get("voice_clone", {}) or {}
        ).get("maximum_duration_seconds"),
        "input_limits.reference_audio.maximum_duration_seconds": (
            contract.get("input_limits", {}).get("reference_audio", {}) or {}
        ).get("maximum_duration_seconds"),
        "controls.voice_clone.recommended_duration_seconds.maximum": (
            (contract.get("controls", {}).get("voice_clone", {}) or {}).get(
                "recommended_duration_seconds"
            )
            or {}
        ).get("maximum"),
    }
    if fn is None:
        return _check(
            "reference_window",
            NOT_CHECKABLE,
            severity=severity,
            claimed=claimed,
            detail="No adapter kwarg builder resolved for this model.",
        )
    assignments = _gen_kwargs_assignments(fn)
    values = [v for v in assignments.get(_REFERENCE_MAX_KWARG, []) if _as_number(v) is not None]
    if not values:
        if all(value is None for value in claimed.values()):
            return _check(
                "reference_window",
                OK,
                severity=severity,
                claimed=claimed,
                expected=None,
                derived_from=f"{fn.name}() sets no {_REFERENCE_MAX_KWARG}",
                detail="No reference window claimed and none pinned in code.",
            )
        return _check(
            "reference_window",
            NOT_CHECKABLE,
            severity=severity,
            claimed=claimed,
            derived_from=f"{fn.name}()",
            detail=(
                f"{fn.name}() pins no literal {_REFERENCE_MAX_KWARG}; the window "
                "may be set elsewhere. Not verified."
            ),
        )
    expected = _as_number(values[0])
    wrong = {
        key: value
        for key, value in claimed.items()
        if value is not None and _as_number(value) != expected
    }
    derived = f"{fn.name}() sets gen_kwargs[{_REFERENCE_MAX_KWARG!r}] = {expected}"
    if wrong:
        return _check(
            "reference_window",
            MISMATCH,
            severity=severity,
            claimed=claimed,
            expected=expected,
            derived_from=derived,
            detail=(
                "Declared reference window does not match the duration the "
                f"adapter truncates to: {wrong}."
            ),
        )
    return _check(
        "reference_window",
        OK,
        severity=severity,
        claimed=claimed,
        expected=expected,
        derived_from=derived,
    )


def check_join_pause(
    contract: dict[str, Any], policy: Optional[dict[str, Any]]
) -> dict[str, Any]:
    severity = "medium"
    claimed = contract.get("input_limits", {}).get("private_join_pause_milliseconds")
    if policy is None:
        return _check(
            "join_pause",
            NOT_CHECKABLE,
            severity=severity,
            claimed=claimed,
            detail="No long-form policy exists for this family.",
        )
    expected = policy["join_pause_milliseconds"]
    derived = (
        "long_form_policy.policy_for(family, repo) with "
        f"{policy.get('source', 'runtime_default')} section policy "
        f"-> join_pause_milliseconds = {expected}"
    )
    if claimed is None:
        return _check(
            "join_pause",
            NOT_CHECKABLE,
            severity=severity,
            claimed=None,
            expected=expected,
            derived_from=derived,
            detail="Record declares no private_join_pause_milliseconds.",
        )
    if _as_number(claimed) != _as_number(expected):
        return _check(
            "join_pause",
            MISMATCH,
            severity=severity,
            claimed=claimed,
            expected=expected,
            derived_from=derived,
            detail="Declared join pause is not the family's runtime pause.",
        )
    return _check(
        "join_pause", OK, severity=severity, claimed=claimed, expected=expected,
        derived_from=derived,
    )


def check_long_form_assembly(contract: dict[str, Any], model_id: str, policy) -> dict[str, Any]:
    """Verify the Qwen 1.7B candidate's complete section-assembly contract."""
    claimed_limits = contract.get("input_limits", {})
    keys = (
        "private_join_pause_milliseconds",
        "private_paragraph_join_pause_milliseconds",
        "private_soft_join_pause_milliseconds",
        "private_edge_destructive_trim",
        "private_speech_crossfade",
    )
    claimed = {key: claimed_limits.get(key) for key in keys}
    expected = policy.qwen_17b_assembly_invariants(model_id)
    if expected is None:
        return _check(
            "long_form_assembly",
            NOT_CHECKABLE,
            severity="critical",
            claimed=claimed,
            detail="No Qwen 1.7B production assembly contract applies to this model.",
        )
    if claimed != expected:
        return _check(
            "long_form_assembly",
            MISMATCH,
            severity="critical",
            claimed=claimed,
            expected=expected,
            derived_from="long_form_policy.qwen_17b_assembly_invariants()",
            detail=(
                "The candidate's sentence, paragraph, soft-split, trim, or "
                "crossfade claim differs from the runtime assembly contract."
            ),
        )
    return _check(
        "long_form_assembly",
        OK,
        severity="critical",
        claimed=claimed,
        expected=expected,
        derived_from="long_form_policy.qwen_17b_assembly_invariants()",
    )


def check_language_control(
    contract: dict[str, Any],
    fn: Optional[ast.FunctionDef],
    catalog_entry: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """May ``controls.language`` exist at all for this model?

    Flags only the unambiguous case: the record offers a language control while
    the adapter passes no language parameter AND the catalog enumerates no
    languages. Either signal alone leaves the claim unverified, not wrong.
    """
    severity = "high"
    claimed = contract.get("controls", {}).get("language")
    declared = claimed is not None
    if fn is None or catalog_entry is None:
        return _check(
            "language_control",
            NOT_CHECKABLE,
            severity=severity,
            claimed=declared,
            detail="Adapter or catalog entry could not be resolved.",
        )
    assignments = _gen_kwargs_assignments(fn)
    passes_language = sorted(set(assignments) & _LANGUAGE_KWARG_KEYS)
    languages = catalog_entry.get("languages")
    enumerates = bool(languages)
    derived = (
        f"{fn.name}() language kwargs = {passes_language or 'none'}; "
        f"catalog languages = {languages if languages is not None else 'unspecified'}"
    )
    if passes_language or enumerates:
        return _check(
            "language_control",
            OK,
            severity=severity,
            claimed=declared,
            expected="language control permitted",
            derived_from=derived,
            detail=(
                "The adapter passes a language parameter and/or the catalog "
                "enumerates languages, so a language control is admissible. "
                "Its exact value set is not verified."
            ),
        )
    if declared:
        return _check(
            "language_control",
            MISMATCH,
            severity=severity,
            claimed=claimed,
            expected="no controls.language",
            derived_from=derived,
            detail=(
                "The record offers a language control, but the adapter passes "
                "no language parameter to the engine and the catalog "
                "enumerates no languages. Nothing consumes this control."
            ),
        )
    return _check(
        "language_control",
        OK,
        severity=severity,
        claimed=False,
        expected="no controls.language",
        derived_from=derived,
    )


def check_voice_clone_required(
    contract: dict[str, Any], fn: Optional[ast.FunctionDef]
) -> dict[str, Any]:
    severity = "high"
    control = contract.get("controls", {}).get("voice_clone")
    claimed = control.get("required") if isinstance(control, dict) else None
    if fn is None:
        return _check(
            "voice_clone_required",
            NOT_CHECKABLE,
            severity=severity,
            claimed=claimed,
            detail="No adapter kwarg builder resolved for this model.",
        )
    expected = _reference_requirement(fn)
    if expected is None:
        return _check(
            "voice_clone_required",
            NOT_CHECKABLE,
            severity=severity,
            claimed=claimed,
            derived_from=f"{fn.name}()",
            detail=(
                f"{fn.name}() has no recognisable guard that raises when the "
                "reference is absent. Not verified."
            ),
        )
    derived = (
        f"{fn.name}() raises when the reference is missing "
        + ("on its own" if expected else "only together with every other input")
    )
    if claimed is None:
        return _check(
            "voice_clone_required",
            NOT_CHECKABLE,
            severity=severity,
            claimed=None,
            expected=expected,
            derived_from=derived,
            detail="Record declares no controls.voice_clone.required.",
        )
    if bool(claimed) != expected:
        return _check(
            "voice_clone_required",
            MISMATCH,
            severity=severity,
            claimed=claimed,
            expected=expected,
            derived_from=derived,
            detail=(
                "Declaring the reference required would refuse requests the "
                "adapter accepts."
                if claimed
                else "Declaring the reference optional would accept requests "
                "the adapter refuses."
            ),
        )
    return _check(
        "voice_clone_required", OK, severity=severity, claimed=claimed,
        expected=expected, derived_from=derived,
    )


def check_section_budget(
    contract: dict[str, Any], model_id: str, policy: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """The highest-value check: this number is fed straight into the runtime.

    ``catalog.py`` passes the audited ``private_section_max_characters`` into
    ``long_form_policy.policy_for(..., audited_section_max_characters=...)``,
    which overrides the family default whenever it lands in the accepted range.
    A wrong number here does not merely misdescribe the model — it silently
    changes how every machine running this release splits a script.
    """
    severity = "critical"
    limits = contract.get("input_limits", {})
    claimed = limits.get("private_section_max_characters")
    if policy is None:
        return _check(
            "section_budget",
            NOT_CHECKABLE,
            severity=severity,
            claimed=claimed,
            detail="No long-form policy exists for this family.",
        )
    anchor = _MEASURED_SECTION_PROVENANCE.get(
        str(policy.get("audit_id") or ""), {}
    )
    v2_default = anchor.get("auto_default_section_max_characters")
    expected = anchor.get("section_max_characters", policy["section_max_characters"])
    derived = (
        "long_form_policy.policy_for(family, repo) with "
        f"{policy.get('source', 'runtime_default')} section policy "
        f"-> section_max_characters = {policy['section_max_characters']}"
    )
    if v2_default is not None:
        derived += f"; independently anchored maximum = {expected}"
    if claimed is None:
        return _check(
            "section_budget",
            NOT_CHECKABLE,
            severity=severity,
            claimed=None,
            expected=expected,
            derived_from=derived,
            detail="Record declares no private_section_max_characters.",
        )
    if v2_default is None and _as_number(claimed) != _as_number(expected):
        return _check(
            "section_budget",
            MISMATCH,
            severity=severity,
            claimed=claimed,
            expected=expected,
            derived_from=derived,
            detail=(
                "This value overrides the family default at catalog build "
                "time, so publishing it changes generation behaviour on every "
                "machine that installs this release. It must be a deliberate, "
                "measured change to the runtime default — not a copied number."
            ),
        )
    if v2_default is None:
        return _check(
            "section_budget", OK, severity=severity, claimed=claimed, expected=expected,
            derived_from=derived,
        )
    default = limits.get("default_private_section_max_characters")
    section_claim = {"maximum": claimed, "auto_default": default}
    section_expected = {"maximum": expected, "auto_default": v2_default}
    if (
        model_id != "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
        or type(default) is not int
        or not 230 <= default <= claimed
        or default != v2_default
    ):
        return _check(
            "section_budget",
            MISMATCH,
            severity=severity,
            claimed=section_claim,
            expected=section_expected,
            derived_from=derived,
            detail=(
                "The Qwen production-v2 Auto default must be the independently "
                "anchored whole-number 280, separately from its 400 maximum."
            ),
        )
    return _check(
        "section_budget",
        OK,
        severity=severity,
        claimed=section_claim,
        expected=section_expected,
        derived_from=derived,
    )


def check_text_max_within_api_cap(
    contract: dict[str, Any], api_cap: Optional[int]
) -> dict[str, Any]:
    """Only that the declared text ceiling is *reachable* through the API.

    Deliberately one-sided. ``text_max_characters`` is a commercial ceiling:
    where a contract chooses to sell inside the code's cap is an owner
    decision this validator has no standing to second-guess. What it can say
    is that a contract promising more than the request model will accept is
    unfulfillable, because the API rejects the request before any adapter runs.
    """
    severity = "high"
    claimed = contract.get("input_limits", {}).get("text_max_characters")
    if api_cap is None or claimed is None:
        return _check(
            "text_max_within_api_cap",
            NOT_CHECKABLE,
            severity=severity,
            claimed=claimed,
            expected=api_cap,
            detail="No API text cap or no declared ceiling to bound.",
        )
    derived = f"main.py Txt2SpeechBody.text Field(max_length={api_cap})"
    if _as_number(claimed) > float(api_cap):
        return _check(
            "text_max_within_api_cap",
            MISMATCH,
            severity=severity,
            claimed=claimed,
            expected=f"<= {api_cap}",
            derived_from=derived,
            detail=(
                "The contract promises more text than the API will accept; "
                "such a request is rejected before any adapter runs."
            ),
        )
    return _check(
        "text_max_within_api_cap",
        OK,
        severity=severity,
        claimed=claimed,
        expected=f"<= {api_cap}",
        derived_from=derived,
        detail=(
            "Within the code's hard cap. Where the contract sits BELOW that cap "
            "is a commercial decision and is not checked here."
        ),
    )


def check_engine_mode(
    contract: dict[str, Any], resolved_mode: Optional[str]
) -> dict[str, Any]:
    """The record's declared engine mode vs the mode its family dispatches to."""
    severity = "medium"
    claimed = contract.get("adapter", {}).get("engine_mode")
    if claimed is None:
        return _check(
            "engine_mode",
            NOT_CHECKABLE,
            severity=severity,
            claimed=None,
            expected=resolved_mode,
            detail="Record declares no adapter.engine_mode.",
        )
    if resolved_mode is None:
        return _check(
            "engine_mode",
            NOT_CHECKABLE,
            severity=severity,
            claimed=claimed,
            detail="Family is not registered in MLX_AUDIO_FAMILIES.",
        )
    derived = f"MLX_AUDIO_FAMILIES[family]['mode'] = {resolved_mode}"
    if claimed != resolved_mode:
        return _check(
            "engine_mode",
            MISMATCH,
            severity=severity,
            claimed=claimed,
            expected=resolved_mode,
            derived_from=derived,
            detail="The record describes an engine mode this family never runs.",
        )
    return _check(
        "engine_mode", OK, severity=severity, claimed=claimed,
        expected=resolved_mode, derived_from=derived,
    )


def _measured_section_override(record: dict[str, Any]) -> dict[str, int] | None:
    """Return independently anchored measured section limits, if exact."""
    anchor = _MEASURED_SECTION_PROVENANCE.get(str(record.get("audit_id") or ""))
    if anchor is None:
        return None
    candidate = record.get("genstudio_candidate") or {}
    contract = record.get("contract") or {}
    subject = record.get("subject") or {}
    evidence = record.get("evidence") or {}
    claimed = (contract.get("input_limits") or {}).get("private_section_max_characters")
    default = (contract.get("input_limits") or {}).get(
        "default_private_section_max_characters"
    )
    canary = evidence.get("five_thousand_character_canary")
    qualified_runtime = evidence.get("qualified_runtime")
    if (
        candidate.get("audit_status") == "passed"
        and candidate.get("candidate_for_genstudio") is True
        and candidate.get("audit_id") == record.get("audit_id")
        and subject.get("model_id") == anchor["model_id"]
        and contract_hash(contract) == anchor["contract_hash"]
        and candidate.get("contract_hash") == anchor["contract_hash"]
        and subject.get("checkpoint_revision") == anchor["runtime_revision"]
        and contract.get("runtime_revision") == anchor["runtime_revision"]
        and candidate.get("runtime_revision") == anchor["runtime_revision"]
        and evidence.get("supersedes_audit_id") == anchor["supersedes_audit_id"]
        and isinstance(canary, dict)
        and isinstance(qualified_runtime, dict)
        and qualified_runtime.get("commit") == anchor["canary_commit"]
        and qualified_runtime.get("target") == anchor["canary_target"]
        and canary.get("hub_batch_id") == anchor["canary_batch_id"]
        and canary.get("worker_job_id") == anchor["canary_job_id"]
        and claimed == anchor["section_max_characters"]
        and canary.get("section_max_characters") == anchor["section_max_characters"]
        and (
            "auto_default_section_max_characters" not in anchor
            or default == anchor["auto_default_section_max_characters"]
        )
    ):
        result = {"maximum": anchor["section_max_characters"]}
        if "auto_default_section_max_characters" in anchor:
            result["default"] = anchor["auto_default_section_max_characters"]
        return result
    return None


def _superseded_by_audit_id(record: dict[str, Any]) -> str | None:
    audit_id = str(record.get("audit_id") or "")
    for replacement_id, anchor in _MEASURED_SECTION_PROVENANCE.items():
        if anchor["supersedes_audit_id"] == audit_id:
            return replacement_id
    return None


# ─── record-level driver ───────────────────────────────────────────────────

def validate_record(
    record: dict[str, Any],
    *,
    catalog: CatalogSource,
    adapters: AdapterSource,
    long_form_policy,
    api_text_cap: Optional[int] = None,
    source_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Compare one audit record's claims against the adapter it describes."""
    contract = record.get("contract") or {}
    model_id = str((record.get("subject") or {}).get("model_id") or "")

    catalog_entry = catalog.get(model_id)
    family = catalog_entry.get("family") if catalog_entry else None

    mode: Optional[str] = None
    fn: Optional[ast.FunctionDef] = None
    if family:
        mode, fn = adapters.resolve(family)

    superseded_by = _superseded_by_audit_id(record)
    if superseded_by is not None:
        return {
            "model_id": model_id,
            "audit_id": record.get("audit_id"),
            "source_path": str(source_path) if source_path else None,
            "resolved": {
                "family": family,
                "engine_mode": mode,
                "adapter_function": fn.name if fn else None,
                "long_form_policy_source": None,
                "historical": True,
                "superseded_by": superseded_by,
            },
            "resolution_notes": [
                f"Audit {record.get('audit_id')!r} is superseded historical evidence "
                f"by {superseded_by!r}; it is not current runtime policy authority."
            ],
            "checks": [],
            "mismatches": [],
            "not_checkable": [],
            "not_covered": NOT_COVERED,
        }

    policy: Optional[dict[str, Any]] = None
    if family:
        measured = _measured_section_override(record) or {}
        policy = long_form_policy.policy_for(
            family,
            model_id,
            audited_section_max_characters=measured.get("maximum"),
            audited_default_section_max_characters=measured.get("default"),
        )
        if policy is not None and measured:
            policy = {**policy, "audit_id": record.get("audit_id")}

    checks = [
        check_section_budget(contract, model_id, policy),
        check_reference_window(contract, fn),
        check_join_pause(contract, policy),
        check_language_control(contract, fn, catalog_entry),
        check_voice_clone_required(contract, fn),
        check_text_max_within_api_cap(contract, api_text_cap),
        check_engine_mode(contract, mode),
    ]
    if long_form_policy.qwen_17b_assembly_invariants(model_id) is not None:
        checks.insert(3, check_long_form_assembly(contract, model_id, long_form_policy))

    resolution_notes: list[str] = []
    if catalog_entry is None:
        resolution_notes.append(
            f"{model_id!r} has no catalog.py ModelEntry — this model's adapter "
            "cannot be introspected, so its claims are unverified, not passed."
        )
    elif family is None:
        resolution_notes.append(f"{model_id!r} has a catalog entry with no family.")
    elif mode is None:
        resolution_notes.append(
            f"family {family!r} is not registered in MLX_AUDIO_FAMILIES."
        )
    elif fn is None:
        resolution_notes.append(
            f"engine mode {mode!r} resolves to no _mlx_kwargs_* builder."
        )

    return {
        "model_id": model_id,
        "audit_id": record.get("audit_id"),
        "source_path": str(source_path) if source_path else None,
        "resolved": {
            "family": family,
            "engine_mode": mode,
            "adapter_function": fn.name if fn else None,
            "long_form_policy_source": policy.get("source") if policy else None,
        },
        "resolution_notes": resolution_notes,
        "checks": checks,
        "mismatches": [c for c in checks if c["status"] == MISMATCH],
        "not_checkable": [c for c in checks if c["status"] == NOT_CHECKABLE],
        "not_covered": NOT_COVERED,
    }


def load_sources(app_root: Path) -> dict[str, Any]:
    """Read every code-side source of truth this validator compares against."""
    catalog_path = app_root / "app" / "backend" / "catalog.py"
    generation_path = app_root / "app" / "backend" / "generation.py"
    main_path = app_root / "app" / "backend" / "main.py"

    if not catalog_path.exists() or not generation_path.exists():
        raise FileNotFoundError(
            f"Couldn't find catalog.py + generation.py under {app_root}. "
            "Run this from the app root (the folder containing pinokio.js)."
        )

    return {
        "catalog": CatalogSource(catalog_path),
        "adapters": AdapterSource(generation_path),
        "long_form_policy": load_long_form_policy(app_root),
        "api_text_cap": read_api_text_cap(main_path) if main_path.exists() else None,
    }


def build_report(app_root: Path) -> dict[str, Any]:
    audit_root = app_root / "model-audits"
    sources = load_sources(app_root)

    records: list[dict[str, Any]] = []
    for path in sorted(audit_root.glob("*/*.audit.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("contract"), dict):
            continue
        records.append(
            validate_record(
                raw, **sources, source_path=path.relative_to(app_root)
            )
        )

    mismatches = [
        {"model_id": r["model_id"], **c} for r in records for c in r["mismatches"]
    ]
    return {
        "records": records,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "not_covered": NOT_COVERED,
    }


# ─── report ────────────────────────────────────────────────────────────────

_STATUS_ICON = {OK: "✓", MISMATCH: "❌", NOT_CHECKABLE: "…"}


def print_report(report: dict[str, Any], app_root: Path) -> bool:
    """Render the report. Returns True if any mismatch was found."""
    print()
    print(f"╔══ Contract-vs-runtime audit for {app_root.name} ══╗")
    for record in report["records"]:
        resolved = record["resolved"]
        print()
        print(f"  {record['model_id']}")
        print(f"    audit_id : {record['audit_id']}")
        print(
            "    resolved : family={family} mode={engine_mode} "
            "adapter={adapter_function}".format(**resolved)
        )
        for note in record["resolution_notes"]:
            print(f"    ⚠️  {note}")
        for check in record["checks"]:
            icon = _STATUS_ICON[check["status"]]
            print(
                f"    {icon} {check['id']:<21} [{check['severity']}] "
                f"claimed={check['claimed']!r} expected={check['expected']!r}"
            )
            if check["derived_from"]:
                print(f"        derived: {check['derived_from']}")
            if check["detail"]:
                print(f"        note   : {check['detail']}")

    print()
    print("  ─── NOT COVERED by this validator (human judgement required) ───")
    for item in report["not_covered"]:
        print(f"    • {item['field']}")
        print(f"        {item['reason']}")

    print()
    if report["mismatch_count"]:
        print(
            f"  ✗ {report['mismatch_count']} CONTRACT MISMATCH(ES) — the record "
            "contradicts the code it describes."
        )
    else:
        print(
            "  ✓ No contract-vs-runtime mismatches. This is NOT a statement "
            "that the records are correct — only that the fields listed above "
            "as covered agree with the adapter."
        )
    print()
    return bool(report["mismatch_count"])


# ─── entry point ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero on any mismatch (for CI use).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead.")
    parser.add_argument(
        "--app-root", default=".",
        help="Path to the app root (default: current directory).",
    )
    args = parser.parse_args()

    app_root = Path(args.app_root).resolve()
    report = build_report(app_root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        had_mismatch = bool(report["mismatch_count"])
    else:
        had_mismatch = print_report(report, app_root)

    return 1 if (args.strict and had_mismatch) else 0


if __name__ == "__main__":
    raise SystemExit(main())
