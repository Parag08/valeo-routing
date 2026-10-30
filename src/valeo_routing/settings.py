"""Settings read from `.env`. Every field is required: a missing key fails fast."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime parameters. No defaults by design."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_seed: int
    data_start_date: date
    data_days: int
    data_reference_dir: Path
    data_output_dir: Path
    demand_profile_path: Path

    vol_nursing_per_day: float
    vol_babysitting_per_day: float
    vol_sample_per_day: float

    staff_home_nurses: int
    staff_babysitters: int
    staff_collection_nurses: int

    clients_total: int


def load_settings(**overrides) -> Settings:
    """Load settings from `.env` (and the environment), with optional explicit overrides."""
    return Settings(**overrides)
