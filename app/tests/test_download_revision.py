from backend import downloads


def test_pinned_download_passes_exact_revision_to_hugging_face(monkeypatch) -> None:
    revision = "b" * 40
    observed = {}
    manager = downloads.DownloadManager(use_processes=False)
    job = downloads.DownloadJob(
        job_id="pinned-download",
        repo="example/model",
        revision=revision,
    )

    monkeypatch.setattr(manager, "_resolve_total_bytes", lambda *_args: 0)
    monkeypatch.setattr(downloads.catalog, "companions_for", lambda _repo: ())
    monkeypatch.setattr(downloads.cache, "ensure_hub_dir", lambda: None)
    monkeypatch.setattr(downloads.settings, "get_hf_token", lambda: None)
    pruned = []
    monkeypatch.setattr(manager, "_prune_completed_stale_incomplete",
                        lambda actual: pruned.append(actual))

    def snapshot_download(**kwargs):
        observed.update(kwargs)

    monkeypatch.setattr(downloads, "snapshot_download", snapshot_download)

    manager._run(job)

    assert job.state == "done"
    assert observed["repo_id"] == "example/model"
    assert observed["revision"] == revision
    assert job.serialize()["requested_revision"] == revision
    assert pruned == [job]


def test_stalled_download_is_replaced_without_removing_its_partial(monkeypatch) -> None:
    manager = downloads.DownloadManager()
    job = downloads.DownloadJob(job_id="stalled", repo="example/model", state="running")
    job.started_at = 100.0
    job._last_progress_at = 100.0
    job._last_observed_bytes = 0
    manager._jobs[job.job_id] = job
    manager._active_by_repo[job.repo] = job.job_id

    monkeypatch.setattr(downloads.time, "time", lambda: 100.0 + downloads.STALE_DOWNLOAD_RESTART_SECONDS)

    assert manager.active_for_repo(job.repo) is None
    assert job.state == "cancelling"
    assert job.cancel_event.is_set()
    assert job.repo not in manager._active_by_repo


def test_progress_and_terminal_percent_include_companion_repositories(monkeypatch) -> None:
    bytes_by_repo = {
        "example/main": (610, 0),
        "example/companion": (0, 0),
    }
    monkeypatch.setattr(
        downloads.cache,
        "snapshot_disk_bytes",
        lambda repo, _revision: bytes_by_repo[repo][0],
    )
    monkeypatch.setattr(downloads.cache, "disk_bytes", lambda repo: bytes_by_repo[repo][0])
    monkeypatch.setattr(downloads.cache, "snapshot_revision", lambda _repo: "a" * 40)
    monkeypatch.setattr(downloads.cache, "incomplete_bytes", lambda repo: bytes_by_repo[repo][1])
    job = downloads.DownloadJob(
        job_id="combined-progress",
        repo="example/main",
        companion_repos=("example/companion",),
        total_bytes=1_106,
        state="running",
        started_at=100.0,
    )

    initial = job.serialize()
    assert initial["bytes_done"] == 610
    assert initial["bytes_observed"] == 610
    assert initial["percent"] == 610 / 1_106 * 100

    # Main is complete; the companion begins its own real transfer.
    bytes_by_repo["example/companion"] = (0, 300)
    progressed = job.serialize()
    assert progressed["bytes_done"] == 610
    assert progressed["bytes_partial"] == 300
    assert progressed["bytes_observed"] == 910
    assert progressed["percent"] == 910 / 1_106 * 100

    job.state = "done"
    # Terminal success is authoritative even if a cache observer has not yet
    # reconciled every completed blob into its on-disk byte accounting.
    assert job.serialize()["percent"] == 100.0


def test_companion_growth_prevents_a_false_stall(monkeypatch) -> None:
    bytes_by_repo = {
        "example/main": (610, 0),
        "example/companion": (0, 0),
    }
    monkeypatch.setattr(
        downloads.cache,
        "snapshot_disk_bytes",
        lambda repo, _revision: bytes_by_repo[repo][0],
    )
    monkeypatch.setattr(downloads.cache, "disk_bytes", lambda repo: bytes_by_repo[repo][0])
    monkeypatch.setattr(downloads.cache, "snapshot_revision", lambda _repo: "a" * 40)
    monkeypatch.setattr(downloads.cache, "incomplete_bytes", lambda repo: bytes_by_repo[repo][1])
    job = downloads.DownloadJob(
        job_id="companion-growth",
        repo="example/main",
        companion_repos=("example/companion",),
        state="running",
        started_at=100.0,
    )
    job.observe_progress(job.observed_bytes()[2], now=100.0)

    # Just before the old 15-minute stale threshold, the main repo is quiet
    # but the companion has started writing resumable bytes.
    bytes_by_repo["example/companion"] = (0, 1)
    job.observe_progress(job.observed_bytes()[2], now=999.0)

    assert job._last_progress_at == 999.0
    assert not job.is_stalled(now=1_000.0)


def test_unversioned_inventory_is_excluded_from_running_repair_progress(monkeypatch) -> None:
    revision = "c" * 40
    samples = iter((100, 300))
    monkeypatch.setattr(downloads.cache, "snapshot_disk_bytes", lambda *_args: 0)
    monkeypatch.setattr(downloads.cache, "disk_bytes", lambda _repo: 1_970)
    monkeypatch.setattr(downloads.cache, "incomplete_bytes", lambda _repo: next(samples))
    job = downloads.DownloadJob(
        job_id="unversioned-repair",
        repo="example/model",
        revision=revision,
        total_bytes=2_000,
        state="running",
        started_at=100.0,
    )

    first = job.serialize()
    second = job.serialize()

    assert first["bytes_verified"] == 0
    assert first["bytes_unverified_inventory"] == 1_970
    assert first["bytes_observed"] == 100
    assert first["percent"] == 5.0
    assert second["bytes_observed"] == 300
    assert second["percent"] == 15.0


def test_repair_eta_uses_only_verified_and_resumable_bytes(monkeypatch) -> None:
    revision = "c" * 40
    monkeypatch.setattr(downloads.cache, "snapshot_disk_bytes", lambda *_args: 0)
    monkeypatch.setattr(downloads.cache, "disk_bytes", lambda _repo: 1_970)
    monkeypatch.setattr(downloads.cache, "incomplete_bytes", lambda _repo: 300)
    monkeypatch.setattr(downloads.time, "time", lambda: 200.0)
    job = downloads.DownloadJob(
        job_id="repair-eta",
        repo="example/model",
        revision=revision,
        total_bytes=2_000,
        state="running",
        started_at=190.0,
    )
    job._last_speed_sample = (199.0, 200)

    current = job.serialize()

    assert current["speed_bps"] == 30.0
    assert current["eta_seconds"] == (2_000 - 300) / 30.0


def test_running_download_reserves_one_hundred_percent_for_terminal_success(monkeypatch) -> None:
    revision = "d" * 40
    monkeypatch.setattr(downloads.cache, "snapshot_disk_bytes", lambda *_args: 2_000)
    monkeypatch.setattr(downloads.cache, "disk_bytes", lambda _repo: 2_000)
    monkeypatch.setattr(downloads.cache, "incomplete_bytes", lambda _repo: 0)
    job = downloads.DownloadJob(
        job_id="finalizing",
        repo="example/model",
        revision=revision,
        total_bytes=2_000,
        state="running",
        started_at=100.0,
    )

    running = job.serialize()
    assert running["percent"] == 99.9
    assert running["eta_seconds"] is None

    job.state = "done"
    assert job.serialize()["percent"] == 100.0


def test_verified_success_prunes_main_and_companion_stale_partials(monkeypatch) -> None:
    manager = downloads.DownloadManager(use_processes=False)
    job = downloads.DownloadJob(
        job_id="verified-success",
        repo="example/main",
        companion_repos=("example/companion",),
    )
    manager._jobs[job.job_id] = job
    manager._active_by_repo = {
        "example/main": job.job_id,
        "example/companion": job.job_id,
    }
    job._owned_repos = {"example/main", "example/companion"}
    pruned = []
    monkeypatch.setattr(
        downloads.cache,
        "prune_stale_incomplete",
        lambda repo, *, complete_snapshot_verified: (
            pruned.append((repo, complete_snapshot_verified))
            or {"removed_files": 1, "removed_bytes": 12}
        ),
    )

    manager._prune_completed_stale_incomplete(job)

    assert pruned == [
        ("example/main", True),
        ("example/companion", True),
    ]


def test_cancelled_or_failed_attempts_keep_resumable_partials(monkeypatch) -> None:
    def prepare(manager, job):
        manager._jobs[job.job_id] = job
        manager._active_by_repo[job.repo] = job.job_id
        job._owned_repos.add(job.repo)
        monkeypatch.setattr(downloads.catalog, "companions_for", lambda _repo: ())
        monkeypatch.setattr(manager, "_resolve_total_bytes", lambda *_args: 100)
        monkeypatch.setattr(downloads.cache, "ensure_hub_dir", lambda: None)
        monkeypatch.setattr(downloads.cache, "disk_bytes", lambda _repo: 0)
        monkeypatch.setattr(downloads.cache, "incomplete_bytes", lambda _repo: 25)
        pruned = []
        monkeypatch.setattr(manager, "_prune_completed_stale_incomplete", lambda _job: pruned.append(_job))
        return pruned

    cancelled_manager = downloads.DownloadManager(use_processes=False)
    cancelled = downloads.DownloadJob(job_id="cancelled", repo="example/cancelled")
    cancelled_pruned = prepare(cancelled_manager, cancelled)
    monkeypatch.setattr(cancelled_manager, "_run_download_process", lambda *_args, **_kwargs: False)
    cancelled_manager._run(cancelled)
    assert cancelled.state == "cancelled"
    assert cancelled_pruned == []

    failed_manager = downloads.DownloadManager(use_processes=False)
    failed = downloads.DownloadJob(job_id="failed", repo="example/failed")
    failed_pruned = prepare(failed_manager, failed)
    monkeypatch.setattr(
        failed_manager,
        "_run_download_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network lost")),
    )
    failed_manager._run(failed)
    assert failed.state == "error"
    assert failed_pruned == []


def test_active_replacement_blocks_old_job_cleanup(monkeypatch) -> None:
    manager = downloads.DownloadManager()
    old = downloads.DownloadJob(
        job_id="old",
        repo="example/main",
        companion_repos=("example/companion",),
    )
    replacement = downloads.DownloadJob(job_id="replacement", repo="example/main")
    old._owned_repos = {"example/main", "example/companion"}
    manager._jobs = {old.job_id: old, replacement.job_id: replacement}
    manager._active_by_repo = {
        "example/main": replacement.job_id,
        "example/companion": replacement.job_id,
    }
    pruned = []
    monkeypatch.setattr(
        downloads.cache,
        "prune_stale_incomplete",
        lambda *args, **kwargs: pruned.append((args, kwargs)),
    )

    manager._prune_completed_stale_incomplete(old)

    assert pruned == []


def test_manual_cleanup_preserves_partials_for_unversioned_snapshot(monkeypatch) -> None:
    manager = downloads.DownloadManager()
    monkeypatch.setattr(manager, "_resolve_total_bytes", lambda *_args: 100)
    monkeypatch.setattr(downloads.cache, "disk_bytes", lambda _repo: 100)
    monkeypatch.setattr(downloads.cache, "snapshot_revision", lambda _repo: None)
    monkeypatch.setattr(downloads.cache, "has_any_snapshot", lambda _repo: True)
    observed = {}

    def prune(repo, *, complete_snapshot_verified):
        observed.update({
            "repo": repo,
            "complete_snapshot_verified": complete_snapshot_verified,
        })
        return {"removed_files": 0, "removed_bytes": 0}

    monkeypatch.setattr(downloads.cache, "prune_stale_incomplete", prune)

    result = manager.prune_stale_incomplete("example/model")

    assert observed == {
        "repo": "example/model",
        "complete_snapshot_verified": False,
    }
    assert result["complete_snapshot_verified"] is False
