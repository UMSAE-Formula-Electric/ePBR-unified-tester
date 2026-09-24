"""Station-wide settings: environment flags plus the instrument address book.

Instrument addressing lives in `config/station.toml` (checked in) and can be
overridden per-machine by `config/station.local.toml` (gitignored) so the COM
port numbers on your laptop don't fight with the ones on the pit bench PC.

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import os
import tomllib
from typing import Any, Dict

from dotenv import load_dotenv

from config.paths import Config

load_dotenv()


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"true", "1", "yes", "on"}


class Env:
    """Values read once from the environment at import."""

    # When true every instrument driver returns plausible fake data instead of
    # touching hardware. Lets you build and dry-run a tester with nothing plugged in.
    SIMULATE = _flag("SIMULATE", False)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    OPERATOR = os.getenv("OPERATOR", "unknown")


class Runtime:
    """Flags that can change after startup, e.g. from a CLI switch.

    Instrument drivers are constructed deep inside test steps and decorators, so
    there is no practical way to thread `--simulate` down to each one by hand.
    They read it from here instead.
    """

    simulate: bool = Env.SIMULATE


def set_simulate(value: bool) -> None:
    """Switch the whole process between real hardware and simulation."""
    Runtime.simulate = bool(value)


def is_simulated() -> bool:
    return Runtime.simulate


def _load_station() -> Dict[str, Any]:
    station: Dict[str, Any] = {}

    if Config.STATION_TOML.exists():
        with Config.STATION_TOML.open("rb") as f:
            station = tomllib.load(f)

    if Config.STATION_LOCAL_TOML.exists():
        with Config.STATION_LOCAL_TOML.open("rb") as f:
            local = tomllib.load(f)
        for section, values in local.items():
            if isinstance(values, dict) and isinstance(station.get(section), dict):
                station[section].update(values)
            else:
                station[section] = values

    return station


STATION: Dict[str, Any] = _load_station()


def instrument_config(name: str) -> Dict[str, Any]:
    """Config block for one instrument, e.g. instrument_config("psu")."""
    return dict(STATION.get(name, {}))


def simulation_config(name: str) -> Dict[str, str]:
    """Canned responses for one instrument in simulate mode.

    Read from the `[<name>.simulation]` table in station.toml, mapping a command
    to the reply it should get. The key "*" is the fallback for anything not
    listed. Populating these is what makes a dry run produce realistic values
    instead of zeros.
    """
    simulation = STATION.get(name, {}).get("simulation", {})
    return {str(k): str(v) for k, v in simulation.items()}


class Timeouts:
    """Defaults used when a call doesn't specify its own."""

    SERIAL_S = 5.0
    SCPI_S = 5.0
    INSTRUMENT_CONNECT_S = 10.0


class Retries:
    SERIAL = 3
    INSTRUMENT = 2
