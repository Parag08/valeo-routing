"""The web API: replay a day under a policy and return everything the screens draw.

Everything the API returns comes from the synthetic month; the response says so (`synthetic: true`).
Replays are cached per (date, policy, overrides) because a day takes a moment to plan.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.data import World, engine_labs, load_world, make_context
from valeo_routing.engine.model import Block, Job, PairDay
from valeo_routing.engine.pairs import build_pairs
from valeo_routing.engine.policy import ExcelEra, LogisticsValeoV1
from valeo_routing.engine.replay import DayKpis, DayResult, replay_day
from valeo_routing.engine.validator import Rules, validate
from valeo_routing.settings import (
    ApiSettings, EngineSettings, Settings, load_api_settings, load_engine_settings, load_settings,
)

POLICIES = {"excel": ("Excel era", ExcelEra), "lv1": ("Logistics Valeo v1", LogisticsValeoV1)}
OVERRIDABLE = ("auto_accept_lead_h", "office_hours", "quiet_hours")
WINDOW = (5 * 60, 23 * 60)  # what the day view draws


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
    """Loaded data plus the cached replays; the app's only state."""

    def __init__(self, settings: Settings, engine: EngineSettings):
        self.settings, self.engine = settings, engine
        self.world: World = load_world(settings.data_reference_dir, settings.demand_profile_path, settings.data_output_dir)
        self.ctx = make_context(engine, self.world.ref)
        self.services = {s.service_id: s for s in self.world.ref.services}
        self.areas = {a.area_id: a for a in self.world.ref.areas}
        self.names = {s.staff_id: s.name for s in self.world.staff}
        self.rules = Rules(self.ctx.dist, self.ctx.office, engine_labs(self.world.ref),
                           self.ctx.tolerance_min, self.ctx.access_min, self.ctx.kit_stop_min)
        self.dates = sorted({o.service_date for o in self.world.orders})
        self._cache: Dict[Tuple, Tuple[DayResult, int]] = {}

    def settings_with(self, overrides: Dict[str, object]) -> EngineSettings:
        try:
            return EngineSettings(**{**self.engine.model_dump(), **overrides})
        except ValidationError as error:
            raise HTTPException(422, detail=[{"field": e["loc"][0], "message": e["msg"].replace("Value error, ", "")} for e in error.errors()])

    def replay(self, day: date, policy_id: str, overrides: Dict[str, object]) -> Tuple[DayResult, int]:
        key = (day, policy_id, tuple(sorted(overrides.items())))
        if key not in self._cache:
            engine = self.settings_with(overrides)
            policy = POLICIES[policy_id][1](engine, self.ctx.office)
            pairs = build_pairs(day, self.world.staff, self.world.availability,
                                engine.shift_start_minutes, engine.shift_hours)
            result = replay_day(day, pairs, self.world.orders_on(day), self.services,
                                Catalog(engine.plan_duration_position), self.ctx, policy, engine.replay_seed)
            self._cache[key] = (result, len(validate(result.plan, result.jobs, self.rules)))
        return self._cache[key]

    def pair_json(self, d: PairDay) -> dict:
        p = d.pair
        return {
            "id": p.pair_id, "nurse_id": p.nurse_id, "nurse": self.names.get(p.nurse_id, p.nurse_id),
            "driver_id": p.driver_id, "driver": self.names.get(p.driver_id, p.driver_id), "car_id": p.car_id,
            "iv_certified": p.iv_certified, "shift_start": p.shift_start_min, "shift_end": p.shift_end_min,
            "km": round(d.km, 1), "visits": len(d.job_ids), "blocks": [_block(b) for b in d.blocks],
        }

    def job_json(self, job: Job, row) -> dict:
        service = self.services[row.service_id]
        return {
            "service": service.name, "category": service.category, "lat": row.lat, "lon": row.lon,
            "area": self.areas[row.area_id].area_name, "emirate": self.areas[row.area_id].emirate,
            "slot": job.slot_min, "published": job.published_min, "lab_id": job.lab_id,
            "needs_kits": job.needs_kits, "duration": job.duration_min, "patient": row.patient_ref,
        }


def _overrides(auto_accept_lead_h: Optional[float], office_hours: Optional[str], quiet_hours: Optional[str]) -> Dict[str, object]:
    given = {"auto_accept_lead_h": auto_accept_lead_h, "office_hours": office_hours, "quiet_hours": quiet_hours}
    return {k: v for k, v in given.items() if v is not None}


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

    def parse_policy(value: str) -> str:
        if value not in POLICIES:
            raise HTTPException(422, detail="policy must be one of {}".format(sorted(POLICIES)))
        return value

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
            "window": {"start": WINDOW[0], "end": WINDOW[1]},
            "settings": {
                "auto_accept_lead_h": e.auto_accept_lead_h, "office_hours": e.office_hours,
                "quiet_hours": e.quiet_hours, "arrival_tolerance_min": e.arrival_tolerance_min,
                "excel_response_min": [e.excel_response_min_lo, e.excel_response_min_hi],
                "manual_response_min": [e.manual_response_min_lo, e.manual_response_min_hi],
            },
            "office": {"lat": engine.world.ref.office.lat, "lon": engine.world.ref.office.lon,
                       "name": engine.world.ref.office.name},
            "labs": [{"id": l.lab_id, "name": l.name, "lat": l.lat, "lon": l.lon} for l in engine.world.ref.labs],
        }

    @app.get("/api/day")
    def day_view(
        date: str, policy: str = "lv1", auto_accept_lead_h: Optional[float] = Query(None, ge=0, le=72),
        office_hours: Optional[str] = None, quiet_hours: Optional[str] = None,
    ) -> dict:
        service_day, policy_id = parse_day(date), parse_policy(policy)
        result, violations = engine.replay(service_day, policy_id, _overrides(auto_accept_lead_h, office_hours, quiet_hours))
        rows = {o.order_id: o for o in engine.world.orders_on(service_day)}
        return {
            "synthetic": True, "date": service_day.isoformat(), "weekday": service_day.strftime("%a"),
            "policy": policy_id, "policy_label": POLICIES[policy_id][0], "window": {"start": WINDOW[0], "end": WINDOW[1]},
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
    def compare(date: str, auto_accept_lead_h: Optional[float] = Query(None, ge=0, le=72),
                office_hours: Optional[str] = None, quiet_hours: Optional[str] = None) -> dict:
        service_day = parse_day(date)
        over = _overrides(auto_accept_lead_h, office_hours, quiet_hours)
        return {"synthetic": True, "date": service_day.isoformat(),
                "kpis": {pid: _kpis(engine.replay(service_day, pid, over)[0].kpis) for pid in POLICIES}}

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
