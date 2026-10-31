"""The web API: replay a day under a scenario and return everything the screens draw.

A scenario is a policy, a roster mode, optional acceptance-rule overrides, staff marked sick, service
duration overrides and how many hubs Logistics Valeo waits at. Everything is carried in the query string, so the API holds no state and every
response is reproducible. All data is the synthetic month; responses say so (`synthetic: true`).
Replays and rosters are cached per scenario because a day takes a moment to plan.
"""
from __future__ import annotations

import threading
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
from valeo_routing.engine import capacity as capacities
from valeo_routing.engine import metrics as metric
from valeo_routing.engine import roster as rosters
from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.data import World, engine_labs, load_world, make_context
from valeo_routing.engine.hubs import Siting, curve, history_window
from valeo_routing.engine.model import Block, Job, Pair, PairDay
from valeo_routing.engine.policy import ExcelEra, LogisticsValeoV1, LogisticsValeoV2
from valeo_routing.engine.replay import DayKpis, DayResult, replay_day
from valeo_routing.engine.standby import HubStandby
from valeo_routing.engine.swap import CancelModel
from valeo_routing.engine.validator import Rules, validate
from valeo_routing.settings import (
    ApiSettings, EngineSettings, Settings, load_api_settings, load_engine_settings, load_settings,
)

POLICIES = {"excel": ("Excel era", ExcelEra), "lv1": ("Logistics Valeo v1", LogisticsValeoV1),
            "lv2": ("v2 (not shipped)", LogisticsValeoV2)}
TOOLS = ("lv1", "lv2")  # the policies that wait at hubs
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
    hubs: int  # hubs Logistics Valeo waits at (the Excel era always waits at the office)


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
        "moved": k.moved, "bumped": k.bumped,
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
        self.hub_dates, self.hub_history = history_window(self.world.orders, engine.hub_history_days)
        self.sitings: List[Siting] = curve([(o.lat, o.lon) for o in self.hub_history], self.world.ref.areas,
                                           self.ctx.office, engine.hub_max_count, self.ctx.dist)
        self._results: Dict[Tuple, Tuple[DayResult, int, rosters.Roster]] = {}
        self._rosters: Dict[Tuple, rosters.Roster] = {}
        self._capacity: Dict[Tuple, List[capacities.DayNeed]] = {}
        self._capacity_lock = threading.Lock()
        self._metrics: Dict[Tuple, Dict[str, List[metric.DayMetrics]]] = {}
        self._metrics_lock = threading.Lock()
        self.cancels = CancelModel(self.world.orders, self.base_services, engine.cancel_bands_h, engine.v2_cancel_prior_weight)

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

    def hub_standby(self, k: int) -> HubStandby:
        return HubStandby(self.ctx.office, [(h.name, h.loc) for h in self.sitings[k].hubs], self.ctx.dist)

    def policy(self, policy_id: str, engine: EngineSettings, hubs: int):
        if policy_id == "lv1":
            return LogisticsValeoV1(engine, self.ctx.office, self.hub_standby(hubs))
        if policy_id == "lv2":
            return LogisticsValeoV2(engine, self.ctx.office, self.cancels, self.hub_standby(hubs))
        return ExcelEra(engine, self.ctx.office)

    def replay(self, day: date, sc: Scenario, roster_mode: Optional[str] = None,
               policy: Optional[str] = None, hubs: Optional[int] = None) -> Tuple[DayResult, int, rosters.Roster]:
        mode, policy_id = roster_mode or sc.roster, policy or sc.policy
        k = sc.hubs if hubs is None else hubs
        key = (day, policy_id, mode, sc.overrides, sc.unavailable, sc.services, k if policy_id in TOOLS else 0)
        if key not in self._results:
            engine = self.settings_with(sc.overrides)
            roster = self.roster(day, sc, mode)
            result = replay_day(day, roster.pairs, self.world.orders_on(day), self.services_with(sc.services),
                                Catalog(engine.plan_duration_position), self.ctx,
                                self.policy(policy_id, engine, k), engine.replay_seed)
            self._results[key] = (result, len(validate(result.plan, result.jobs, self.rules)), roster)
        return self._results[key]

    def capacity(self, sc: Scenario) -> List[capacities.DayNeed]:
        """Pairs needed on every day of the month; slow (a few plans per day), so cached and warmed at start."""
        key = (sc.services, sc.hubs)
        with self._capacity_lock:
            if key not in self._capacity:
                services = self.services_with(sc.services)
                catalog = Catalog(self.engine.plan_duration_position)
                ctx = replace(self.ctx, standby=self.hub_standby(sc.hubs))
                default = Scenario("lv1", "auto", (), (), sc.services, sc.hubs)
                self._capacity[key] = [
                    capacities.day_need(d, self.world.orders_on(d), self.world.orders, self.world.staff, services,
                                        catalog, ctx, self.engine, len(self.roster(d, default, "auto").pairs))
                    for d in self.dates
                ]
            return self._capacity[key]

    def tool_policy(self, sc: Scenario) -> str:
        """The policy measured against the Excel era: the scenario's, or v1 when the Excel era is selected."""
        return sc.policy if sc.policy in TOOLS else "lv1"

    def metrics(self, sc: Scenario) -> Dict[str, List[metric.DayMetrics]]:
        """The tracker's record of every day, under the Excel era and the tool; a month of replays, so cached."""
        tool = self.tool_policy(sc)
        key = (tool, sc.roster, sc.overrides, sc.services, sc.hubs)
        with self._metrics_lock:
            if key not in self._metrics:
                out: Dict[str, List[metric.DayMetrics]] = {}
                for policy_id in ("excel", tool):
                    days = []
                    for d in self.dates:
                        result = self.replay(d, replace(sc, unavailable=()), policy=policy_id)[0]
                        days.append(metric.track_day(d, result.plan, result.kpis.visits, self.engine))
                    out[policy_id] = days
                self._metrics[key] = out
            return self._metrics[key]

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


def _hub_json(h) -> dict:
    return {"id": h.hub_id, "area_id": h.area_id, "name": h.name, "emirate": h.emirate,
            "lat": h.loc[0], "lon": h.loc[1], "orders": h.orders}


def create_app(settings: Settings, engine_settings: EngineSettings, api: ApiSettings, warm: bool = True) -> FastAPI:
    engine = Engine(settings, engine_settings)
    if warm:  # the month's capacity takes a while; start it now so the Capacity tab is ready when opened
        default = Scenario("lv1", "auto", (), (), (), engine_settings.hub_count)
        threading.Thread(target=engine.capacity, args=(default,), daemon=True).start()
        threading.Thread(target=engine.metrics, args=(default,), daemon=True).start()
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
        hubs: Optional[int] = Query(None, ge=0),
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
        k = engine.engine.hub_count if hubs is None else hubs
        if k > engine.engine.hub_max_count:
            raise HTTPException(422, detail=[{"field": "hubs", "message": "hubs must be 0 to {}".format(engine.engine.hub_max_count)}])
        return Scenario(policy, roster, overrides, ids, parse_service_edits(services, engine.base_services), k)

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
                "hub_count": e.hub_count, "hub_max_count": e.hub_max_count, "hub_history_days": e.hub_history_days,
                "capacity_serve_share": e.capacity_serve_share, "capacity_max_pairs": e.capacity_max_pairs,
                "capacity_levels": e.capacity_percentiles,
                "v2_search_window_min": e.v2_search_window_min, "v2_min_notice_h": e.v2_min_notice_h,
            },
            "map": {"tile_url": e.map_tile_url.replace("{key}", e.map_api_key), "attribution": e.map_attribution},
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
            "hubs": [_hub_json(h) for h in engine.sitings[sc.hubs].hubs] if sc.policy in TOOLS else [],
            "pairs": [engine.pair_json(d) for d in result.plan.pairs.values()],
            "jobs": {i: engine.job_json(j, rows[i]) for i, j in result.jobs.items()},
            "log": [
                {"order_id": r.order_id, "published": r.published_min, "decided": r.decided_min, "slot": r.slot_min,
                 "mode": r.mode, "outcome": r.outcome, "reason": r.reason, "pair_id": r.pair_id, "final": r.final,
                 "room": r.room}
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

    @app.get("/api/hubs")
    def hubs_view(date: str, sc: Scenario = Depends(scenario)) -> dict:
        service_day = parse_day(date)
        sitings = []
        for s in engine.sitings:
            k = engine.replay(service_day, sc, policy="lv1", hubs=s.k)[0].kpis
            sitings.append({"k": s.k, "km_to_spot": round(s.km_per_order, 2), "office_orders": s.office_orders,
                            "hubs": [_hub_json(h) for h in s.hubs], "day": _kpis(k)})
        return {
            "synthetic": True, "date": service_day.isoformat(), "applied": sc.hubs, "default": engine.engine.hub_count,
            "window": {"from": engine.hub_dates[0].isoformat(), "to": engine.hub_dates[-1].isoformat(),
                       "days": len(engine.hub_dates), "orders": len(engine.hub_history)},
            "orders": [[round(o.lat, 5), round(o.lon, 5)] for o in engine.hub_history],
            "office": {"lat": engine.world.ref.office.lat, "lon": engine.world.ref.office.lon, "name": engine.world.ref.office.name},
            "excel_day": _kpis(engine.replay(service_day, sc, policy="excel")[0].kpis),
            "sitings": sitings,
        }

    @app.get("/api/capacity")
    def capacity_view(sc: Scenario = Depends(scenario)) -> dict:
        needs = engine.capacity(sc)
        e = engine.engine
        levels = [{"p": p, "pairs": capacities.percentile([n.needed for n in needs], p)} for p in e.capacity_percentiles]
        return {
            "synthetic": True, "serve_share": e.capacity_serve_share, "max_pairs": e.capacity_max_pairs,
            "hubs": sc.hubs, "levels": levels,
            "rostered": {"min": min(n.rostered for n in needs), "max": max(n.rostered for n in needs)},
            "days": [
                {"date": n.day.isoformat(), "weekday": n.day.strftime("%a"), "orders": n.orders, "floor": n.floor,
                 "unservable": n.unservable, "needed": n.needed, "served": n.served, "rostered": n.rostered}
                for n in needs
            ],
        }

    @app.get("/api/metrics")
    def metrics_view(date: str, sc: Scenario = Depends(scenario)) -> dict:
        service_day = parse_day(date)
        tool = engine.tool_policy(sc)
        record = engine.metrics(sc)
        e = engine.engine
        tool_days, base_days = record[tool], record["excel"]
        clean = [i for i, d in enumerate(tool_days) if not d.excluded and not base_days[i].excluded]
        kept = metric.Totals.of([tool_days[i] for i in clean])
        saving = metric.Saving.measure([base_days[i] for i in clean], [tool_days[i] for i in clean], e)
        km_ratio = kept.actual_km / kept.predicted_km if kept.predicted_km else 1.0
        error = metric.error_share([p for i in clean for p in tool_days[i].pairs])

        def totals(t: metric.Totals) -> dict:
            return {"days": t.days, "visits": t.visits, "km": round(t.actual_km, 1),
                    "km_per_visit": round(t.km_per_visit, 2), "mean_of_daily": round(t.mean_of_daily, 2)}

        def excluded(i: int) -> str:
            return tool_days[i].excluded or base_days[i].excluded

        today = tool_days[engine.dates.index(service_day)]
        return {
            "synthetic": True, "date": service_day.isoformat(), "tool": tool, "tool_label": POLICIES[tool][0],
            "rules": {"min_coverage": e.metrics_min_coverage, "max_pair_ratio": e.metrics_max_pair_ratio},
            "rates": {"marginal": e.cost_per_km_marginal, "all_in": e.cost_per_km_all_in, "currency": e.cost_currency},
            "road_factor": e.road_factor,
            "summary": {
                "clean_days": len(clean), "days": len(engine.dates), "km_ratio": round(km_ratio, 4),
                "time_ratio": round(kept.actual_drive_min / kept.predicted_drive_min, 4) if kept.predicted_drive_min else 1.0,
                "median_error": round(error, 4) if error is not None else None,
                "suggested_road_factor": round(e.road_factor * km_ratio, 2),
            },
            "days": [
                {"date": d.day.isoformat(), "weekday": d.day.strftime("%a"), "visits": d.visits,
                 "predicted_km": round(d.predicted_km, 1), "actual_km": round(d.actual_km, 1),
                 "predicted_min": d.predicted_drive_min, "actual_min": round(d.actual_drive_min),
                 "excluded": excluded(i)}
                for i, d in enumerate(tool_days)
            ],
            "pairs": [
                {"id": p.pair_id, "visits": p.visits, "predicted_km": round(p.predicted_km, 1),
                 "actual_km": round(p.actual_km, 1), "predicted_min": p.predicted_drive_min,
                 "actual_min": round(p.actual_drive_min), "coverage": round(p.coverage, 3), "fault": p.fault}
                for p in today.pairs
            ],
            "day_excluded": excluded(engine.dates.index(service_day)),
            "saving": {"baseline": totals(saving.baseline), "tool": totals(saving.tool),
                       "km_saved": round(saving.km_saved), "marginal": round(saving.marginal),
                       "all_in": round(saving.all_in)},
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
