"""
Download manager.

Wraps huggingface_hub.snapshot_download in a background thread per job.
Progress is recovered by polling the on-disk cache (bytes downloaded /
total expected bytes), since snapshot_download's internal tqdm is awkward
to capture without monkey-patching globally.

Total expected bytes are fetched once via the HF API (HfApi.repo_info)
before the download starts. Resume is automatic in huggingface_hub 0.27+
(the previous opt-in `resume_download=True` was removed in 1.0). Partial
files are kept as <hash>.incomplete and continued from the byte offset
on retry. Cancelling a job leaves the .incomplete files in place; the
next start_download for the same repo picks up where it left off.

NB: huggingface_hub will sometimes discard a partial and restart from
byte 0 if it can't verify the partial matches the current remote etag.
This is server-driven and outside our control.
"""
from __future__ import annotations

import fnmatch
import multiprocessing as mp
import os
import queue
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Optional

# Hugging Face's Xet transport can wedge mid-transfer while holding the repo
# file lock: bytes stop growing on disk and ``snapshot_download`` never
# returns, so the stall watchdog below can only cancel and restart it.  Because
# each attempt writes its own ``<blob>.<suffix>.incomplete``, a cancelled
# attempt's bytes are not picked up by the next one, so progress fragments
# across temp files and a large repo can loop without ever completing --
# observed on mlx-community/fish-audio-s2-pro-8bit, which accumulated six
# partials of one blob (4351/629/201/201/52/31 MB) and never finished.  With
# the classic HTTP transport the same repo completed in one pass.
#
# This must run before huggingface_hub is imported, because its constants
# module reads the flag at import time.  The download child process is spawned
# (not forked), so it re-imports this module and picks the setting up too.
# Set VOICESTUDIO_ENABLE_XET=1 to opt back in.
if os.environ.get("VOICESTUDIO_ENABLE_XET") != "1":
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import HfApi, snapshot_download  # noqa: E402
from huggingface_hub.utils import HfHubHTTPError

from . import cache, catalog, settings


# A normal Hugging Face partial is useful resumable state and must remain on
# disk.  This only detects a transfer that has stopped changing on disk long
# enough for the next Hub reconciliation to recover it safely.
STALE_DOWNLOAD_RESTART_SECONDS = 15 * 60


def _download_worker(payload: dict, result_queue) -> None:
    """Run one HF transfer in an interruptible child process.

    ``snapshot_download`` can block inside an HTTP/Xet transfer while holding
    a Hugging Face file lock.  A cancelled Python thread cannot interrupt that
    call, so starting a replacement in the same process can leave the new job
    waiting forever on the old lock.  Keeping the transfer in a child process
    lets the parent terminate a genuinely stalled attempt; the child still
    uses the same HF_HOME, so every retry resumes the existing ``.incomplete``
    blobs rather than starting a second cache.
    """
    try:
        snapshot_download(
            repo_id=payload["repo"],
            revision=payload.get("revision"),
            token=payload.get("token"),
            ignore_patterns=payload.get("ignore_patterns"),
        )
        for companion in payload.get("companions", ()):
            snapshot_download(
                repo_id=companion["repo"],
                token=payload.get("token"),
                allow_patterns=companion.get("allow_patterns"),
            )
        result_queue.put({"ok": True})
    except BaseException as exc:  # report the error without pickling it
        result_queue.put({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        })


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    """fnmatch with extra love: a pattern of 'foo/*' should match
    'foo/bar.bin' AND 'foo/sub/bar.bin'. fnmatch normally won't match the
    second because '*' doesn't cross '/'. We OR in a recursive variant."""
    for p in patterns:
        if fnmatch.fnmatch(path, p):
            return True
        # 'foo/*' → 'foo/**' style recursive match.
        if p.endswith("/*") and (path == p[:-2] or path.startswith(p[:-1])):
            return True
    return False


@dataclass
class DownloadJob:
    job_id: str
    repo: str
    revision: Optional[str] = None
    token: Optional[str] = None
    state: str = "queued"           # queued | running | paused | done | error | cancelled
    error: Optional[str] = None
    total_bytes: int = 0            # 0 until we resolve it from HF API
    companion_repos: tuple[str, ...] = field(default_factory=tuple)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    # Sliding-window byte-rate, smoothed with an EMA so the UI doesn't
    # oscillate when chunks land in bursts.
    _last_speed_sample: Optional[tuple[float, int]] = field(default=None, repr=False)
    _speed_bps: float = field(default=0.0, repr=False)
    _last_observed_bytes: int = field(default=-1, repr=False)
    _last_progress_at: Optional[float] = field(default=None, repr=False)
    _owned_repos: set[str] = field(default_factory=set, repr=False)

    def tracked_repos(self) -> tuple[str, ...]:
        """Main plus the exact companion repositories this job downloads."""
        return tuple(dict.fromkeys((self.repo, *self.companion_repos)))

    def _progress_revision(self, repo: str) -> Optional[str]:
        """Return the immutable snapshot that may contribute progress bytes."""
        if repo == self.repo and self.revision:
            return self.revision.lower()
        return cache.snapshot_revision(repo)

    def _byte_observation(self) -> tuple[int, int, int, int]:
        """Return verified, partial, progress, and excluded inventory bytes.

        Complete files count only after an immutable snapshot links them to
        the requested revision.  Unversioned standalone files remain reusable
        cache inventory, but cannot make a repair transfer look complete.
        """
        bytes_done = 0
        bytes_partial = 0
        bytes_unverified = 0
        for repo in self.tracked_repos():
            verified = cache.snapshot_disk_bytes(repo, self._progress_revision(repo))
            bytes_done += verified
            bytes_partial += cache.incomplete_bytes(repo)
            bytes_unverified += max(0, cache.disk_bytes(repo) - verified)
        return (
            bytes_done,
            bytes_partial,
            bytes_done + bytes_partial,
            bytes_unverified,
        )

    def observed_bytes(self) -> tuple[int, int, int]:
        """Return verified, resumable-partial, and progress-eligible bytes."""
        bytes_done, bytes_partial, observed, _ = self._byte_observation()
        return bytes_done, bytes_partial, observed

    def unverified_inventory_bytes(self) -> int:
        """Completed cache bytes excluded from this job's progress evidence."""
        return self._byte_observation()[3]

    def observe_progress(self, observed: int, now: Optional[float] = None) -> None:
        """Record byte growth without treating an unchanged partial as progress."""
        if observed > self._last_observed_bytes:
            self._last_observed_bytes = observed
            self._last_progress_at = time.time() if now is None else now

    def serialize(self) -> dict:
        bytes_done, bytes_partial, observed, bytes_unverified = self._byte_observation()

        # Update the rolling speed estimate. Only meaningful while running;
        # cleared when the job reaches a terminal state so the UI doesn't show
        # stale speeds next to a finished job.
        now = time.time()
        if self.state == "running":
            self.observe_progress(observed, now)
            if self._last_speed_sample is None:
                self._last_speed_sample = (now, observed)
            else:
                last_t, last_b = self._last_speed_sample
                dt = now - last_t
                if dt >= 0.5:
                    delta = max(0, observed - last_b)
                    instant = delta / dt
                    # EMA: 30% new + 70% old. Smooths spikes from chunk arrivals
                    # without lagging too far behind real bandwidth changes.
                    self._speed_bps = 0.3 * instant + 0.7 * self._speed_bps
                    self._last_speed_sample = (now, observed)
        else:
            self._speed_bps = 0.0

        percent = None
        if self.state == "done":
            # A successful snapshot_download is terminal proof that every main
            # and companion transfer completed. Disk accounting may lag cache
            # reconciliation, but a terminal job must never display 55%.
            percent = 100.0
        elif self.total_bytes > 0:
            # Reserve 100% for terminal success. A transfer can have every
            # byte on disk while snapshot_download is still reconciling the
            # immutable snapshot and companions.
            percent = min(99.9, observed / self.total_bytes * 100.0)

        # ETA: remaining bytes at current speed. Only show when speed is
        # nonzero and there's a known total.
        #
        # Also require a few seconds of runtime first: right after a download
        # starts, snapshot_download() is often still resolving repo metadata
        # before any real bytes land, so the very first EMA sample can be a
        # near-zero "instant" speed (e.g. 1.57 KB observed over ~3 sec). That
        # single noisy sample, divided into a multi-GB remaining total,
        # produces an absurd ETA (observed: "ETA 99679m 03s" seconds after
        # clicking Download). Waiting until the EMA has had a few real
        # 1-second update cycles lets it settle to a representative speed
        # before we ever surface an ETA.
        eta_seconds = None
        if (
            self.state == "running"
            and self._speed_bps > 0
            and self.total_bytes > 0
            and self.started_at is not None
            and now - self.started_at >= 3.0
            and observed < self.total_bytes
        ):
            remaining = max(0, self.total_bytes - observed)
            eta_seconds = remaining / self._speed_bps

        return {
            "id": self.job_id,
            "repo": self.repo,
            "requested_revision": self.revision,
            "state": self.state,
            "error": self.error,
            "bytes_done": bytes_done,
            "bytes_verified": bytes_done,
            "bytes_partial": bytes_partial,
            "bytes_unverified_inventory": bytes_unverified,
            "bytes_observed": observed,
            "bytes_total": self.total_bytes,
            "percent": percent,
            "speed_bps": self._speed_bps,
            "eta_seconds": eta_seconds,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def is_stalled(self, now: Optional[float] = None) -> bool:
        """True only for a running transfer with no observed byte growth.

        This intentionally needs a long quiet period. Slow transfers stay
        resumable; the recovery is triggered only by a later request (normally
        the Hub's regular reconciliation), never by an aggressive background
        cancellation loop.
        """
        if self.state != "running" or self.started_at is None:
            return False
        check_at = time.time() if now is None else now
        last_progress = self._last_progress_at or self.started_at
        return check_at - last_progress >= STALE_DOWNLOAD_RESTART_SECONDS


class DownloadManager:
    """In-memory registry of download jobs, keyed by repo."""

    def __init__(self, *, use_processes: bool = True) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, DownloadJob] = {}     # job_id -> job
        self._active_by_repo: dict[str, str] = {}   # repo   -> active job_id
        self._workers: dict[str, mp.Process] = {}
        self._use_processes = bool(use_processes)

    # ---------- public API ----------

    def start(
        self,
        repo: str,
        token: Optional[str] = None,
        revision: Optional[str] = None,
    ) -> DownloadJob:
        with self._lock:
            existing = self._active_for_repo_locked(repo)
            if existing is not None:
                existing.observe_progress(existing.observed_bytes()[2])
                if existing.is_stalled():
                    # snapshot_download can occasionally remain blocked on a
                    # dead transport. Mark the old attempt cancelling and let
                    # a fresh job reuse the same HF partial under its lock.
                    # No model bytes are removed.
                    existing.cancel_event.set()
                    existing.state = "cancelling"
                    self._release_job_repos_locked(existing)
                else:
                    return existing
            job = DownloadJob(
                job_id=uuid.uuid4().hex[:12],
                repo=repo,
                revision=revision or None,
                token=token or None,
            )
            self._jobs[job.job_id] = job
            self._active_by_repo[repo] = job.job_id
            job._owned_repos.add(repo)

        job.thread = threading.Thread(
            target=self._run, args=(job,), name=f"dl-{repo}", daemon=True
        )
        job.thread.start()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.state in ("done", "error", "cancelled"):
            return False
        job.cancel_event.set()
        # The thread will observe the cancel on the next file write; mark
        # the state immediately so the UI reflects user intent.
        if job.state == "running":
            job.state = "cancelling"
        return True

    def get(self, job_id: str) -> Optional[DownloadJob]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[DownloadJob]:
        return list(self._jobs.values())

    def clear_finished(self) -> int:
        """Drop all terminal-state jobs from memory. Returns count removed."""
        with self._lock:
            terminal = [jid for jid, j in self._jobs.items()
                        if j.state in ("done", "error", "cancelled")]
            for jid in terminal:
                job = self._jobs.pop(jid, None)
                if job is not None:
                    self._release_job_repos_locked(job)
            # Also prune any active_by_repo pointers that referenced removed jobs
            for repo, jid in list(self._active_by_repo.items()):
                if jid not in self._jobs:
                    self._active_by_repo.pop(repo, None)
        return len(terminal)

    def active_for_repo(self, repo: str) -> Optional[DownloadJob]:
        with self._lock:
            job = self._active_for_repo_locked(repo)
            if job is not None:
                job.observe_progress(job.observed_bytes()[2])
            if job is not None and job.is_stalled():
                # Let the caller start a replacement immediately. The old
                # transfer retains its partial files and observes cancellation
                # when its blocked transport returns.
                job.cancel_event.set()
                job.state = "cancelling"
                self._release_job_repos_locked(job)
                return None
            return job

    def _release_job_repos_locked(self, job: DownloadJob) -> None:
        """Release every mapping owned by this job without touching cache data."""
        # Include map entries as well as the job's normal ownership record so
        # recovery remains safe for jobs restored/constructed by an older
        # process that predates companion ownership bookkeeping.
        mapped_repos = {
            repo for repo, job_id in self._active_by_repo.items() if job_id == job.job_id
        }
        for repo in tuple(job._owned_repos | mapped_repos):
            if self._active_by_repo.get(repo) == job.job_id:
                self._active_by_repo.pop(repo, None)
        job._owned_repos.clear()

    def _claim_companion_repos_locked(self, job: DownloadJob) -> None:
        """Claim idle companion repos so only their successful owner may prune.

        A companion already being downloaded by another active job remains
        untouched. Hugging Face's own lock coordinates the shared transfer,
        while neither job is permitted to delete its resumable partials.
        """
        for repo in job.companion_repos:
            active_id = self._active_by_repo.get(repo)
            if active_id in (None, job.job_id):
                self._active_by_repo[repo] = job.job_id
                job._owned_repos.add(repo)

    def _prune_completed_stale_incomplete(self, job: DownloadJob) -> None:
        """Remove stale partials only after this exact transfer succeeded.

        `snapshot_download` returning success is the proof here, avoiding an
        unsafe manifest-byte guess for a repo that has just completed. Manual
        cleanup remains conservative. Every main/companion repo is checked
        against the current owner mapping so an active replacement can never
        lose its partial state.
        """
        removed_files = 0
        removed_bytes = 0
        with self._lock:
            for repo in job.tracked_repos():
                if self._active_by_repo.get(repo) != job.job_id:
                    continue
                removed = cache.prune_stale_incomplete(
                    repo, complete_snapshot_verified=True
                )
                removed_files += removed["removed_files"]
                removed_bytes += removed["removed_bytes"]
        if removed_files:
            print(
                f"[downloads] pruned {removed_files} stale partial file(s) "
                f"({removed_bytes} bytes) after verified completion of {job.repo}",
                flush=True,
            )

    def prune_stale_incomplete(self, repo: str) -> dict[str, int | bool]:
        """Prune stale partials while excluding concurrent download starts."""
        expected_bytes = self._resolve_total_bytes(repo, None)
        with self._lock:
            if self._active_for_repo_locked(repo) is not None:
                raise RuntimeError("a model download is active")
            complete_bytes = cache.disk_bytes(repo)
            immutable_revision = cache.snapshot_revision(repo)
            complete_snapshot_verified = bool(
                expected_bytes > 0
                and complete_bytes == expected_bytes
                and cache.has_any_snapshot(repo)
                and immutable_revision
                and cache.has_weight_files(repo, revision=immutable_revision)
            )
            removed = cache.prune_stale_incomplete(
                repo,
                complete_snapshot_verified=complete_snapshot_verified,
            )
        return {
            **removed,
            "expected_bytes": expected_bytes,
            "complete_bytes": complete_bytes,
            "complete_snapshot_verified": complete_snapshot_verified,
        }

    # ---------- internals ----------

    def _active_for_repo_locked(self, repo: str) -> Optional[DownloadJob]:
        job_id = self._active_by_repo.get(repo)
        if job_id is None:
            return None
        job = self._jobs.get(job_id)
        # Also treat "cancelling" as no-longer-active so a user can immediately
        # kick off a fresh attempt even if the old thread is wedged on a dead
        # socket. hf_hub's internal `.locks/` directory keeps concurrent writes
        # on the same blob safe.
        if job is None or job.state in ("done", "error", "cancelled", "cancelling"):
            if job is None:
                self._active_by_repo.pop(repo, None)
            else:
                self._release_job_repos_locked(job)
            return None
        return job

    def _resolve_total_bytes(
        self, repo: str, token: Optional[str], revision: Optional[str] = None
    ) -> int:
        effective = token or settings.get_hf_token()
        try:
            info = HfApi().repo_info(
                repo_id=repo,
                revision=revision,
                files_metadata=True,
                token=effective,
            )
        except HfHubHTTPError:
            return 0
        except Exception:
            return 0
        ignore = catalog.ignore_patterns_for(repo)
        total = 0
        for sibling in info.siblings or []:
            name = getattr(sibling, "rfilename", "") or ""
            if ignore and _matches_any(name, ignore):
                # Don't count files we won't download — otherwise progress
                # percentage would top out below 100%.
                continue
            size = getattr(sibling, "size", None) or 0
            try:
                total += int(size)
            except (TypeError, ValueError):
                continue
        return total

    def _companion_bytes(self, repo: str, allow_patterns, token: Optional[str]) -> int:
        """Bytes for a companion download. When allow_patterns is set, count
        ONLY the matched files (kyutai/moshiko is a ~15 GB repo we take 1 file
        from)."""
        effective = token or settings.get_hf_token()
        try:
            info = HfApi().repo_info(repo_id=repo, files_metadata=True, token=effective)
        except Exception:
            return 0
        total = 0
        for sibling in info.siblings or []:
            name = getattr(sibling, "rfilename", "") or ""
            if allow_patterns and not _matches_any(name, allow_patterns):
                continue
            size = getattr(sibling, "size", None) or 0
            try:
                total += int(size)
            except (TypeError, ValueError):
                continue
        return total

    def _run(self, job: DownloadJob) -> None:
        job.state = "running"
        job.started_at = time.time()
        # Capture the resumable starting point. Future health/catalog polls
        # compare against it, so a transfer that is actually writing bytes is
        # never mistaken for a silent stall at the first 15-minute Hub check.
        job.observe_progress(job.observed_bytes()[2])
        # Total = main repo + every companion (codec/tokenizer) the engine pulls
        # at generation time. Counting companions here keeps the progress bar
        # honest AND makes the download complete-on-first-run (no surprise
        # second download when the user hits Generate).
        companions = catalog.companions_for(job.repo)
        job.companion_repos = tuple(
            dict.fromkeys(str(companion["repo"]) for companion in companions)
        )
        with self._lock:
            self._claim_companion_repos_locked(job)
        total = self._resolve_total_bytes(job.repo, job.token, job.revision)
        for c in companions:
            total += self._companion_bytes(c["repo"], c.get("allow_patterns"), job.token)
        job.total_bytes = total
        cache.ensure_hub_dir()
        print(
            f"[downloads] starting {job.repo}  "
            f"(job={job.job_id}, total={job.total_bytes / 1e9:.2f} GB"
            f"{', +' + str(len(companions)) + ' companion(s)' if companions else ''})",
            flush=True,
        )

        try:
            effective_token = job.token or settings.get_hf_token()
            # Per-model ignore patterns trim out redundant weight formats
            # (e.g. pytorch_model.bin when model.safetensors already exists,
            # or audiocraft state_dict.bin alongside transformers weights).
            ignore = catalog.ignore_patterns_for(job.repo)
            completed = self._run_download_process(
                job,
                effective_token=effective_token,
                ignore_patterns=list(ignore) if ignore else None,
                companions=companions,
            )
            if not completed:
                job.state = "cancelled"
                print(f"[downloads] cancelled {job.repo}", flush=True)
                return
            if job.cancel_event.is_set():
                job.state = "cancelled"
                print(f"[downloads] cancelled {job.repo}", flush=True)
            else:
                self._prune_completed_stale_incomplete(job)
                job.state = "done"
                print(f"[downloads] done {job.repo}", flush=True)
        except Exception as e:
            if job.cancel_event.is_set():
                job.state = "cancelled"
                print(f"[downloads] cancelled (during exception) {job.repo}", flush=True)
            else:
                job.state = "error"
                job.error = f"{type(e).__name__}: {e}"
                print(f"[downloads] error {job.repo}: {job.error}", file=sys.stderr, flush=True)
                traceback.print_exc()
        finally:
            job.finished_at = time.time()
            with self._lock:
                self._release_job_repos_locked(job)

    def _run_download_process(
        self,
        job: DownloadJob,
        *,
        effective_token: Optional[str],
        ignore_patterns: Optional[list[str]],
        companions,
    ) -> bool:
        """Run the transfer and terminate it promptly when cancelled.

        Tests can opt into the old in-process runner so they can monkeypatch
        ``snapshot_download`` without spawning a second interpreter. Production
        downloads use a child process to make stale-transfer recovery real.
        """
        payload = {
            "repo": job.repo,
            "revision": job.revision,
            "token": effective_token,
            "ignore_patterns": ignore_patterns,
            "companions": [
                {
                    "repo": c["repo"],
                    "allow_patterns": list(c.get("allow_patterns") or []) or None,
                }
                for c in companions
            ],
        }
        if not self._use_processes:
            snapshot_download(
                repo_id=payload["repo"],
                revision=payload.get("revision"),
                token=payload.get("token"),
                ignore_patterns=payload.get("ignore_patterns"),
            )
            for companion in payload["companions"]:
                snapshot_download(
                    repo_id=companion["repo"],
                    token=payload.get("token"),
                    allow_patterns=companion.get("allow_patterns"),
                )
            return True

        context = mp.get_context("spawn")
        result_queue = context.Queue()
        worker = context.Process(
            target=_download_worker,
            args=(payload, result_queue),
            name=f"hf-download-{job.job_id}",
        )
        with self._lock:
            self._workers[job.job_id] = worker
        worker.start()
        try:
            while worker.is_alive():
                if job.cancel_event.wait(0.5):
                    worker.terminate()
                    worker.join(timeout=5)
                    if worker.is_alive():
                        worker.kill()
                        worker.join(timeout=5)
                    return False
            worker.join(timeout=1)
            try:
                # multiprocessing.Queue uses a feeder thread; allow it a
                # moment to flush the child's terminal result after exit.
                result = result_queue.get(timeout=2)
            except queue.Empty as exc:
                raise RuntimeError(
                    f"download worker exited with code {worker.exitcode}"
                ) from exc
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "download failed"))
            return True
        finally:
            with self._lock:
                self._workers.pop(job.job_id, None)
            result_queue.close()


manager = DownloadManager()
