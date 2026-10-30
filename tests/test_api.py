"""The web API: what the screens draw, the policy switch, overrides, errors and the built UI."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from valeo_routing.api.app import create_app
from valeo_routing.settings import ApiSettings, EngineSettings

from .conftest import ROOT

DAY = "2026-11-04"


def api_settings(tmp_path, dist=None) -> ApiSettings:
    return ApiSettings(_env_file=str(ROOT / ".env.example"), web_dist_dir=dist or tmp_path / "no-dist")


@pytest.fixture(scope="module")
def client(settings, written, tmp_path_factory):
    engine = EngineSettings(_env_file=str(ROOT / ".env.example"))
    return TestClient(create_app(settings, engine, api_settings(tmp_path_factory.mktemp("api"))))


def day(client, **params):
    response = client.get("/api/day", params={"date": DAY, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_meta(client):
    meta = client.get("/api/meta").json()
    assert meta["synthetic"] is True
    assert len(meta["dates"]) == 35 and meta["dates"][0] == {"date": "2026-11-02", "weekday": "Mon", "orders": meta["dates"][0]["orders"]}
    assert [p["id"] for p in meta["policies"]] == ["excel", "lv1"]
    assert meta["settings"]["auto_accept_lead_h"] == 12 and meta["settings"]["quiet_hours"] == "22:00-06:00"
    assert len(meta["labs"]) == 3 and meta["office"]["name"].startswith("Ops office")


def test_day_has_everything_the_screens_draw(client):
    d = day(client)
    assert d["synthetic"] is True and d["policy"] == "lv1" and d["policy_label"] == "Logistics Valeo v1"
    assert d["weekday"] == "Wed" and d["window"] == {"start": 300, "end": 1380}
    assert len(d["pairs"]) == 9 and d["violations"] == 0
    for pair in d["pairs"]:
        blocks = pair["blocks"]
        assert all(a["end"] <= b["start"] or a["end"] == b["start"] for a, b in zip(blocks, blocks[1:]))
        visits = [b for b in blocks if b["kind"] == "visit"]
        assert len(visits) == pair["visits"] and pair["shift_end"] - pair["shift_start"] == 720
        assert pair["nurse"] and pair["driver"] and pair["nurse"] != pair["nurse_id"]
    assert set(d["jobs"]) == {r["order_id"] for r in d["log"]}
    job = next(iter(d["jobs"].values()))
    assert {"service", "category", "lat", "lon", "area", "emirate", "slot", "published", "lab_id", "needs_kits", "duration"} <= set(job)


def test_the_log_and_kpis_agree(client):
    d = day(client)
    k, log = d["kpis"], d["log"]
    assert k["offered"] == len(log) == k["accepted"] + k["lost"] + k["declined"] + k["cancelled_before_decision"]
    assert k["capture_rate"] == pytest.approx(k["accepted"] / k["capturable"], abs=1e-3)
    planned = {b["job_id"] for p in d["pairs"] for b in p["blocks"] if b["kind"] == "visit"}
    assert planned == {r["order_id"] for r in log if r["outcome"] == "accepted" and r["final"] in ("served", "late_cancellation")}
    assert k["visits"] == len(planned)
    assert all(r["reason"] for r in log) and {r["mode"] for r in log} <= {"auto", "manual", "excel"}


def test_the_policy_switch_changes_the_outcome(client):
    lv1, excel = day(client, policy="lv1"), day(client, policy="excel")
    assert excel["policy_label"] == "Excel era" and {r["mode"] for r in excel["log"]} == {"excel"}
    assert lv1["kpis"]["capture_rate"] > excel["kpis"]["capture_rate"]
    assert lv1["violations"] == excel["violations"] == 0


def test_compare_matches_the_day_views(client):
    both = client.get("/api/compare", params={"date": DAY}).json()
    assert both["synthetic"] is True
    for policy in ("excel", "lv1"):
        assert both["kpis"][policy] == day(client, policy=policy)["kpis"]


def test_overrides_change_the_acceptance_rule(client):
    default = day(client)
    strict = day(client, auto_accept_lead_h=72)  # nothing is long enough to auto-accept
    assert any(r["mode"] == "auto" for r in default["log"])
    assert not any(r["mode"] == "auto" for r in strict["log"])
    assert strict["kpis"]["capture_rate"] < default["kpis"]["capture_rate"]
    assert day(client, auto_accept_lead_h=12) == default  # same as the default, from the cache or not


@pytest.mark.parametrize("params, status", [
    ({"date": "04-11-2026"}, 422), ({"date": "2030-01-01"}, 404), ({"date": DAY, "policy": "nope"}, 422),
    ({"date": DAY, "auto_accept_lead_h": -1}, 422), ({"date": DAY, "quiet_hours": "bad"}, 422),
    ({"date": DAY, "office_hours": "20:00-08:00"}, 422),
])
def test_bad_requests_are_refused(client, params, status):
    assert client.get("/api/day", params=params).status_code == status


def test_a_bad_override_names_the_field(client):
    detail = client.get("/api/day", params={"date": DAY, "quiet_hours": "bad"}).json()["detail"]
    assert detail[0]["field"] == "quiet_hours"


def test_the_api_only_reads(client):
    assert client.post("/api/day", params={"date": DAY}).status_code == 405


def test_root_without_a_built_ui_explains(client):
    assert "API only" in client.get("/").json()["message"]


def test_root_serves_the_built_ui(settings, written, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Logistics Valeo</title>", encoding="utf-8")
    app = create_app(settings, EngineSettings(_env_file=str(ROOT / ".env.example")), api_settings(tmp_path, dist))
    response = TestClient(app).get("/")
    assert response.status_code == 200 and "Logistics Valeo" in response.text
    assert TestClient(app).get("/api/meta").status_code == 200  # the API still wins over the static mount


def test_api_settings_fail_fast(tmp_path, monkeypatch):
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    for key in (l.split("=", 1)[0] for l in lines if "=" in l and not l.startswith("#")):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("\n".join(l for l in lines if not l.startswith("API_PORT=")), encoding="utf-8")
    with pytest.raises(ValidationError, match="PORT"):
        ApiSettings(_env_file=str(env))
