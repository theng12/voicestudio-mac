#!/usr/bin/env python3
"""
Truth audit: verify _WIRED_FAMILIES matches actual dispatch coverage.

Why this exists
---------------
v1.2.0 fixed a bug where the Models tab showed a green "✓ engine ready" chip
for FLUX.1 schnell / FLUX.1 dev / FLUX.2 dev, but clicking Generate threw
`NotImplementedError: Phase 2 currently supports only FLUX.2 klein family`.

Root cause: `_WIRED_FAMILIES` (the source of truth for the chip) was
hand-maintained separately from the actual dispatch code in `_generate_*`.
Two sources of truth = inevitable drift.

This script reads both files and reports four kinds of drift:

  1. COMMISSION LIES — family in _WIRED_FAMILIES, but its dispatch branch
     raises NotImplementedError. User sees green chip → hits a wall.
     (The v1.2.0 bug. Worst kind.)

  2. OMISSION LIES — family is handled in dispatch (no NotImplementedError),
     but NOT in _WIRED_FAMILIES. UI shows "🕓 worker in roadmap" but
     generation actually works. (Less harmful — false negative.)

  3. ORPHAN FAMILIES — family appears in catalog.py ModelEntry but has no
     dispatch branch at all. Picking such a model silently falls through
     to the `else: raise NotImplementedError` default.

  4. PHANTOM WIRES — family in _WIRED_FAMILIES but no catalog entry uses it.
     Harmless but suspicious — usually means a refactor left dead config.

Usage
-----
    python3 audit_truth.py           # human-readable table + exit code
    python3 audit_truth.py --strict  # exit non-zero on any drift

Run from the app root. No deps beyond stdlib (so it works without the venv).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Optional


# ─── AST helpers ───────────────────────────────────────────────────────────

def _string_literal(node: ast.AST) -> Optional[str]:
    """Return the string value if `node` is a string Constant, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _strings_in_collection(node: ast.AST) -> set[str]:
    """Extract all string literals from a Tuple/List/Set node."""
    out: set[str] = set()
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for elt in node.elts:
            s = _string_literal(elt)
            if s is not None:
                out.add(s)
    return out


def _branch_raises_not_implemented(stmts: list[ast.stmt]) -> bool:
    """True if the body raises NotImplementedError (anywhere, including
    inside `if cancel_event` guards). We treat any NotImplementedError-raising
    branch as "not wired" — even if there's other code, the family hits the wall."""
    for node in stmts:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Raise) and sub.exc is not None:
                exc = sub.exc
                # `raise NotImplementedError(...)` or `raise NotImplementedError`
                if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                    if exc.func.id == "NotImplementedError":
                        return True
                if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                    return True
    return False


# ─── catalog audit ─────────────────────────────────────────────────────────

def parse_catalog_families(catalog_path: Path) -> set[str]:
    """Return the set of family ids used by any ModelEntry(...) call."""
    tree = ast.parse(catalog_path.read_text())
    families: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "ModelEntry":
                for kw in node.keywords:
                    if kw.arg == "family":
                        s = _string_literal(kw.value)
                        if s:
                            families.add(s)
    return families


# ─── generation.py audit ───────────────────────────────────────────────────

class GenerationAuditor:
    """Reads generation.py and answers:
       - What's in _WIRED_FAMILIES?
       - What families does the dispatch code actually handle without raising?
    """

    def __init__(self, generation_path: Path):
        self.tree = ast.parse(generation_path.read_text())
        self.module_sets = self._collect_module_level_sets()

    def _collect_module_level_sets(self) -> dict[str, set[str]]:
        """Find module-level `NAME = {...}` or `NAME: type = {...}` assignments
        whose elements/keys are string literals. Used to resolve `family in
        MLX_AUDIO_FAMILIES`-style membership checks (where a dynamic set of
        families is delegated to one worker).

        Handles both:
        - `_WIRED_FAMILIES = {"x", "y"}`       (ast.Assign)
        - `MLX_AUDIO_FAMILIES: dict = {...}`   (ast.AnnAssign — has type hint)
        """
        out: dict[str, set[str]] = {}

        def record(name: str, value: ast.AST) -> None:
            if isinstance(value, ast.Set):
                out[name] = {s for e in value.elts if (s := _string_literal(e))}
            elif isinstance(value, ast.Dict):
                out[name] = {s for k in value.keys if (s := _string_literal(k))}

        for node in self.tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    record(target.id, node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                # `NAME: type = value`
                if isinstance(node.target, ast.Name):
                    record(node.target.id, node.value)
        return out

    def wired_families(self) -> set[str]:
        """Read the literal `_WIRED_FAMILIES = {...}` assignment."""
        return self.module_sets.get("_WIRED_FAMILIES", set())

    def dispatch_families(self) -> tuple[set[str], set[str]]:
        """
        Walk every method whose name starts with `_dispatch_` and analyze its
        if/elif chain. For each branch:
          - extract the family string(s) the branch matches
          - check whether the body raises NotImplementedError

        Returns (handled, raising):
          handled — families with at least one branch that has a real worker
          raising — families whose only branch raises NotImplementedError
        """
        handled: set[str] = set()
        raising: set[str] = set()

        for node in ast.walk(self.tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("_dispatch_"):
                continue
            for branch_families, branch_body in self._walk_if_chain(node.body):
                if _branch_raises_not_implemented(branch_body):
                    raising |= branch_families
                else:
                    handled |= branch_families

        # If a family appears in BOTH (e.g. it has multiple dispatch branches —
        # one raises, one handles), prefer "handled" — at least one code path
        # works for it. Remove from raising.
        raising -= handled
        return handled, raising

    def _walk_if_chain(self, stmts: list[ast.stmt]) -> list[tuple[set[str], list[ast.stmt]]]:
        """Walk every If node (and its elif chain) inside `stmts`. For each
        branch, yield (matched_families, branch_body). Resolves these patterns:
          - `family == "X"`
          - `family in ("X", "Y")`
          - `family in NAME` (where NAME is a module-level set/dict of strings)
        """
        out: list[tuple[set[str], list[ast.stmt]]] = []
        for node in stmts:
            if not isinstance(node, ast.If):
                continue
            current: Optional[ast.If] = node
            while current is not None:
                families = self._families_from_test(current.test)
                if families:
                    out.append((families, current.body))
                # Walk elif: orelse is either [If, ...] or non-If body (else)
                if (len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If)):
                    current = current.orelse[0]
                else:
                    current = None
        return out

    def _families_from_test(self, test: ast.expr) -> set[str]:
        """Extract family strings matched by an if-condition."""
        out: set[str] = set()

        # `family == "X"` or `family != "X"` (skip the != case)
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left = test.left
            op = test.ops[0]
            right = test.comparators[0]

            # `family == "X"`
            if (isinstance(op, ast.Eq) and isinstance(left, ast.Name)
                    and left.id == "family"):
                s = _string_literal(right)
                if s:
                    out.add(s)

            # `family in ("X", "Y")` or `family in NAME`
            if (isinstance(op, ast.In) and isinstance(left, ast.Name)
                    and left.id == "family"):
                literals = _strings_in_collection(right)
                if literals:
                    out |= literals
                elif isinstance(right, ast.Name):
                    out |= self.module_sets.get(right.id, set())
        return out


# ─── report ────────────────────────────────────────────────────────────────

def build_report(app_root: Path) -> dict:
    catalog_path = app_root / "app" / "backend" / "catalog.py"
    generation_path = app_root / "app" / "backend" / "generation.py"

    if not catalog_path.exists() or not generation_path.exists():
        raise FileNotFoundError(
            f"Couldn't find catalog.py + generation.py under {app_root}. "
            "Run this from the app root (the folder containing pinokio.js)."
        )

    catalog_families = parse_catalog_families(catalog_path)
    auditor = GenerationAuditor(generation_path)
    wired = auditor.wired_families()
    handled, raising = auditor.dispatch_families()

    # Compute drift
    commission_lies = wired & raising            # green chip but errors at runtime
    omission_lies = handled - wired              # works but UI says roadmap
    orphan_families = catalog_families - (handled | raising)   # no dispatch branch at all
    phantom_wires = wired - catalog_families     # wired but no catalog model uses it

    return {
        "catalog_families": sorted(catalog_families),
        "declared_wired": sorted(wired),
        "actually_handled": sorted(handled),
        "raising_branches": sorted(raising),
        "drift": {
            "commission_lies": sorted(commission_lies),
            "omission_lies": sorted(omission_lies),
            "orphan_families": sorted(orphan_families),
            "phantom_wires": sorted(phantom_wires),
        },
    }


def print_report(report: dict, app_root: Path) -> bool:
    """Render the report. Returns True if any drift was found."""
    drift = report["drift"]
    any_drift = any(drift.values())

    print()
    print(f"╔══ Truth audit for {app_root.name} ══╗")
    print()
    print(f"  Catalog families       : {len(report['catalog_families']):2}  {report['catalog_families']}")
    print(f"  _WIRED_FAMILIES claims : {len(report['declared_wired']):2}  {report['declared_wired']}")
    print(f"  Dispatch handles       : {len(report['actually_handled']):2}  {report['actually_handled']}")
    print(f"  Dispatch raises NotImpl: {len(report['raising_branches']):2}  {report['raising_branches']}")
    print()
    print("  ─── Drift ───")

    def section(label: str, items: list[str], icon: str, severity: str) -> None:
        if not items:
            print(f"  {icon} {label}: none")
        else:
            print(f"  {icon} {label} ({severity}):")
            for it in items:
                print(f"       - {it}")

    section("COMMISSION LIES  (claim wired, dispatch raises)",
            drift["commission_lies"], "❌", "BUG — user sees green chip, hits wall")
    section("OMISSION LIES    (handled but not in _WIRED_FAMILIES)",
            drift["omission_lies"], "⚠️ ", "false negative — UI underreports")
    section("ORPHAN FAMILIES  (in catalog, no dispatch branch)",
            drift["orphan_families"], "⚠️ ", "falls through to default error")
    section("PHANTOM WIRES    (in _WIRED_FAMILIES, no catalog)",
            drift["phantom_wires"], "ℹ️ ", "harmless but suspicious — dead config")

    print()
    if any_drift:
        print("  ✗ DRIFT DETECTED — fix the bullets above before release.")
    else:
        print("  ✓ NO DRIFT — _WIRED_FAMILIES matches actual dispatch coverage.")
    print()
    return any_drift


# ─── entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero on any drift (for CI use).",
    )
    parser.add_argument(
        "--app-root", default=".",
        help="Path to the app root (default: current directory).",
    )
    args = parser.parse_args()

    app_root = Path(args.app_root).resolve()
    report = build_report(app_root)
    had_drift = print_report(report, app_root)

    if args.strict and had_drift:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
