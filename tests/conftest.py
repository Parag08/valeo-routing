"""Shared fixtures: settings from .env.example with absolute paths, and one generated dataset."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from valeo_routing.datagen.generate import generate, write
from valeo_routing.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def make_settings(output_dir: Path) -> Settings:
    s = Settings(_env_file=str(ROOT / ".env.example"))
    return Settings(
        _env_file=str(ROOT / ".env.example"),
        data_reference_dir=ROOT / s.data_reference_dir,
        demand_profile_path=ROOT / s.demand_profile_path,
        data_output_dir=output_dir,
    )


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
    return make_settings(tmp_path_factory.mktemp("out"))


@pytest.fixture(scope="session")
def written(settings) -> Path:
    write(generate(settings), settings.data_output_dir)
    return settings.data_output_dir


@pytest.fixture(scope="session")
def profile(settings) -> dict:
    return json.loads(settings.demand_profile_path.read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
