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
