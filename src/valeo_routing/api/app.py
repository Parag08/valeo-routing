"""The web API: replay a day under a scenario and return everything the screens draw.

A scenario is a policy, a roster mode, optional acceptance-rule overrides, staff marked sick and service
duration overrides. Everything is carried in the query string, so the API holds no state and every
response is reproducible. All data is the synthetic month; responses say so (`synthetic: true`).
Replays and rosters are cached per scenario because a day takes a moment to plan.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from valeo_routing.datagen.reference import Service
from valeo_routing.engine import roster as rosters
from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.data import World, engine_labs, load_world, make_context
from valeo_routing.engine.model import Block, Job, Pair, PairDay
from valeo_routing.engine.policy import ExcelEra, LogisticsValeoV1
from valeo_routing.engine.replay import DayKpis, DayResult, replay_day
from valeo_routing.engine.validator import Rules, validate
from valeo_routing.settings import (
    ApiSettings, EngineSettings, Settings, load_api_settings, load_engine_settings, load_settings,
)

POLICIES = {"excel": ("Excel era", ExcelEra), "lv1": ("Logistics Valeo v1", LogisticsValeoV1)}
ROSTERS = {"auto": "Auto-allocated", "simple": "Simple pairing"}
WINDOW = (5 * 60, 23 * 60)  # what the day view draws
MAX_DURATION_MIN, MAX_SAMPLE_LIMIT_MIN = 480, 1440


@dataclass(frozen=True)
class Scenario:
    """Everything that can change a day's plan, hashable so replays can be cached."""

    policy: str
    roster: str
    overrides: Tuple[Tuple[str, object], ...]  # acceptance-rule overrides, sorted by name
    unavailable: Tuple[str, ...]  # staff marked sick for the day, sorted
    services: Tuple[Tuple[str, int, int, Optional[int]], ...]  # id, minutes lo, hi, sample limit; sorted


def _block(b: Block) -> dict:
    return {
        "kind": b.kind, "start": b.start, "end": b.end, "km": round(b.km, 2), "loc": list(b.loc),
        "job_id": b.job_id, "lab_id": b.lab_id, "job_ids": list(b.job_ids), "note": b.note,
    }


def _kpis(k: DayKpis) -> dict:
    return {
        "offered": k.offered, "capturable": k.capturable, "accepted": k.accepted, "lost": k.lost,
        "declined": k.declined, "cancelled_before_decision": k.cancelled_before_decision,
        "honored_cancellations": k.honored_cancellations, "late_cancellations": k.late_cancellations,
        "visits": k.visits, "capture_rate": round(k.capture_rate, 4), "km": round(k.km, 1),
        "km_per_visit": round(k.km_per_visit, 2), "visit_h": round(k.visit_h, 1),
        "drive_h": round(k.drive_h, 1), "idle_h": round(k.idle_h, 1),
    }


class Engine:
    """Loaded data plus the cached plans; the app's only state."""

    def __init__(self, settings: Settings, engine: EngineSettings):
        self.settings, self.engine = settings, engine
        self.world: World = load_world(settings.data_reference_dir, settings.demand_profile_path, settings.data_output_dir)
        self.ctx = make_context(engine, self.world.ref)
        self.base_services = {s.service_id: s for s in self.world.ref.services}
        self.areas = {a.area_id: a for a in self.world.ref.areas}
        self.staff = {s.staff_id: s for s in self.world.staff}
        self.rules = Rules(self.ctx.dist, self.ctx.office, engine_labs(self.world.ref),
                           self.ctx.tolerance_min, self.ctx.access_min, self.ctx.kit_stop_min)
        self.dates = sorted({o.service_date for o in self.world.orders})
        self._results: Dict[Tuple, Tuple[DayResult, int, rosters.Roster]] = {}
        self._rosters: Dict[Tuple, rosters.Roster] = {}

    # -- scenario pieces ---------------------------------------------------------------------

    def settings_with(self, overrides: Tuple[Tuple[str, object], ...]) -> EngineSettings:
        try:
            return EngineSettings(**{**self.engine.model_dump(), **dict(overrides)})
        except ValidationError as error:
            raise HTTPException(422, detail=[
                {"field": e["loc"][0], "message": e["msg"].replace("Value error, ", "")} for e in error.errors()
            ])

    def services_with(self, edits: Tuple[Tuple[str, int, int, Optional[int]], ...]) -> Dict[str, Service]:
        services = dict(self.base_services)
        for sid, lo, hi, limit in edits:
            changes = {"duration_min_lo": lo, "duration_min_hi": hi}
            if limit is not None:
                changes["sample_max_min"] = limit
            services[sid] = replace(services[sid], **changes)
        return services

    def roster(self, day: date, sc: Scenario, mode: Optional[str] = None) -> rosters.Roster:
        mode = mode or sc.roster
        key = (day, mode, sc.unavailable, sc.services)
        if key not in self._rosters:
            services = self.services_with(sc.services)
            catalog = Catalog(self.engine.plan_duration_position)
            demand = rosters.expected_demand(self.world.orders, services, catalog, day, self.engine)
            build = rosters.allocate if mode == "auto" else rosters.simple
            self._rosters[key] = build(day, self.world.staff, self.world.availability, demand, self.engine, sc.unavailable)
        return self._rosters[key]

    def replay(self, day: date, sc: Scenario, roster_mode: Optional[str] = None,
               policy: Optional[str] = None) -> Tuple[DayResult, int, rosters.Roster]:
        mode, policy_id = roster_mode or sc.roster, policy or sc.policy
        key = (day, policy_id, mode, sc.overrides, sc.unavailable, sc.services)
        if key not in self._results:
            engine = self.settings_with(sc.overrides)
            roster = self.roster(day, sc, mode)
            result = replay_day(day, roster.pairs, self.world.orders_on(day), self.services_with(sc.services),
                                Catalog(engine.plan_duration_position), self.ctx,
                                POLICIES[policy_id][1](engine, self.ctx.office), engine.replay_seed)
            self._results[key] = (result, len(validate(result.plan, result.jobs, self.rules)), roster)
        return self._results[key]

    # -- JSON ---------------------------------------------------------------------------------

    def pair_json(self, d: PairDay) -> dict:
        p = d.pair
        return {
            **self.pair_summary(p), "km": round(d.km, 1), "visits": len(d.job_ids),
            "blocks": [_block(b) for b in d.blocks],
        }

    def pair_summary(self, p: Pair) -> dict:
        return {
            "id": p.pair_id, "nurse_id": p.nurse_id, "nurse": self.staff[p.nurse_id].name,
            "driver_id": p.driver_id, "driver": self.staff[p.driver_id].name, "car_id": p.car_id,
            "iv_certified": p.iv_certified, "shift_start": p.shift_start_min, "shift_end": p.shift_end_min,
        }

    def job_json(self, job: Job, row) -> dict:
        service = self.base_services[row.service_id]
        return {
            "service": service.name, "category": service.category, "lat": row.lat, "lon": row.lon,
            "area": self.areas[row.area_id].area_name, "emirate": self.areas[row.area_id].emirate,
            "slot": job.slot_min, "published": job.published_min, "lab_id": job.lab_id,
            "needs_kits": job.needs_kits, "duration": job.duration_min, "patient": row.patient_ref,
        }


def parse_service_edits(text: Optional[str], services: Dict[str, Service]) -> Tuple[Tuple[str, int, int, Optional[int]], ...]:
    """'SV-08:50-70,SV-02:12-18:360' -> (id, minutes lo, hi, sample limit) tuples, sorted by id."""
    edits: Dict[str, Tuple[str, int, int, Optional[int]]] = {}
    for token in (t.strip() for t in (text or "").split(",") if t.strip()):
        parts = token.split(":")
        try:
            sid, span = parts[0], parts[1].split("-")
            lo, hi = int(span[0]), int(span[1])
            limit = int(parts[2]) if len(parts) > 2 else None
            if len(parts) > 3 or len(span) != 2:
                raise ValueError
        except (ValueError, IndexError):
            raise HTTPException(422, detail=[{"field": "services", "message": "expected ID:lo-hi or ID:lo-hi:limit, got {!r}".format(token)}])
        service = services.get(sid)
        problems = []
        if service is None:
            problems.append("unknown service {}".format(sid))
        else:
            if not 1 <= lo <= hi <= MAX_DURATION_MIN:
                problems.append("{}: minutes must satisfy 1 <= lo <= hi <= {}".format(sid, MAX_DURATION_MIN))
            if limit is not None and not service.needs_lab:
                problems.append("{} has no lab, so no sample time limit".format(sid))
            if limit is not None and not 15 <= limit <= MAX_SAMPLE_LIMIT_MIN:
                problems.append("{}: sample limit must be 15 to {} minutes".format(sid, MAX_SAMPLE_LIMIT_MIN))
        if problems:
            raise HTTPException(422, detail=[{"field": "services", "message": m} for m in problems])
        edits[sid] = (sid, lo, hi, limit)
    return tuple(edits[k] for k in sorted(edits))


def create_app(settings: Settings, engine_settings: EngineSettings, api: ApiSettings) -> FastAPI:
    engine = Engine(settings, engine_settings)
    app = FastAPI(title="Logistics Valeo rebuild", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=[api.dev_cors_origin], allow_methods=["GET"], allow_headers=["*"])

    def parse_day(value: str) -> date:
        try:
            day = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(422, detail="date must be YYYY-MM-DD")
        if day not in engine.dates:
            raise HTTPException(404, detail="no generated orders for {}".format(value))
        return day

    def scenario(
        policy: str = "lv1", roster: str = "auto",
        auto_accept_lead_h: Optional[float] = Query(None, ge=0, le=72),
        office_hours: Optional[str] = None, quiet_hours: Optional[str] = None,
        unavailable: Optional[str] = None, services: Optional[str] = None,
    ) -> Scenario:
        if policy not in POLICIES:
            raise HTTPException(422, detail="policy must be one of {}".format(sorted(POLICIES)))
        if roster not in ROSTERS:
            raise HTTPException(422, detail="roster must be one of {}".format(sorted(ROSTERS)))
        given = {"auto_accept_lead_h": auto_accept_lead_h, "office_hours": office_hours, "quiet_hours": quiet_hours}
        overrides = tuple(sorted((k, v) for k, v in given.items() if v is not None))
        engine.settings_with(overrides)  # fail fast on a bad value
        ids = tuple(sorted({t.strip() for t in (unavailable or "").split(",") if t.strip()}))
        unknown = [i for i in ids if i not in engine.staff]
        if unknown:
            raise HTTPException(422, detail=[{"field": "unavailable", "message": "unknown staff id {}".format(i)} for i in unknown])
        return Scenario(policy, roster, overrides, ids, parse_service_edits(services, engine.base_services))

    @app.get("/api/meta")
    def meta() -> dict:
        counts: Dict[date, int] = {}
        for o in engine.world.orders:
            counts[o.service_date] = counts.get(o.service_date, 0) + 1
        e = engine.engine
        return {
            "synthetic": True,
            "dates": [{"date": d.isoformat(), "weekday": d.strftime("%a"), "orders": counts[d]} for d in engine.dates],
            "policies": [{"id": k, "label": v[0]} for k, v in POLICIES.items()],
            "rosters": [{"id": k, "label": v} for k, v in ROSTERS.items()],
            "window": {"start": WINDOW[0], "end": WINDOW[1]},
            "settings": {
                "auto_accept_lead_h": e.auto_accept_lead_h, "office_hours": e.office_hours,
                "quiet_hours": e.quiet_hours, "arrival_tolerance_min": e.arrival_tolerance_min,
                "excel_response_min": [e.excel_response_min_lo, e.excel_response_min_hi],
                "manual_response_min": [e.manual_response_min_lo, e.manual_response_min_hi],
                "plan_duration_position": e.plan_duration_position, "shift_hours": e.shift_hours,
                "roster_target_utilisation": e.roster_target_utilisation,
                "roster_travel_allowance_min": e.roster_travel_allowance_min,
                "roster_starts": [e.roster_starts[0], e.roster_starts[-1]],
            },
            "office": {"lat": engine.world.ref.office.lat, "lon": engine.world.ref.office.lon,
                       "name": engine.world.ref.office.name},
            "labs": [{"id": l.lab_id, "name": l.name, "lat": l.lat, "lon": l.lon} for l in engine.world.ref.labs],
        }

    @app.get("/api/day")
    def day_view(date: str, sc: Scenario = Depends(scenario)) -> dict:
        service_day = parse_day(date)
        result, violations, roster = engine.replay(service_day, sc)
        rows = {o.order_id: o for o in engine.world.orders_on(service_day)}
        return {
            "synthetic": True, "date": service_day.isoformat(), "weekday": service_day.strftime("%a"),
            "policy": sc.policy, "policy_label": POLICIES[sc.policy][0], "roster": sc.roster,
            "roster_label": ROSTERS[sc.roster], "window": {"start": WINDOW[0], "end": WINDOW[1]},
            "unavailable": list(sc.unavailable), "services_edited": [e[0] for e in sc.services],
            "pairs": [engine.pair_json(d) for d in result.plan.pairs.values()],
            "jobs": {i: engine.job_json(j, rows[i]) for i, j in result.jobs.items()},
            "log": [
                {"order_id": r.order_id, "published": r.published_min, "decided": r.decided_min, "slot": r.slot_min,
                 "mode": r.mode, "outcome": r.outcome, "reason": r.reason, "pair_id": r.pair_id, "final": r.final}
                for r in result.log
            ],
            "kpis": _kpis(result.kpis), "violations": violations,
        }

    @app.get("/api/compare")
    def compare(date: str, sc: Scenario = Depends(scenario)) -> dict:
        service_day = parse_day(date)
        return {"synthetic": True, "date": service_day.isoformat(),
                "kpis": {pid: _kpis(engine.replay(service_day, sc, policy=pid)[0].kpis) for pid in POLICIES}}

    @app.get("/api/roster")
    def roster_view(date: str, sc: Scenario = Depends(scenario)) -> dict:
        service_day = parse_day(date)
        chosen = engine.roster(service_day, sc)
        status = {a.staff_id: a.status for a in engine.world.availability if a.date == service_day}
        placed = {}
        for p in chosen.pairs:
            placed[p.nurse_id] = placed[p.driver_id] = p
        people = []
        for person in sorted(engine.world.staff, key=lambda x: (x.role != "nurse", x.staff_id)):
            marked = person.staff_id in sc.unavailable and status[person.staff_id] == "available"
            pair = placed.get(person.staff_id)
            people.append({
                "id": person.staff_id, "name": person.name, "role": person.role, "iv_certified": person.iv_certified,
                "status": "marked_sick" if marked else status[person.staff_id],
                "pair_id": pair.pair_id if pair else None,
                "shift_start": pair.shift_start_min if pair else None, "shift_end": pair.shift_end_min if pair else None,
            })
        curves = {m: engine.roster(service_day, sc, m) for m in ROSTERS}
        d = chosen.demand
        return {
            "synthetic": True, "date": service_day.isoformat(), "weekday": service_day.strftime("%a"),
            "roster": sc.roster, "policy": sc.policy, "unavailable": list(sc.unavailable),
            "staff": people, "pairs": [engine.pair_summary(p) for p in chosen.pairs], "reserve": chosen.reserve,
            "curve": {
                "hours": list(d.hours), "expected_orders": [round(x, 2) for x in d.orders],
                "required_pairs": [round(x, 2) for x in d.required_pairs],
                "on_duty": {m: [round(x, 2) for x in r.on_duty] for m, r in curves.items()},
                "shortfall": {m: round(r.shortfall, 2) for m, r in curves.items()},
            },
            "compare": {m: _kpis(engine.replay(service_day, sc, roster_mode=m)[0].kpis) for m in ROSTERS},
        }

    @app.get("/api/services")
    def services_view(sc: Scenario = Depends(scenario)) -> dict:
        edited = {e[0]: e for e in sc.services}
        catalog = Catalog(engine.engine.plan_duration_position)
        current = engine.services_with(sc.services)
        rows = []
        for sid, base in sorted(engine.base_services.items()):
            now = current[sid]
            rows.append({
                "id": sid, "name": base.name, "category": base.category,
                "duration_lo": now.duration_min_lo, "duration_hi": now.duration_min_hi,
                "default_lo": base.duration_min_lo, "default_hi": base.duration_min_hi,
                "planned_min": catalog.planned_minutes(now), "needs_lab": base.needs_lab,
                "sample_max_min": now.sample_max_min, "default_sample_max_min": base.sample_max_min,
                "keep_cold": base.keep_cold, "needs_office_supplies": base.needs_office_supplies,
                "iv_certified_only": base.iv_certified_only, "mix_weight": base.mix_weight, "edited": sid in edited,
            })
        total = sum(r["mix_weight"] for r in rows)
        for r in rows:
            r["mix_share"] = round(r["mix_weight"] / total, 4)
        return {"synthetic": True, "plan_duration_position": engine.engine.plan_duration_position,
                "limits": {"max_duration_min": MAX_DURATION_MIN, "max_sample_limit_min": MAX_SAMPLE_LIMIT_MIN},
                "services": rows}

    web = api.web_dist_dir
    if web.is_dir():
        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")
    else:
        @app.get("/")
        def root() -> JSONResponse:
            return JSONResponse({"message": "API only: build the UI with `npm run build` in web/ or use the Vite dev server.",
                                 "docs": "/api/docs"})
    return app


def main() -> None:
    settings, engine_settings, api = load_settings(), load_engine_settings(), load_api_settings()
    uvicorn.run(create_app(settings, engine_settings, api), host=api.api_host, port=api.api_port)


if __name__ == "__main__":
    main()
