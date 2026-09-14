from contextlib import nullcontext
from types import SimpleNamespace
import sys

import numpy as np
import pytest
import soundfile as sf

from backend import generation


REPO = "khmerttsopensource/khmer-tts"
REVISION = "c9380a9d1c817f2b21980d54f29f7a61b0d626f5"


@pytest.fixture
def worker(monkeypatch, tmp_path):
    calls = []
    audio = np.array([0.0, 0.1, -0.1], dtype=np.float32)
    tensor = SimpleNamespace(squeeze=lambda: SimpleNamespace(
        cpu=lambda: SimpleNamespace(numpy=lambda: audio)))
    class Tokenizer:
        pad_token_id = 0
        unk_token_id = 74
        def __call__(self, text, **kwargs):
            calls.append(("text", text))
            return {"input_ids": SimpleNamespace(tolist=lambda: [[0, 61, 0, 13, 0]])}
    class Model:
        config = SimpleNamespace(sampling_rate=16000)
        def eval(self):
            return self
        def __call__(self, **kwargs):
            return SimpleNamespace(waveform=tensor)
    def loader(kind, value):
        def load(path, **kwargs):
            calls.append((kind, path, kwargs))
            return value
        return SimpleNamespace(from_pretrained=load)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=loader("tokenizer", Tokenizer()), VitsModel=loader("model", Model())))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        manual_seed=lambda seed: calls.append(("seed", seed)), inference_mode=nullcontext))
    monkeypatch.setattr(generation.cache, "snapshot_revision", lambda repo: REVISION)
    monkeypatch.setattr(generation.cache, "repo_cache_dir", lambda repo: tmp_path)
    runtime = object.__new__(generation.GenerationManager)
    monkeypatch.setattr(runtime, "_evict_loaded_models", lambda **kwargs: {})
    return runtime, calls, audio


@pytest.mark.parametrize("text", ["សួស្តីអ្នកទាំងអស់គ្នា", "ឱ"])
def test_worker_preserves_khmer_and_uses_selected_offline_snapshot(worker, tmp_path, text):
    runtime, calls, _ = worker
    job = generation.GenerationJob("khmer", "txt2speech", {"repo": REPO, "text": text, "seed": 7,
                                                          "normalize_text": True})
    output = tmp_path / "test.wav"
    runtime._generate_mms_vits(job, SimpleNamespace(repo=REPO), output)
    assert ("text", text) in calls
    assert ("seed", 7) in calls
    assert job.resolved_seed == 7
    for kind in ("tokenizer", "model"):
        call = next(item for item in calls if item[0] == kind)
        assert call[1] == str(tmp_path / "snapshots" / REVISION)
        assert call[2]["local_files_only"] is True
    assert sf.info(output).samplerate == 16000
    assert sf.info(output).frames == 3


@pytest.mark.parametrize("text", ["", "hello", "ស" * 501])
def test_invalid_input_fails_before_loading_weights(worker, tmp_path, text):
    runtime, calls, _ = worker
    job = generation.GenerationJob("invalid", "txt2speech", {"repo": REPO, "text": text})
    with pytest.raises(ValueError):
        runtime._generate_mms_vits(job, SimpleNamespace(repo=REPO), tmp_path / "no.wav")
    assert not calls


def test_worker_rejects_nonfinite_audio(worker, tmp_path):
    runtime, _, audio = worker
    audio[1] = np.nan
    output = tmp_path / "no.wav"
    job = generation.GenerationJob("nan", "txt2speech", {"repo": REPO, "text": "សួស្តី"})
    with pytest.raises(RuntimeError, match="audio"):
        runtime._generate_mms_vits(job, SimpleNamespace(repo=REPO), output)
    assert not output.exists()


def test_cancel_before_load_produces_no_audio(worker, tmp_path):
    runtime, calls, _ = worker
    job = generation.GenerationJob("cancel", "txt2speech", {"repo": REPO, "text": "សួស្តី"})
    job.cancel_event.set()
    output = tmp_path / "no.wav"
    runtime._generate_mms_vits(job, SimpleNamespace(repo=REPO), output)
    assert not calls
    assert not output.exists()


def test_availability_requires_all_vits_dependencies(monkeypatch):
    monkeypatch.setattr(generation, "_package_installed", lambda name: name in {"torch", "transformers", "numpy", "soundfile"})
    assert "mms-vits" in generation.availability()["wired_families"]
    monkeypatch.setattr(generation, "_package_installed", lambda name: name != "soundfile")
    assert "mms-vits" not in generation.availability()["wired_families"]


def test_native_dispatch_routes_vits_and_reports_runtime_ready(monkeypatch, tmp_path):
    model = SimpleNamespace(repo=REPO, family="mms-vits")
    monkeypatch.setattr(generation.catalog, "get_model", lambda repo: model)
    monkeypatch.setattr(generation.cache, "cache_state", lambda repo: "cached")
    monkeypatch.setattr(generation, "_package_installed", lambda name: True)
    runtime = object.__new__(generation.GenerationManager)
    monkeypatch.setattr(runtime, "_memory_preflight", lambda entry: None)
    calls = []
    monkeypatch.setattr(runtime, "_generate_mms_vits", lambda *args: calls.append(args))
    job = generation.GenerationJob("dispatch", "txt2speech", {"repo": REPO, "text": "សួស្តី"})
    assert runtime.runtime_ready_for_family("mms-vits")
    output = tmp_path / "dispatch.wav"
    runtime._dispatch_txt2speech_direct(job, output, postprocess_speed=False)
    assert calls == [(job, model, output)]


def test_completed_khmer_job_records_model_and_fixed_voice_revision(monkeypatch):
    monkeypatch.setattr(generation.cache, "snapshot_revision", lambda repo: REVISION)
    job = generation.GenerationJob("revision", "txt2speech", {"repo": REPO, "text": "សួស្តី"})
    generation.GenerationManager._record_local_revision_evidence(job)
    assert job.model_revision == REVISION
    assert job.voice_revision == f"{REVISION}:fixed:khmer"
