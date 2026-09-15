"""Filesystem layout. Everything resolves from the repo root, not the CWD,
so the CLI behaves the same no matter where you run it from.
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


class Logs:
    BASE = ROOT_DIR / "logs"


class Results:
    BASE = ROOT_DIR / "results"
    SUMMARY_CSV = BASE / "summary.csv"


class Testers:
    BASE = ROOT_DIR / "testers"


class Config:
    BASE = ROOT_DIR / "config"
    STATION_TOML = BASE / "station.toml"
    # Optional per-machine override, gitignored. Use it for the COM ports on
    # your laptop without touching the shared station.toml.
    STATION_LOCAL_TOML = BASE / "station.local.toml"


class Firmware:
    """Drop .bin/.hex/.elf images here if you add a flashing step later."""

    BASE = ROOT_DIR / "firmware"
