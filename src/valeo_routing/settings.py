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
