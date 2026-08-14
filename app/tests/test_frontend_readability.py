from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
STYLE_PATH = ROOT / "app" / "frontend" / "style.css"
FRONTEND_PATHS = [
    STYLE_PATH,
    ROOT / "app" / "frontend" / "index.html",
    ROOT / "app" / "frontend" / "app.js",
]


def test_frontend_keeps_a_twelve_pixel_typography_floor() -> None:
    declarations: list[tuple[str, str, float]] = []
    for path in FRONTEND_PATHS:
        source = path.read_text(encoding="utf-8")
        declarations.extend(
            (path.name, match.group(0), float(match.group("size")))
            for match in re.finditer(
                r"font-size\s*:\s*(?P<size>\d+(?:\.\d+)?)px",
                source,
                flags=re.IGNORECASE,
            )
        )
        declarations.extend(
            (path.name, match.group(0), float(match.group("size")))
            for match in re.finditer(
                r"\bfont\s*:\s*[^;{}]*?(?P<size>\d+(?:\.\d+)?)px(?:/|\s)",
                source,
                flags=re.IGNORECASE,
            )
        )

    too_small = [
        f"{filename}: {declaration}"
        for filename, declaration, size in declarations
        if size < 12
    ]
    assert not too_small, f"Readable UI text must be at least 12px: {too_small}"
    css = STYLE_PATH.read_text(encoding="utf-8")
    assert "--font-caption: 12.5px" in css
    assert not re.search(r"font-size\s*:\s*0\.\d+(?:em|rem)", css, flags=re.IGNORECASE)


def test_common_controls_keep_readable_and_compact_size_tokens() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "--font-control: 15px" in css
    assert "--control-min-height: 40px" in css
    assert "--control-compact-height: 32px" in css
    assert "min-height: var(--control-min-height)" in css
    assert "min-height: var(--control-compact-height)" in css


def test_frontend_has_no_inherited_image_or_lora_surface() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in FRONTEND_PATHS)
    inherited_markers = (
        "/api/loras",
        "img2img",
        "txt2img",
        "tone-cloud",
        "is-cloud",
        "setInputImage",
        "gen.prompt",
        ".img-drop",
        ".lora-row",
    )
    assert not [marker for marker in inherited_markers if marker in source]


def test_section_size_control_is_accessible_and_responsive() -> None:
    markup = (ROOT / "app" / "frontend" / "index.html").read_text(encoding="utf-8")
    css = STYLE_PATH.read_text(encoding="utf-8")

    assert "<fieldset" in markup
    assert "<legend>Section size</legend>" in markup
    assert markup.count('name="section-size-mode"') == 2
    assert 'for="section-max-characters"' in markup
    assert 'id="section-max-characters"' in markup
    assert 'type="number"' in markup
    assert ':min="sectionSizeControl?.minimum"' in markup
    assert ':max="sectionSizeControl?.maximum"' in markup
    assert ':step="sectionSizeControl?.step"' in markup
    assert "aria-invalid" in markup
    assert "aria-describedby" in markup
    assert (
        'id="section-size-validation" role="status" aria-live="polite"'
        in markup
    )
    assert ".section-size-grid" in css
    assert re.search(
        r"@media\s*\(max-width:\s*900px\)\s*\{[^}]*?\.section-size-grid\s*\{[^}]*?grid-template-columns:\s*1fr",
        css,
        flags=re.DOTALL,
    )
    assert css.index("grid-template-columns: minmax(0, 1fr) minmax(150px, 0.9fr)") < css.rindex(
        ".section-size-grid { grid-template-columns: 1fr; }"
    )
