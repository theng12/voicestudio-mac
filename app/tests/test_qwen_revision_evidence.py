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


def test_voxcpm_clone_records_model_and_reference_revisions(monkeypatch):
    revision = "3" * 40
    digest = "b" * 64
    monkeypatch.setattr(cache, "snapshot_revision", lambda _repo: revision)
    monkeypatch.setattr(
        voices.library,
        "get",
        lambda voice_id: (
            SimpleNamespace(audio_sha256=digest)
            if voice_id == "voice-library-1"
            else None
        ),
    )
    job = generation.GenerationJob(
        job_id="voxcpm-proof",
        mode="txt2speech",
        params={
            "repo": "mlx-community/VoxCPM2-4bit",
            "voice_library_id": "voice-library-1",
        },
    )

    generation.GenerationManager._record_local_revision_evidence(job)

    result = job.serialize()
    assert job.model_revision == revision
    assert job.voice_revision == digest
    assert result["internal_model_id"] == "mlx-community/VoxCPM2-4bit"
    assert result["runtime_revision"] == revision
    assert result["voice_library_id"] == "voice-library-1"


def test_kokoro_preset_records_model_and_voice_revision(monkeypatch):
    revision = "4" * 40
    monkeypatch.setattr(cache, "snapshot_revision", lambda _repo: revision)
    job = generation.GenerationJob(
        job_id="kokoro-proof",
        mode="txt2speech",
        params={
            "repo": "mlx-community/Kokoro-82M-bf16",
            "voice": "AF_Heart",
        },
    )

    generation.GenerationManager._record_local_revision_evidence(job)

    result = job.serialize()
    assert result["runtime_revision"] == revision
    assert result["voice_revision"] == f"{revision}:preset:af_heart"


def test_chatterbox_clone_records_model_and_reference_revisions(monkeypatch):
    revision = "5" * 40
    digest = "c" * 64
    monkeypatch.setattr(cache, "snapshot_revision", lambda _repo: revision)
    monkeypatch.setattr(
        voices.library,
        "get",
        lambda voice_id: (
            SimpleNamespace(audio_sha256=digest)
            if voice_id == "accountvoice1"
            else None
        ),
    )
    job = generation.GenerationJob(
        job_id="chatterbox-proof",
        mode="txt2speech",
        params={
            "repo": "mlx-community/chatterbox-4bit",
            "voice_library_id": "accountvoice1",
        },
    )

    generation.GenerationManager._record_local_revision_evidence(job)

    result = job.serialize()
    assert result["runtime_revision"] == revision
    assert result["voice_revision"] == digest
