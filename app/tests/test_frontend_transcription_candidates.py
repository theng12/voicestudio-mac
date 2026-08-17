from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "frontend" / "app.js"
MARKUP = ROOT / "frontend" / "index.html"
STYLES = ROOT / "frontend" / "style.css"


def _run_node(probe: str) -> dict:
    result = subprocess.run(
        ["node", "-e", probe, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_candidate_selection_enforces_word_timing_capability() -> None:
    probe = r"""
const fs = require('fs');
const vm = require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
const app = studio();
app.stt.models = [
  { repo: 'moonshine-ai/moonshine-base', supports_word_timestamps: false },
  { repo: 'mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit', supports_word_timestamps: true },
];
app.stt.wordTimestamps = true;
app.selectTranscriptionModel('moonshine-ai/moonshine-base');
const moonshine = {
  repo: app.stt.model,
  supported: app.sttWordTimestampsSupported,
  selected: app.stt.wordTimestamps,
};
app.selectTranscriptionModel('mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit');
const nemotron = {
  repo: app.stt.model,
  supported: app.sttWordTimestampsSupported,
};
process.stdout.write(JSON.stringify({moonshine, nemotron}));
"""

    observed = _run_node(probe)

    assert observed == {
        "moonshine": {
            "repo": "moonshine-ai/moonshine-base",
            "supported": False,
            "selected": False,
        },
        "nemotron": {
            "repo": "mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit",
            "supported": True,
        },
    }


def test_download_flow_polls_every_transcription_engine() -> None:
    probe = r"""
const fs = require('fs');
const vm = require('vm');
global.fetch = async () => ({ ok: true, json: async () => ({}) });
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
(async () => {
  const app = studio();
  const repo = 'moonshine-ai/moonshine-base';
  app.stt.models = [{ repo }];
  app.pendingDownload = { repo };
  const polled = [];
  app._pollTranscriptionUntilCached = value => polled.push(value);
  app.refreshCatalog = async () => { throw new Error('wrong refresh'); };
  await app.startDownload();
  process.stdout.write(JSON.stringify({polled}));
})();
"""

    assert _run_node(probe) == {"polled": ["moonshine-ai/moonshine-base"]}


def test_transcription_ui_uses_generic_copy_and_truthful_candidate_badges() -> None:
    markup = MARKUP.read_text(encoding="utf-8")

    assert "Transcription models" in markup
    assert '>Transcription model</label>' in markup
    assert 'for="transcription-model"' in markup
    assert 'id="transcription-model"' in markup
    assert "Internal pilot" in markup
    assert "8 GB candidate" in markup
    assert "m.engine === 'nemotron' ? 'Nemotron'" in markup
    assert 'x-text="m.languages"' in markup
    assert "Segment timing" in markup
    assert "Word timing" in markup
    assert "Long-form" in markup
    assert ':disabled="!sttWordTimestampsSupported"' in markup
    assert "Word timing is unavailable for this model." in markup
    assert "Whisper model</label>" not in markup
    assert "#transcription-model { min-height: 44px; }" in STYLES.read_text(
        encoding="utf-8"
    )
