import re

from fastapi.testclient import TestClient

from backend import main


def test_health_attests_to_the_loaded_app_commit():
    client = TestClient(main.app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{40}", response.json()["app_commit"])


def test_auto_update_status_advertises_exact_managed_commit_capability():
    client = TestClient(main.app, headers={"X-Studio-Token": main.FLEET_TOKEN})

    response = client.get("/api/auto-update/status")

    assert response.status_code == 200
    assert response.json()["capabilities"]["managed_exact_commit"] is True


def test_managed_update_route_requires_auth_and_threads_full_tuple(monkeypatch):
    request = {
        "after_current": True,
        "target_commit": "a" * 40,
        "target_version": "2.0.0",
        "operation_id": "hub-op-1",
    }
    public = TestClient(main.app)
    assert public.post("/api/auto-update/update", json=request).status_code == 401

    calls = []
    monkeypatch.setattr(
        main.auto_updater,
        "trigger_update",
        lambda **kwargs: calls.append(kwargs) or {"state": "deferred"},
    )
    client = TestClient(main.app, headers={"X-Studio-Token": main.FLEET_TOKEN})

    response = client.post("/api/auto-update/update", json=request)

    assert response.status_code == 200
    assert calls == [request]
