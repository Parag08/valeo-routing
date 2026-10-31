"""Settings read from `.env`. Every field is required: a missing key fails fast."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Tuple

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_clock(value: str) -> int:
    """'HH:MM' as minutes after midnight."""
    try:
        hours, minutes = (int(x) for x in value.strip().split(":"))
    except ValueError:
        raise ValueError("expected a time like 08:00, got {!r}".format(value))
    if not (0 <= hours <= 47 and 0 <= minutes <= 59):
        raise ValueError("bad clock time {!r}".format(value))
    return hours * 60 + minutes


def _split_window(part: str) -> Tuple[int, int]:
    try:
        start, end = part.split("-")
    except ValueError:
        raise ValueError("expected hours like 08:00-20:00, got {!r}".format(part))
    return parse_clock(start), parse_clock(end)


def parse_windows(value: str) -> List[Tuple[int, int]]:
    """'07:00-09:30,16:00-19:00' as [(420, 570), (960, 1140)]."""
    windows = []
    for part in value.split(","):
        start, end = _split_window(part)
        if end <= start:
            raise ValueError("window {!r} ends before it starts".format(part))
        windows.append((start, end))
    return windows


def parse_wrapping_window(value: str) -> Tuple[int, int]:
    """'22:00-06:00' as (1320, 360): a window that may run past midnight."""
    start, end = _split_window(value)
    if start == end:
        raise ValueError("window {!r} is empty".format(value))
    return start, end


class Settings(BaseSettings):
    """All runtime parameters. No defaults by design."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_seed: int
    data_start_date: date
    data_days: int
    data_reference_dir: Path
    data_output_dir: Path
    demand_profile_path: Path

    orders_per_day: float
    staff_nurses: int
    staff_drivers: int


def load_settings(**overrides) -> Settings:
    """Load settings from `.env` (and the environment), with optional explicit overrides."""
    return Settings(**overrides)


class EngineSettings(BaseSettings):
    """Planning-engine parameters. Same `.env`, same rule: every field is required."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    road_factor: float  # predicted road km = straight line x this (S14)
    speed_kmh_off_peak: float
    speed_kmh_peak: float
    peak_windows: str  # 'HH:MM-HH:MM,...' when the peak speed applies
    arrival_tolerance_min: int  # arrive within +/- this of the requested slot (S9)
    access_min: int  # parking and reaching the patient's door, before service starts
    office_supply_stop_min: int  # time at the office to collect IV kits
    plan_duration_position: float  # planned on-site time = lo + position * (hi - lo)
    shift_hours: float
    roster_shift_starts: str  # 'HH:MM,...' placeholder roster, cycled over the pairs (until PLAN step 5)
    standby_min_gap_min: int  # idle gaps shorter than this are waited out in place

    # Roster auto-allocation (PLAN step 5).
    roster_target_utilisation: float  # share of an on-duty hour a pair should spend working, in the demand model
    roster_travel_allowance_min: int  # driving time allowed per order when sizing demand in pair-hours
    roster_start_earliest: str  # earliest shift start the roster may choose
    roster_start_latest: str
    roster_start_step_min: int  # shift starts sit on this grid
    roster_lead_min: int  # a pair must be on duty this long before the slot it serves: time to reach the patient
    roster_min_pairs_when_booked: float  # an hour that usually has bookings keeps at least this many pairs on duty
    roster_min_orders_for_cover: float  # "usually has bookings": expected orders per hour at or above this

    # Hub siting (PLAN step 6).
    hub_history_days: int  # hubs are sited on the orders of the last this-many service days in the data
    hub_max_count: int  # the Hubs tab sites 1 to this many hubs
    hub_count: int  # how many hubs Logistics Valeo uses unless the page applies another siting

    # Capacity (PLAN step 6).
    capacity_serve_share: float  # a day counts as covered when the planner serves at least this share of its orders
    capacity_max_pairs: int  # the simulation tries up to this many pairs
    capacity_levels: str  # service levels shown, as percentiles across days: '50,75,90'

    # Logistics Valeo v2: making room for an order that does not fit (PLAN step 7).
    v2_search_window_min: int  # only accepted orders whose slot is this close to the new one are considered
    v2_min_notice_h: float  # an order may be released to the platform only this long before its slot
    v2_visit_value_km: float  # an expected visit is worth this many km when scoring a swap
    v2_swap_min_gain_km: float  # a swap goes ahead only when the fleet gains at least this (km-equivalent)
    v2_cancel_bands_h: str  # lead-time band edges in hours for the cancellation model: '6,24,48'
    v2_cancel_prior_weight: float  # a band's cancellation share is pulled to the overall share by this many orders

    # Metrics (PLAN step 6): the synthetic "actual" km and time, the exclusion rules and the cost rates.
    metrics_seed: int
    metrics_km_bias: float  # recorded road km per predicted km, on average (the road factor's error)
    metrics_km_sigma: float  # spread of that ratio per drive (log-normal sigma)
    metrics_time_bias: float  # recorded driving minutes per predicted minute, on average
    metrics_time_sigma: float
    metrics_gap_day_rate: float  # share of days on which one pair's tracker drops out for part of the shift
    metrics_spike_day_rate: float  # share of days on which one pair's tracker records a GPS jump
    metrics_min_coverage: float  # a day is excluded when any pair's tracker covers less of its shift than this
    metrics_max_pair_ratio: float  # a day is excluded when any pair records more than this x its predicted km
    cost_per_km_marginal: float  # what a km saved is worth: fuel, tolls, parking (assumed, synthetic)
    cost_per_km_all_in: float  # average cost per km with salaries and rental (assumed, synthetic)
    cost_currency: str

    # Map (Hubs tab).
    map_tile_url: str  # raster tile URL template; '{key}' is replaced by MAP_API_KEY
    map_api_key: str  # may be empty for providers that need none
    map_attribution: str

    # Acceptance and replay (PLAN step 3).
    replay_seed: int
    office_hours: str  # 'HH:MM-HH:MM': when ops are at their desks to accept orders
    quiet_hours: str  # 'HH:MM-HH:MM', may wrap midnight: ignored when judging whether ops can react
    auto_accept_lead_h: float  # the tool accepts by itself when the lead time, quiet hours excluded, is at least this
    excel_response_min_lo: int  # Excel era: minutes from ops seeing an order to deciding on it
    excel_response_min_hi: int
    manual_response_min_lo: int  # with the tool: slots are shown upfront, so ops decide faster
    manual_response_min_hi: int

    @field_validator("peak_windows")
    @classmethod
    def _check_windows(cls, value: str) -> str:
        parse_windows(value)
        return value

    @field_validator("roster_target_utilisation")
    @classmethod
    def _check_utilisation(cls, value: float) -> float:
        if not 0.0 < value <= 1.0:
            raise ValueError("roster_target_utilisation must be above 0 and at most 1")
        return value

    @field_validator("hub_history_days", "hub_max_count")
    @classmethod
    def _check_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be at least 1")
        return value

    @field_validator("capacity_serve_share")
    @classmethod
    def _check_share(cls, value: float) -> float:
        if not 0.0 < value <= 1.0:
            raise ValueError("capacity_serve_share must be above 0 and at most 1")
        return value

    @field_validator("capacity_max_pairs")
    @classmethod
    def _check_max_pairs(cls, value: int) -> int:
        if value < 1:
            raise ValueError("capacity_max_pairs must be at least 1")
        return value

    @field_validator("capacity_levels")
    @classmethod
    def _check_levels(cls, value: str) -> str:
        levels = [float(x) for x in value.split(",")]
        if not levels or any(not 0 < x <= 100 for x in levels) or levels != sorted(levels):
            raise ValueError("capacity_levels must be ascending percentiles between 0 and 100, like 50,75,90")
        return value

    @field_validator("v2_search_window_min")
    @classmethod
    def _check_window(cls, value: int) -> int:
        if value < 0:
            raise ValueError("v2_search_window_min must be 0 or more")
        return value

    @field_validator("v2_min_notice_h", "v2_visit_value_km", "v2_swap_min_gain_km", "v2_cancel_prior_weight",
                     "metrics_km_sigma", "metrics_time_sigma", "cost_per_km_marginal", "cost_per_km_all_in")
    @classmethod
    def _check_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("must be 0 or more")
        return value

    @field_validator("v2_cancel_bands_h")
    @classmethod
    def _check_bands(cls, value: str) -> str:
        bands = [float(x) for x in value.split(",")]
        if any(b <= 0 for b in bands) or bands != sorted(set(bands)):
            raise ValueError("v2_cancel_bands_h must be ascending positive hours, like 6,24,48")
        return value

    @property
    def cancel_bands_h(self) -> List[float]:
        return [float(x) for x in self.v2_cancel_bands_h.split(",")]

    @field_validator("metrics_km_bias", "metrics_time_bias", "metrics_max_pair_ratio")
    @classmethod
    def _check_ratio(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be above 0")
        return value

    @field_validator("metrics_gap_day_rate", "metrics_spike_day_rate", "metrics_min_coverage")
    @classmethod
    def _check_rate(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("must be between 0 and 1")
        return value

    @property
    def capacity_percentiles(self) -> List[float]:
        return [float(x) for x in self.capacity_levels.split(",")]

    @field_validator("hub_count")
    @classmethod
    def _check_hub_count(cls, value: int, info) -> int:
        top = info.data.get("hub_max_count")
        if value < 0 or (top is not None and value > top):
            raise ValueError("hub_count must be between 0 and hub_max_count")
        return value

    @field_validator("roster_lead_min")
    @classmethod
    def _check_lead(cls, value: int) -> int:
        if not 0 <= value <= 60:
            raise ValueError("roster_lead_min must be between 0 and 60")
        return value

    @field_validator("roster_start_step_min")
    @classmethod
    def _check_step(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("roster_start_step_min must be positive")
        return value

    @field_validator("roster_start_earliest", "roster_start_latest")
    @classmethod
    def _check_start(cls, value: str) -> str:
        parse_clock(value)
        return value

    @field_validator("office_hours")
    @classmethod
    def _check_office_hours(cls, value: str) -> str:
        parse_windows(value)
        return value

    @field_validator("quiet_hours")
    @classmethod
    def _check_quiet_hours(cls, value: str) -> str:
        parse_wrapping_window(value)
        return value

    @field_validator("roster_shift_starts")
    @classmethod
    def _check_starts(cls, value: str) -> str:
        for part in value.split(","):
            parse_clock(part)
        return value

    @field_validator("plan_duration_position")
    @classmethod
    def _check_position(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("plan_duration_position must be between 0 and 1")
        return value

    @property
    def roster_starts(self) -> List[int]:
        """Every shift start the roster may choose, on the step grid from earliest to latest."""
        first, last = parse_clock(self.roster_start_earliest), parse_clock(self.roster_start_latest)
        if last < first:
            raise ValueError("roster_start_latest is before roster_start_earliest")
        return list(range(first, last + 1, self.roster_start_step_min))

    @property
    def office_window(self) -> Tuple[int, int]:
        return parse_windows(self.office_hours)[0]

    @property
    def quiet_window(self) -> Tuple[int, int]:
        return parse_wrapping_window(self.quiet_hours)

    @property
    def peak_window_minutes(self) -> List[Tuple[int, int]]:
        return parse_windows(self.peak_windows)

    @property
    def shift_start_minutes(self) -> List[int]:
        return [parse_clock(p) for p in self.roster_shift_starts.split(",")]


def load_engine_settings(**overrides) -> EngineSettings:
    return EngineSettings(**overrides)


class ApiSettings(BaseSettings):
    """The web server. Same `.env`, same rule: every field is required."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_host: str
    # PORT is the hosting convention (preview tools and platforms set it); it wins over API_PORT in .env.
    api_port: int = Field(validation_alias=AliasChoices("PORT", "API_PORT"))
    web_dist_dir: Path  # the built UI; served at / when it exists
    dev_cors_origin: str  # the Vite dev server, allowed to call the API while developing


def load_api_settings(**overrides) -> ApiSettings:
    return ApiSettings(**overrides)
