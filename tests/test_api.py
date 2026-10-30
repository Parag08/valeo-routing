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
    return TestClient(create_app(settings, engine, api_settings(tmp_path_factory.mktemp("api")), warm=False))


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
    app = create_app(settings, EngineSettings(_env_file=str(ROOT / ".env.example")), api_settings(tmp_path, dist), warm=False)
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


# --- roster, sick staff and service edits -----------------------------------------------------


def roster(client, **params):
    response = client.get("/api/roster", params={"date": DAY, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_meta_lists_the_rosters(client):
    meta = client.get("/api/meta").json()
    assert [r["id"] for r in meta["rosters"]] == ["auto", "simple"]
    assert meta["settings"]["plan_duration_position"] == 0.5 and meta["settings"]["roster_starts"] == [330, 600]


def test_roster_view(client):
    r = roster(client)
    assert r["synthetic"] is True and r["roster"] == "auto" and len(r["pairs"]) == 9
    people = {p["id"]: p for p in r["staff"]}
    assert len(people) == 26 and {p["role"] for p in people.values()} == {"nurse", "driver"}
    placed = [p for p in r["staff"] if p["pair_id"]]
    assert len(placed) == 18 and all(p["status"] == "available" for p in placed)
    assert {p["id"] for p in r["staff"] if p["status"] == "available" and not p["pair_id"]} == set(r["reserve"])
    assert {p["status"] for p in r["staff"]} <= {"available", "rest", "sick", "leave", "marked_sick"}
    curve = r["curve"]
    n = len(curve["hours"])
    assert n == len(curve["expected_orders"]) == len(curve["required_pairs"]) == len(curve["on_duty"]["auto"]) == len(curve["on_duty"]["simple"])
    assert curve["shortfall"]["auto"] < curve["shortfall"]["simple"]
    assert set(r["compare"]) == {"auto", "simple"} and r["compare"]["auto"]["offered"] == r["compare"]["simple"]["offered"]


def test_auto_and_simple_rosters_differ_in_shift_starts(client):
    auto, simple = roster(client, roster="auto"), roster(client, roster="simple")
    assert sorted({p["shift_start"] for p in simple["pairs"]}) == [330, 480, 600]
    assert {p["shift_start"] for p in auto["pairs"]} != {p["shift_start"] for p in simple["pairs"]}
    assert day(client, roster="simple")["roster"] == "simple" and day(client)["roster"] == "auto"


def test_marking_someone_sick_removes_them_and_replans(client):
    before = roster(client)
    driver = next(p for p in before["staff"] if p["role"] == "driver" and p["pair_id"])
    after = roster(client, unavailable=driver["id"])
    status = {p["id"]: p for p in after["staff"]}
    assert status[driver["id"]]["status"] == "marked_sick" and status[driver["id"]]["pair_id"] is None
    assert len(after["pairs"]) == len(before["pairs"]) - 1 and after["unavailable"] == [driver["id"]]
    planned = day(client, unavailable=driver["id"])
    assert len(planned["pairs"]) == 8 and planned["unavailable"] == [driver["id"]] and planned["violations"] == 0
    assert planned["kpis"] != day(client)["kpis"]


def test_marking_someone_already_off_changes_nothing(client):
    resting = next(p for p in roster(client)["staff"] if p["status"] == "rest")
    assert day(client, unavailable=resting["id"])["pairs"] == day(client)["pairs"]


def test_services_catalog(client):
    r = client.get("/api/services").json()
    rows = {s["id"]: s for s in r["services"]}
    assert r["synthetic"] is True and len(rows) == 12 and not any(s["edited"] for s in rows.values())
    assert sum(s["mix_share"] for s in rows.values()) == pytest.approx(1.0, abs=1e-3)
    assert rows["SV-08"]["planned_min"] == 60 and rows["SV-01"]["needs_lab"] and rows["SV-01"]["sample_max_min"] == 480
    assert rows["SV-11"]["sample_max_min"] is None and rows["SV-07"]["iv_certified_only"]


def test_service_edits_flow_into_the_day(client):
    edited = client.get("/api/services", params={"services": "SV-01:30-40"}).json()["services"]
    row = next(s for s in edited if s["id"] == "SV-01")
    assert (row["duration_lo"], row["duration_hi"], row["planned_min"], row["edited"]) == (30, 40, 35, True)
    assert row["default_lo"] == 10 and next(s for s in edited if s["id"] == "SV-02")["edited"] is False

    base, changed = day(client), day(client, services="SV-01:30-40")
    cbc = [i for i, j in base["jobs"].items() if j["service"].startswith("Blood draw - routine")]
    assert cbc and all(base["jobs"][i]["duration"] == 15 and changed["jobs"][i]["duration"] == 35 for i in cbc)
    lengths = {b["end"] - b["start"] for p in changed["pairs"] for b in p["blocks"] if b["kind"] == "visit" and b["job_id"] in cbc}
    assert lengths == {40}  # 35 minutes of service plus 5 of access
    assert changed["services_edited"] == ["SV-01"] and changed["violations"] == 0
    assert changed["kpis"] != base["kpis"]


def test_a_shorter_sample_limit_makes_labs_unreachable(client):
    base, tight = day(client), day(client, services="SV-03:10-20:15")
    assert sum("lab_unreachable" in r["reason"] for r in tight["log"]) > sum("lab_unreachable" in r["reason"] for r in base["log"])
    assert tight["kpis"]["capture_rate"] <= base["kpis"]["capture_rate"]


@pytest.mark.parametrize("params", [
    {"unavailable": "NOPE-1"}, {"services": "SV-99:1-2"}, {"services": "SV-08:90-40"}, {"services": "SV-08:0-10"},
    {"services": "SV-11:10-20:60"}, {"services": "SV-01:10-20:5"}, {"services": "junk"}, {"services": "SV-08:1-2:3:4"},
    {"roster": "x"},
])
def test_bad_scenarios_are_refused(client, params):
    response = client.get("/api/day", params={"date": DAY, **params})
    assert response.status_code == 422, params
    assert client.get("/api/roster", params={"date": DAY, **params}).status_code == 422


def test_the_same_scenario_gives_the_same_answer(client):
    scenario = {"services": "SV-01:30-40", "unavailable": "NUR-001", "auto_accept_lead_h": 20}
    assert day(client, **scenario) == day(client, **scenario)
    assert roster(client, **scenario) == roster(client, **scenario)


# --- hubs and capacity (PLAN step 6) -------------------------------------------------------------


def test_hubs_view(client):
    meta = client.get("/api/meta").json()
    r = client.get("/api/hubs", params={"date": DAY})
    assert r.status_code == 200, r.text
    data = r.json()
    top = meta["settings"]["hub_max_count"]
    assert data["synthetic"] is True and data["applied"] == data["default"] == meta["settings"]["hub_count"]
    assert [s["k"] for s in data["sitings"]] == list(range(top + 1))
    assert data["window"]["days"] == meta["settings"]["hub_history_days"] and len(data["orders"]) == data["window"]["orders"]
    assert data["sitings"][0]["hubs"] == [] and all(len(s["hubs"]) == s["k"] for s in data["sitings"])
    proxy = [s["km_to_spot"] for s in data["sitings"]]
    assert proxy == sorted(proxy, reverse=True)
    assert data["sitings"][meta["settings"]["hub_count"]]["day"]["km"] < data["sitings"][0]["day"]["km"]
    assert meta["map"]["tile_url"].startswith("https://")


def test_hubs_flow_into_the_day_view(client):
    with_hubs, office_only = day(client, hubs=2), day(client, hubs=0)
    assert with_hubs["violations"] == office_only["violations"] == 0
    assert len(with_hubs["hubs"]) == 2 and office_only["hubs"] == []
    notes = {b["note"] for p in with_hubs["pairs"] for b in p["blocks"] if b["kind"] == "standby"}
    assert any(n.startswith("hub ") for n in notes)
    assert with_hubs["kpis"]["km"] < office_only["kpis"]["km"]
    excel = day(client, policy="excel", hubs=2)
    assert excel["hubs"] == [] and excel["kpis"] == day(client, policy="excel", hubs=0)["kpis"]  # the Excel era waits at the office
    assert client.get("/api/day", params={"date": DAY, "hubs": 9}).status_code == 422


def test_capacity_view(client):
    r = client.get("/api/capacity")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["synthetic"] is True and len(data["days"]) == 35
    pairs = [lvl["pairs"] for lvl in data["levels"]]
    assert pairs == sorted(pairs) and all(1 <= p <= data["max_pairs"] for p in pairs)
    for d in data["days"]:
        assert d["floor"] <= d["needed"] <= data["max_pairs"]
        assert d["served"] + d["unservable"] <= d["orders"]
