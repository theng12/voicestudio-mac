from backend import downloads


def test_pinned_download_passes_exact_revision_to_hugging_face(monkeypatch) -> None:
    revision = "b" * 40
    observed = {}
    manager = downloads.DownloadManager()
    job = downloads.DownloadJob(
        job_id="pinned-download",
        repo="example/model",
        revision=revision,
    )

    monkeypatch.setattr(manager, "_resolve_total_bytes", lambda *_args: 0)
    monkeypatch.setattr(downloads.catalog, "companions_for", lambda _repo: ())
    monkeypatch.setattr(downloads.cache, "ensure_hub_dir", lambda: None)
    monkeypatch.setattr(downloads.settings, "get_hf_token", lambda: None)

    def snapshot_download(**kwargs):
        observed.update(kwargs)

    monkeypatch.setattr(downloads, "snapshot_download", snapshot_download)

    manager._run(job)

    assert job.state == "done"
    assert observed["repo_id"] == "example/model"
    assert observed["revision"] == revision
    assert job.serialize()["requested_revision"] == revision
