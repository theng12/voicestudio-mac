"""Regression coverage for bounded ownership of a native execution process."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest
import numpy as np
import soundfile as sf

from backend import generation
from backend import native_executor
from backend.native_executor import ExclusiveNativeExecutor, NativeRunOutcome


def _hanging_native_call(_payload, _cancel_requested):
    """A stand-in for an uninterruptible native model call; never loads a model."""
    while True:
        time.sleep(0.05)


def _fast_native_call(_payload, _cancel_requested):
    return {"completed": True}


def _cached_native_call(payload, _cancel_requested):
    return {"pid": os.getpid(), "action": payload["action"]}


def _release_hanging_native_call(payload, _cancel_requested):
    if payload["action"] == "release":
        while True:
            time.sleep(0.05)
    return {"ready": True}


def _release_error_native_call(payload, _cancel_requested):
    if payload["action"] == "release":
        raise RuntimeError("release failed")
    return {"ready": True}


def _crashing_native_call(_payload, _cancel_requested):
    os._exit(7)


def _spawn_reports_no_server_generation_manager(_payload, _cancel_requested):
    from backend import generation as child_generation

    return {"server_manager_constructed": child_generation.manager is not None}


def test_cancel_terminates_only_the_owned_spawned_native_process_within_deadline():
    executor = ExclusiveNativeExecutor(_hanging_native_call, cooperative_grace=0.05,
                                       terminate_timeout=0.5, kill_timeout=0.5)
    requested = threading.Event()
    timer = threading.Timer(0.05, requested.set)
    timer.start()
    started = time.monotonic()
    try:
        outcome = executor.run({"kind": "synthetic-hang"}, requested)
    finally:
        timer.cancel()
        executor.close()

    assert outcome.state == "cancelled"
    assert outcome.generation == 1
    assert outcome.run_id
    assert outcome.terminated is True
    assert time.monotonic() - started < 1.5


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group fallback")
def test_cancel_uses_exact_process_handle_during_setsid_startup_race(monkeypatch):
    executor = ExclusiveNativeExecutor(_hanging_native_call, cooperative_grace=0.01,
                                       terminate_timeout=0.5, kill_timeout=0.5)
    requested = threading.Event()
    timer = threading.Timer(0.02, requested.set)
    monkeypatch.setattr(native_executor.os, "killpg",
                        lambda *_args: (_ for _ in ()).throw(ProcessLookupError()))
    timer.start()
    try:
        outcome = executor.run({"kind": "synthetic-hang"}, requested)
    finally:
        timer.cancel()
        executor.close()

    assert outcome.state == "cancelled"
    assert outcome.terminated is True


def test_cancel_wins_when_matching_result_arrives_after_request():
    executor = ExclusiveNativeExecutor(_fast_native_call)
    requested = threading.Event()
    requested.set()
    try:
        outcome = executor.run({"kind": "synthetic-fast"}, requested)
    finally:
        executor.close()

    assert outcome.state == "cancelled"
    assert outcome.terminated is False


def test_normal_commands_reuse_the_same_spawned_executor_cache():
    executor = ExclusiveNativeExecutor(_cached_native_call)
    try:
        first = executor.run({"action": "first"}, threading.Event())
        second = executor.run({"action": "second"}, threading.Event())
    finally:
        executor.close()

    assert first.state == second.state == "done"
    assert first.generation == second.generation == 1
    assert first.value["pid"] == second.value["pid"]


def test_spawned_native_child_does_not_construct_the_server_history_manager():
    executor = ExclusiveNativeExecutor(_spawn_reports_no_server_generation_manager)
    try:
        outcome = executor.run({"action": "probe"}, threading.Event())
    finally:
        executor.close()

    assert generation.manager is not None
    assert outcome.state == "done"
    assert outcome.value == {"server_manager_constructed": False}


def test_started_callback_failure_does_not_lease_or_submit_the_executor():
    executor = ExclusiveNativeExecutor(_fast_native_call)

    def fail_before_submit(*_args):
        raise RuntimeError("history unavailable")

    try:
        with pytest.raises(RuntimeError, match="history unavailable"):
            executor.run({"kind": "must-not-submit"}, threading.Event(), on_started=fail_before_submit)
        retry = executor.run({"kind": "retry"}, threading.Event())
    finally:
        executor.close()

    assert retry.state == "done"
    assert retry.generation == 1


def test_idle_release_is_bounded_and_reclaims_only_its_executor():
    executor = ExclusiveNativeExecutor(_release_hanging_native_call,
                                       terminate_timeout=0.5, kill_timeout=0.5)
    try:
        assert executor.run({"action": "warmup"}, threading.Event()).state == "done"
        started = time.monotonic()
        released = executor.release({"action": "release"}, acknowledgement_timeout=0.02)
    finally:
        executor.close()

    assert released.state == "done"
    assert released.terminated is True
    assert time.monotonic() - started < 1.5


def test_idle_release_error_reclaims_the_same_executor_cache():
    executor = ExclusiveNativeExecutor(_release_error_native_call,
                                       terminate_timeout=0.5, kill_timeout=0.5)
    try:
        assert executor.run({"action": "warmup"}, threading.Event()).state == "done"
        released = executor.release({"action": "release"})
    finally:
        executor.close()

    assert released.state == "done"
    assert released.terminated is True


def test_unverified_exit_fences_executor_from_new_submission(monkeypatch):
    executor = ExclusiveNativeExecutor(_hanging_native_call, cooperative_grace=0.01)
    requested = threading.Event()
    timer = threading.Timer(0.02, requested.set)
    original_discard = executor._discard
    monkeypatch.setattr(executor, "_discard", lambda: False)
    timer.start()
    try:
        first = executor.run({"kind": "synthetic-hang"}, requested)
        second = executor.run({"kind": "must-not-dispatch"}, threading.Event())
    finally:
        timer.cancel()
        monkeypatch.setattr(executor, "_discard", original_discard)
        executor.close()

    assert first.state == "uncertain"
    assert second.state == "uncertain"
    assert second.run_id == ""
    assert second.generation == 1


def test_spontaneous_child_exit_fences_all_later_submissions():
    executor = ExclusiveNativeExecutor(_crashing_native_call)
    try:
        first = executor.run({"action": "crash"}, threading.Event())
        assert executor._discard() is False
        second = executor.run({"action": "must-not-submit"}, threading.Event())
    finally:
        executor.close()

    assert first.state == "uncertain"
    assert first.generation == 1
    assert second.state == "uncertain"
    assert second.generation == 1
    assert second.run_id == ""


def test_parent_owned_ffmpeg_stops_on_the_job_cancel_event(tmp_path, monkeypatch):
    output = tmp_path / "source.wav"
    sf.write(output, np.zeros(100, dtype=np.float32), 1_000, subtype="PCM_16")
    stopped: list[tuple[int, int]] = []

    class HangingFfmpeg:
        pid = 12345
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            self.returncode = -15
            return self.returncode

        def communicate(self):
            return "", ""

    monkeypatch.setattr(generation, "_find_ffmpeg_executable", lambda: Path("/fake/ffmpeg"))
    monkeypatch.setattr(generation.subprocess, "Popen", lambda *_args, **_kwargs: HangingFfmpeg())
    monkeypatch.setattr(generation.os, "killpg", lambda pid, sig: stopped.append((pid, sig)))
    cancelled = threading.Event()
    cancelled.set()

    assert generation._apply_mlx_output_speed(output, 1.1, "qwen3-tts", cancelled) is False
    assert stopped == [(12345, generation.signal.SIGTERM)]
    assert not list(tmp_path.glob(".source.tempo-*.wav"))


def test_parent_owned_ffmpeg_reports_uncertain_when_termination_cannot_be_verified(tmp_path, monkeypatch):
    output = tmp_path / "source.wav"
    sf.write(output, np.zeros(100, dtype=np.float32), 1_000, subtype="PCM_16")

    class UnstoppableFfmpeg:
        pid = 23456
        returncode = None

        def poll(self):
            return None

        def wait(self, timeout):
            raise generation.subprocess.TimeoutExpired("ffmpeg", timeout)

        def communicate(self):
            return "", ""

    monkeypatch.setattr(generation, "_find_ffmpeg_executable", lambda: Path("/fake/ffmpeg"))
    monkeypatch.setattr(generation.subprocess, "Popen", lambda *_args, **_kwargs: UnstoppableFfmpeg())
    monkeypatch.setattr(generation.os, "killpg", lambda *_args: None)
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(generation.NativeExecutionUncertain):
        generation._apply_mlx_output_speed(output, 1.1, "qwen3-tts", cancelled)
    assert not list(tmp_path.glob(".source.tempo-*.wav"))


def test_parent_owned_ffmpeg_timeout_group_kills_and_reports_uncertain(tmp_path, monkeypatch):
    output = tmp_path / "source.wav"
    sf.write(output, np.zeros(100, dtype=np.float32), 1_000, subtype="PCM_16")
    stopped: list[tuple[int, int]] = []

    class UnstoppableFfmpeg:
        pid = 34567
        returncode = None

        def poll(self):
            return None

        def wait(self, timeout):
            raise generation.subprocess.TimeoutExpired("ffmpeg", timeout)

    ticks = iter((0.0, 301.0))
    monkeypatch.setattr(generation, "_find_ffmpeg_executable", lambda: Path("/fake/ffmpeg"))
    monkeypatch.setattr(generation.subprocess, "Popen", lambda *_args, **_kwargs: UnstoppableFfmpeg())
    monkeypatch.setattr(generation.os, "killpg", lambda pid, sig: stopped.append((pid, sig)))
    monkeypatch.setattr(generation.time, "monotonic", lambda: next(ticks))

    with pytest.raises(generation.NativeExecutionUncertain):
        generation._apply_mlx_output_speed(output, 1.1, "qwen3-tts")
    assert stopped == [(34567, generation.signal.SIGKILL)]
    assert not list(tmp_path.glob(".source.tempo-*.wav"))


def test_idle_memory_release_evicts_the_reused_executor_cache_without_stopping_work(monkeypatch):
    released: list[dict] = []

    class IdleExecutor:
        def release(self, payload):
            released.append(payload)
            return NativeRunOutcome("done", "release", 1, value={"released": True})

    manager = generation.GenerationManager.__new__(generation.GenerationManager)
    manager._mlx_audio_model = None
    manager._mlx_audio_model_repo = None
    manager._f5_tts_model = None
    manager._f5_tts_model_repo = None
    manager._native_executor = IdleExecutor()
    manager._native_loaded_model_keys = [("local/voice", "tts-mlx")]
    monkeypatch.setattr(generation, "_release_device_memory", lambda _device: None)

    result = manager._evict_loaded_models("test")

    assert released == [{"action": "release"}]
    assert manager._native_loaded_model_keys == []
    assert result["released"] is True
    assert "cleared native executor model cache" in result["actions"]


def test_parent_sequences_long_form_native_sections_and_joins_only_after_completion(
    tmp_path, monkeypatch,
):
    calls: list[dict] = []

    class FakeExecutor:
        def run(self, payload, _cancel_event, *, on_started):
            calls.append(payload)
            on_started(f"run-{len(calls)}", 7)
            sf.write(payload["output_path"], np.full(100, len(calls) / 10, dtype=np.float32),
                     1_000, subtype="PCM_16")
            return NativeRunOutcome(
                "done", f"run-{len(calls)}", 7,
                value={
                    "loaded_models": [["local/voice", "tts-mlx"]],
                    "resource_usage": {
                        "schema": generation.resource_telemetry.SCHEMA,
                        "schema_version": generation.resource_telemetry.SCHEMA_VERSION,
                        "worker": {"peak_rss_gb": float(len(calls))},
                        "sampling": {"samples": 1, "started_at": float(len(calls)),
                                     "finished_at": float(len(calls))},
                    },
                },
            )

    model = SimpleNamespace(family="voxcpm-mlx", repo="local/voice")
    monkeypatch.setattr(generation.catalog, "get_model", lambda _repo: model)
    monkeypatch.setattr(generation, "_normalized_speech_text", lambda *_args: "first second")
    monkeypatch.setattr(generation, "_internal_mlx_text_chunks", lambda *_args, **_kwargs: ["first", "second"])
    manager = generation.GenerationManager.__new__(generation.GenerationManager)
    manager._native_executor = FakeExecutor()
    manager._native_loaded_model_keys = []
    manager._persist = lambda **_kwargs: None
    job = generation.GenerationJob(
        "long-form", "txt2speech", {"repo": "local/voice", "text": "first second", "seed": 3},
    )
    output = tmp_path / "joined.wav"

    manager._dispatch_txt2speech(job, output)

    assert [call["params"]["text"] for call in calls] == ["first", "second"]
    assert all(call["params"]["_native_single_section"] for call in calls)
    assert calls[0]["params"]["_native_continue_rng"] is False
    assert calls[1]["params"]["_native_continue_rng"] is True
    assert job.chunk_index == job.chunk_total == 2
    assert job.resource_usage["worker"]["peak_rss_gb"] == 2.0
    assert job.resource_usage["command_count"] == 2
    assert output.exists()


def test_parent_long_form_resolves_random_seed_once_before_child_sections(tmp_path, monkeypatch):
    calls: list[dict] = []

    class FakeExecutor:
        def run(self, payload, _cancel_event, *, on_started):
            calls.append(payload)
            on_started(f"run-{len(calls)}", 7)
            sf.write(payload["output_path"], np.ones(100, dtype=np.float32), 1_000,
                     subtype="PCM_16")
            return NativeRunOutcome("done", f"run-{len(calls)}", 7, value={})

    model = SimpleNamespace(family="voxcpm-mlx", repo="local/voice")
    monkeypatch.setattr(generation.catalog, "get_model", lambda _repo: model)
    monkeypatch.setattr(generation, "_normalized_speech_text", lambda *_args: "first second")
    monkeypatch.setattr(generation, "_internal_mlx_text_chunks", lambda *_args, **_kwargs: ["first", "second"])
    monkeypatch.setattr("random.randint", lambda *_args: 2468)
    manager = generation.GenerationManager.__new__(generation.GenerationManager)
    manager._native_executor = FakeExecutor()
    manager._native_loaded_model_keys = []
    manager._persist = lambda **_kwargs: None
    job = generation.GenerationJob(
        "random-long-form", "txt2speech", {"repo": "local/voice", "text": "first second", "seed": -1},
    )
    output = tmp_path / "joined.wav"

    manager._dispatch_txt2speech(job, output)

    assert job.resolved_seed == 2468
    assert [call["params"]["_qwen_attempt_seed"] for call in calls] == [2468, 2468]
    assert [call["params"]["_native_continue_rng"] for call in calls] == [False, True]


def test_cancel_persistence_blocks_final_promotion_until_the_event_is_set(tmp_path):
    manager = generation.GenerationManager()
    job = generation.GenerationJob("cancel-promotion", "txt2speech", {"repo": "local/voice"}, state="running")
    manager._jobs = {job.job_id: job}
    partial = tmp_path / "partial.wav"
    final = tmp_path / "final.wav"
    partial.write_bytes(b"audio")
    job.partial_output_path = str(partial)
    persist_entered = threading.Event()
    allow_persist = threading.Event()
    promoted: list[Path | None] = []
    cancelled: list[bool] = []

    def persist(*, strict=False):
        if strict:
            persist_entered.set()
            assert allow_persist.wait(1)
        return True

    manager._persist = persist
    cancelling = threading.Thread(target=lambda: cancelled.append(manager.cancel(job.job_id)))
    cancelling.start()
    assert persist_entered.wait(1)
    finalizing = threading.Thread(
        target=lambda: promoted.append(manager._promote_or_cancel_output(job, partial, final)),
    )
    finalizing.start()
    assert finalizing.is_alive()
    allow_persist.set()
    cancelling.join(1)
    finalizing.join(1)

    assert cancelled == [True]
    assert job.cancel_event.is_set()
    assert job.state == "cancelled"
    assert promoted == [None]
    assert not partial.exists()
    assert not final.exists()


def test_parent_long_form_join_cancellation_never_promotes_a_partial_wav(tmp_path):
    section = tmp_path / "section.wav"
    output = tmp_path / "joined.wav"
    sf.write(section, np.ones(100, dtype=np.float32), 1_000, subtype="PCM_16")
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(InterruptedError, match="join cancelled"):
        generation._join_long_form_wavs(
            [section], output, "voxcpm-mlx", cancel_event=cancelled,
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".*.joining"))


def test_restart_marks_persisted_active_job_uncertain_and_keeps_request_identity(tmp_path, monkeypatch):
    history = tmp_path / ".history.json"
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", history)
    partial = tmp_path / ".active-job.partial.wav"
    partial.write_bytes(b"incomplete")
    active = generation.GenerationJob(
        job_id="active-job", mode="txt2speech",
        params={"repo": "mlx-community/Kokoro-82M-bf16", "client_request_id": "hub:1:2"},
        client_request_params={"repo": "mlx-community/Kokoro-82M-bf16", "client_request_id": "hub:1:2"},
        state="cancel_requested", partial_output_path=str(partial),
    )
    manager = generation.GenerationManager.__new__(generation.GenerationManager)
    manager._lock = threading.RLock()
    manager._jobs = {active.job_id: active}
    manager._persist()

    restored = generation.GenerationManager.__new__(generation.GenerationManager)
    restored._lock = threading.RLock()
    restored._jobs = {}
    restored._load_history()

    job = restored._jobs["active-job"]
    assert job.state == "uncertain"
    assert job.params["client_request_id"] == "hub:1:2"
    assert job.output_path is None
    assert job.partial_output_path is None
    assert not partial.exists()
    assert job.serialize()["output_url"] is None


def test_failed_queued_acceptance_never_starts_a_worker_or_leaves_dedupe_state(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", tmp_path / ".history.json")
    manager = generation.GenerationManager()
    monkeypatch.setattr(generation.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(generation.PersistenceError):
        manager.start_txt2speech({
            "repo": "mlx-community/Kokoro-82M-bf16", "client_request_id": "durable-accept",
        })

    assert manager._jobs == {}


def test_failed_execution_identity_write_does_not_submit_native_command(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", tmp_path / ".history.json")
    submitted: list[dict] = []

    class FakeExecutor:
        def run(self, payload, _cancel_event, *, on_started):
            on_started("run-1", 1)
            submitted.append(payload)
            return NativeRunOutcome("done", "run-1", 1, value={})

    manager = generation.GenerationManager.__new__(generation.GenerationManager)
    manager._lock = threading.RLock()
    job = generation.GenerationJob("durable-run", "txt2speech", {"repo": "local/voice"}, state="running")
    manager._jobs = {job.job_id: job}
    manager._native_executor = FakeExecutor()
    manager._native_loaded_model_keys = []
    monkeypatch.setattr(generation.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(generation.PersistenceError):
        manager._run_native_payload(job, {"action": "generate", "job_id": job.job_id})

    assert submitted == []
    assert job.execution_run_id is None
    assert job.executor_generation is None


def test_failed_cancel_requested_write_does_not_signal_running_work(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", tmp_path / ".history.json")
    manager = generation.GenerationManager()
    job = generation.GenerationJob("durable-cancel", "txt2speech", {"repo": "local/voice"}, state="running")
    manager._jobs = {job.job_id: job}
    monkeypatch.setattr(generation.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))

    assert manager.cancel(job.job_id) is False
    assert job.state == "running"
    assert job.cancel_event.is_set() is False
    assert job.cancel_requested_at is None


def test_cancel_requested_timestamp_is_persisted_before_signalling_work(tmp_path, monkeypatch):
    history = tmp_path / ".history.json"
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", history)
    manager = generation.GenerationManager()
    job = generation.GenerationJob("timestamped-cancel", "txt2speech", {"repo": "local/voice"}, state="running")
    manager._jobs = {job.job_id: job}

    assert manager.cancel(job.job_id) is True
    saved = json.loads(history.read_text())["jobs"]
    assert isinstance(job.cancel_requested_at, float)
    assert saved[0]["cancel_requested_at"] == job.cancel_requested_at
    assert job.cancel_event.is_set() is True


def test_queued_job_is_durable_before_worker_start_and_reloads_as_uncertain(tmp_path, monkeypatch):
    history = tmp_path / ".history.json"
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", history)
    manager = generation.GenerationManager()
    params = {"repo": "mlx-community/Kokoro-82M-bf16", "client_request_id": "queued-durable"}
    generation._GEN_LOCK.acquire()
    try:
        job = manager.start_txt2speech(params)
        saved = json.loads(history.read_text())["jobs"]
        assert any(row["job_id"] == job.job_id and row["state"] == "queued" for row in saved)

        restored = generation.GenerationManager()
        recovered = restored.get(job.job_id)
        assert recovered is not None
        assert recovered.state == "uncertain"
        assert restored.start_txt2speech(params) is recovered
    finally:
        manager.cancel(job.job_id)
        generation._GEN_LOCK.release()
        job.thread.join(timeout=1)


def test_history_keeps_every_active_job_beyond_terminal_retention_limit(tmp_path, monkeypatch):
    history = tmp_path / ".history.json"
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", history)
    monkeypatch.setattr(generation, "HISTORY_MAX", 2)
    manager = generation.GenerationManager()
    active = generation.GenerationJob(
        "active-old", "txt2speech",
        {"repo": "local/voice", "client_request_id": "must-survive"},
        state="queued", created_at=1.0,
    )
    terminals = [
        generation.GenerationJob(
            f"done-{index}", "txt2speech", {"repo": "local/voice"},
            state="done", created_at=float(index), finished_at=float(index),
        )
        for index in range(2, 6)
    ]
    manager._jobs = {job.job_id: job for job in [active, *terminals]}

    assert manager._persist() is True
    saved = json.loads(history.read_text())["jobs"]

    assert [row["job_id"] for row in saved] == ["active-old", "done-5", "done-4"]
    assert saved[0]["params"]["client_request_id"] == "must-survive"


def test_history_writes_serialize_the_fixed_temporary_path(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", tmp_path / ".history.json")
    manager = generation.GenerationManager()
    manager._jobs = {
        "queued": generation.GenerationJob("queued", "txt2speech", {"repo": "local/voice"}),
    }
    entered = threading.Event()
    allow_replace = threading.Event()
    second_finished = threading.Event()
    results: list[bool] = []
    failures: list[BaseException] = []
    original_replace = generation.os.replace
    replace_count = 0

    def replace(source, destination):
        nonlocal replace_count
        replace_count += 1
        if replace_count == 1:
            entered.set()
            assert allow_replace.wait(1)
        return original_replace(source, destination)

    monkeypatch.setattr(generation.os, "replace", replace)
    def persist_into(results_event: threading.Event | None = None) -> None:
        try:
            results.append(manager._persist())
        except BaseException as exc:
            failures.append(exc)
        finally:
            if results_event is not None:
                results_event.set()

    first = threading.Thread(target=persist_into)
    second = threading.Thread(target=lambda: persist_into(second_finished))
    first.start()
    assert entered.wait(1)
    second.start()
    assert not second_finished.wait(0.05)
    allow_replace.set()
    first.join(1)
    second.join(1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert second_finished.is_set()
    assert failures == []
    assert results == [True, True]
    assert json.loads((tmp_path / ".history.json").read_text())["jobs"][0]["job_id"] == "queued"
