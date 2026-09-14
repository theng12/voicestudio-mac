from __future__ import annotations

import json
from pathlib import Path
import subprocess

from backend import catalog


REPO = "khmerttsopensource/khmer-tts"
ROOT = Path(__file__).parents[2]


def test_khmer_tts_catalog_publishes_its_local_single_voice_contract() -> None:
    family = catalog.FAMILIES["mms-vits"]
    assert family.text_guidance.soft_max_chars == 500
    assert family.text_guidance.chunking == "hard-cap"
    assert family.text_guidance.note == (
        "For initial testing, use short Khmer passages up to 500 characters; "
        "long-text chunking is not enabled."
    )

    model = catalog.get_model(REPO)
    assert model is not None
    assert model.family == "mms-vits"
    assert model.size_gb == 0.3322
    assert model.gated is False
    assert model.min_unified_memory_gb == 8
    assert model.capabilities == ("tts",)
    assert model.sample_rate_hz == 16000
    assert model.languages == ("km",)

    published = catalog.serialize_model(model)
    assert published["apple_optimized"] is False
    assert published["reference_audio"]["supported"] is False
    assert published["language_support"] == {
        "input_selection": "none",
        "enumeration_status": "exact",
        "codes": ["km"],
        "claimed_count": None,
        "claimed_lower_bound": None,
        "runtime_enforced": False,
    }


def test_khmer_tts_frontend_uses_fixed_voice_safe_defaults_and_request_fields() -> None:
    probe = r"""
const fs = require('fs');
const vm = require('vm');
global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'));

(async () => {
  const app = studio();
  const repo = 'khmerttsopensource/khmer-tts';
  app.models = [{
    repo,
    family: 'mms-vits',
    label: 'Khmer TTS',
    capabilities: ['tts'],
    cache: {state: 'cached'},
  }];
  app.families = {'mms-vits': {text_guidance: {
    soft_max_chars: 500,
    chunking: 'hard-cap',
    note: 'For initial testing, use short Khmer passages up to 500 characters; long-text chunking is not enabled.',
  }}};
  app.gen.available = true;
  app.gen.device = 'mps';
  app.gen.repo = repo;
  const authoredText = 'Keep this authored draft when switching models.';
  app.gen.text = authoredText;
  app.gen.normalize_text = true;
  app.gen.batchCount = 1;
  app.gen.seed = 7;
  app._requestNotificationPermission = () => {};
  app.pushToast = () => {};

  app.onModelChange();
  const preservedText = app.gen.text;
  app.gen.text = '';
  app.onModelChange();
  const blankInitialText = app.gen.text;
  app.gen.normalize_text = true;
  let requestBody = null;
  global.fetch = async (_url, options) => {
    requestBody = JSON.parse(options.body);
    return {ok: true, json: async () => ({job: {id: 'khmer-job'}})};
  };
  await app.submitGenerate();

  app.gen.submitting = false;
  app.gen.text = 'ក'.repeat(501);
  const result = {
    isKhmerFamily: app.isMmsVits(repo),
    voiceSummary: app.selectedVoiceSummary,
    computeSummary: app.selectedComputeSummary,
    authoredText,
    preservedText,
    blankInitialText,
    requestBody,
    overCap: app.textHardCapExceeded,
    canSubmitOverCap: app.canSubmit,
    submitHint: app.submitHint,
  };
  process.stdout.write(JSON.stringify(result));
})();
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            probe,
            str(ROOT / "app" / "frontend" / "prompts.js"),
            str(ROOT / "app" / "frontend" / "app.js"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    actual = json.loads(result.stdout)

    assert actual["isKhmerFamily"] is True
    assert actual["voiceSummary"] == "Fixed Khmer voice"
    assert actual["computeSummary"] == "CPU"
    assert actual["preservedText"] == actual["authoredText"]
    assert any("\u1780" <= char <= "\u17ff" for char in actual["blankInitialText"])
    assert len(actual["blankInitialText"]) <= 500
    assert actual["requestBody"]["language"] == "km"
    assert actual["requestBody"]["normalize_text"] is False
    assert actual["requestBody"]["voice"] is None
    assert actual["requestBody"]["voice_library_id"] is None
    assert actual["requestBody"]["instruct"] is None
    assert actual["overCap"] is True
    assert actual["canSubmitOverCap"] is False
    assert actual["submitHint"] == "Khmer TTS currently accepts up to 500 characters per generation."


def test_khmer_tts_exposes_the_existing_seed_control() -> None:
    markup = (ROOT / "app" / "frontend" / "index.html").read_text(encoding="utf-8")
    assert (
        'x-show="isMlxAudio(gen.repo) || isBark(gen.repo) || isMmsVits(gen.repo)"'
        in markup
    )
