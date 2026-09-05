"""One clean-spawned, exclusively leased native execution process.

The parent owns job state and artifacts.  This helper owns only the process
identity needed to stop an uncooperative native call without signalling the
server or another job.
"""

from __future__ import annotations

import multiprocessing
import os
import queue
import signal
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class NativeRunOutcome:
    state: str
    run_id: str
    generation: int
    value: Any = None
    error: str | None = None
    terminated: bool = False


def _worker_main(commands, results, cancel_requested, generation: int, native_call) -> None:
    # On POSIX the executor owns a separate process group, so a forced stop
    # cannot signal the server's group. FFmpeg remains parent-owned.
    if os.name == "posix":
        os.setsid()
    while True:
        command = commands.get()
        if command is None:
            return
        run_id = command["run_id"]
        try:
            value = native_call(command["payload"], cancel_requested)
            results.put({"run_id": run_id, "generation": generation, "value": value})
        except BaseException as exc:
            results.put({"run_id": run_id, "generation": generation,
                         "error": f"{type(exc).__name__}: {exc}"})


class ExclusiveNativeExecutor:
    """Reuse one spawned process until cancellation requires destroying it."""

    def __init__(self, native_call: Callable[[dict, Any], Any], *,
                 cooperative_grace: float = 5.0, terminate_timeout: float = 2.0,
                 kill_timeout: float = 2.0) -> None:
        self._native_call = native_call
        self._grace = cooperative_grace
        self._terminate_timeout = terminate_timeout
        self._kill_timeout = kill_timeout
        self._ctx = multiprocessing.get_context("spawn")
        self._process = None
        self._commands = None
        self._results = None
        self._cancel_requested = None
        self._generation = 0
        self._active: tuple[str, int] | None = None
        # A child we cannot prove stopped must never receive another command
        # or be replaced by a second concurrent model process.
        self._blocked_reason: str | None = None

    def _start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._generation += 1
        self._commands = self._ctx.Queue()
        self._results = self._ctx.Queue()
        self._cancel_requested = self._ctx.Event()
        self._process = self._ctx.Process(
            target=_worker_main,
            args=(self._commands, self._results, self._cancel_requested,
                  self._generation, self._native_call),
            name=f"voice-native-{self._generation}",
            daemon=True,
        )
        previous_child_marker = os.environ.get("VOICE_NATIVE_EXECUTOR_CHILD")
        os.environ["VOICE_NATIVE_EXECUTOR_CHILD"] = "1"
        try:
            self._process.start()
        finally:
            if previous_child_marker is None:
                os.environ.pop("VOICE_NATIVE_EXECUTOR_CHILD", None)
            else:
                os.environ["VOICE_NATIVE_EXECUTOR_CHILD"] = previous_child_marker

    def _discard(self) -> bool:
        process = self._process
        if process is None:
            return True
        if not process.is_alive():
            # A leader that died before we could signal its group does not
            # prove that a native helper exited with it. Reap descriptors, but
            # make the caller preserve the uncertainty fence.
            process.close()
            self._process = None
            self._commands = None
            self._results = None
            self._cancel_requested = None
            return False
        if process.is_alive():
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    # Spawn may report the child alive before it has called
                    # setsid(). Its direct process handle is still exact.
                    process.terminate()
            else:
                process.terminate()
            process.join(self._terminate_timeout)
        if process.is_alive():
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    process.kill()
            else:
                process.kill()
            process.join(self._kill_timeout)
        dead = not process.is_alive()
        if dead:
            process.close()
            self._process = None
            self._commands = None
            self._results = None
            self._cancel_requested = None
        return dead

    def run(self, payload: dict, cancel_event, *, on_started=None,
            timeout: float | None = None) -> NativeRunOutcome:
        if self._active is not None:
            raise RuntimeError("native executor already leased")
        if self._blocked_reason is not None:
            return NativeRunOutcome("uncertain", "", self._generation,
                                    error=self._blocked_reason)
        self._start()
        assert self._commands is not None and self._results is not None
        assert self._cancel_requested is not None
        self._cancel_requested.clear()
        run_id = uuid.uuid4().hex
        generation = self._generation
        self._active = (run_id, generation)
        cancel_at = None
        timeout_at = time.monotonic() + timeout if timeout is not None else None
        try:
            if on_started is not None:
                on_started(run_id, generation)
            self._commands.put({"run_id": run_id, "payload": payload})
            while True:
                if cancel_event.is_set() and cancel_at is None:
                    cancel_at = time.monotonic()
                    self._cancel_requested.set()
                try:
                    result = self._results.get(timeout=0.02)
                except queue.Empty:
                    result = None
                if result and result.get("run_id") == run_id and result.get("generation") == generation:
                    if cancel_at is not None:
                        # The parent must discard this command's output, but
                        # cache inventory is safe to retain for idle release.
                        return NativeRunOutcome("cancelled", run_id, generation,
                                                value=result.get("value"))
                    if "error" in result:
                        return NativeRunOutcome("error", run_id, generation,
                                                error=result["error"])
                    return NativeRunOutcome("done", run_id, generation, value=result.get("value"))
                if cancel_at is not None and time.monotonic() - cancel_at >= self._grace:
                    # `_active` is the exact identity checked before touching a process.
                    if self._active != (run_id, generation):
                        return NativeRunOutcome("uncertain", run_id, generation,
                                                error="native execution identity changed")
                    verified = self._discard()
                    if not verified:
                        self._blocked_reason = "native executor exit was not verified"
                    return NativeRunOutcome(
                        "cancelled" if verified else "uncertain", run_id, generation,
                        error=None if verified else "native executor exit was not verified",
                        terminated=verified,
                    )
                if timeout_at is not None and time.monotonic() >= timeout_at:
                    verified = self._discard()
                    if not verified:
                        self._blocked_reason = "native executor exit was not verified"
                    return NativeRunOutcome(
                        "cancelled" if verified else "uncertain", run_id, generation,
                        error=None if verified else "native executor release exit was not verified",
                        terminated=verified,
                    )
                if self._process is None or not self._process.is_alive():
                    # A dead executor leader cannot prove that an inherited
                    # native helper also stopped. Preserve the generation fence
                    # and refuse every later command rather than spawning a
                    # second model process beside unknown work.
                    self._blocked_reason = "native executor exited without a matched result"
                    return NativeRunOutcome("uncertain", run_id, generation,
                                            error=self._blocked_reason)
        finally:
            self._active = None

    def release(self, payload: dict, *, acknowledgement_timeout: float = 2.0) -> NativeRunOutcome:
        """Bounded idle-cache eviction; reclaim only this idle executor on timeout."""
        if self._active is not None:
            raise RuntimeError("native executor is active")
        outcome = self.run(payload, threading.Event(), timeout=acknowledgement_timeout)
        if outcome.state == "cancelled" and outcome.terminated:
            return NativeRunOutcome("done", outcome.run_id, outcome.generation,
                                    value={"released": True}, terminated=True)
        if outcome.state == "error":
            verified = self._discard()
            if verified:
                return NativeRunOutcome("done", outcome.run_id, outcome.generation,
                                        value={"released": True}, terminated=True)
            self._blocked_reason = "native executor exit was not verified"
            return NativeRunOutcome("uncertain", outcome.run_id, outcome.generation,
                                    error=self._blocked_reason)
        return outcome

    def close(self) -> None:
        self._discard()
