from types import SimpleNamespace

from backend import cache, generation, voices


def test_qwen_preset_records_model_and_voice_revision(monkeypatch):
    revision = "1" * 40
    monkeypatch.setattr(cache, "snapshot_revision", lambda _repo: revision)
    job = generation.GenerationJob(
        job_id="preset-proof",
        mode="txt2speech",
        params={
            "repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
            "preset_speaker": "Ryan",
        },
    )

    generation.GenerationManager._record_qwen_revision_evidence(job)

    assert job.model_revision == revision
    assert job.voice_revision == f"{revision}:preset:ryan"
    assert job.serialize()["voice_revision"] == job.voice_revision


def test_qwen_clone_records_reference_audio_digest(monkeypatch):
    revision = "2" * 40
    digest = "a" * 64
    monkeypatch.setattr(cache, "snapshot_revision", lambda _repo: revision)
    monkeypatch.setattr(
        voices.library,
        "get",
        lambda voice_id: SimpleNamespace(audio_sha256=digest) if voice_id == "074743daa991" else None,
    )
    job = generation.GenerationJob(
        job_id="clone-proof",
        mode="txt2speech",
        params={
            "repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
            "voice_library_id": "074743daa991",
        },
    )

    generation.GenerationManager._record_qwen_revision_evidence(job)

    assert job.model_revision == revision
    assert job.voice_revision == digest
