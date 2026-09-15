"""Constants for the latching board tester.

Everything the test steps need to know about *this* board lives here: rail
settings, waveforms, relay mapping, serial commands and their regex parsers,
and timing. Steps import from here rather than hard-coding numbers, so changing
a rail voltage is a one-line edit in one file.

Limits do NOT live here - they live in result_details.toml, so they can be
reviewed and changed without touching code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from instruments.function_generator import FG_Setting, Waveforms
from instruments.psu import PSU_Setting
from utils.serial_device import BaseSerialCommandParser, SerialCommand

# ---------------------------------------------------------------------------
# Board identity
# ---------------------------------------------------------------------------

BOARD_NAME = "ePBR27 Latching Board"
SERIAL_NUMBER_PREFIX = "EPBR27-LB-"


# ---------------------------------------------------------------------------
# Power supply settings
# ---------------------------------------------------------------------------


class PSU_Settings:
    """Named rail configurations. Referenced by @with_psu on a test step."""

    OFF = PSU_Setting(voltage=0.0, current=0.0)

    # Nominal board supply. Set the current limit to something the board cannot
    # survive drawing, so a short trips the supply instead of cooking a trace.
    NOMINAL_12V = PSU_Setting(voltage=12.0, current=0.5, settle_s=0.2)

    # Brown-out / over-voltage corners for supply-range tests.
    LOW_9V = PSU_Setting(voltage=9.0, current=0.5, settle_s=0.2)
    HIGH_15V = PSU_Setting(voltage=15.0, current=0.5, settle_s=0.2)

    # Current-limited rail for the first power-up of an unknown board.
    CURRENT_LIMITED = PSU_Setting(voltage=12.0, current=0.05, settle_s=0.5)


# ---------------------------------------------------------------------------
# Function generator settings
# ---------------------------------------------------------------------------


class FG_Settings:
    """Named waveforms driven into the board's inputs."""

    OFF = FG_Setting(waveform=Waveforms.DC, low_v=0.0, high_v=0.0)

    # Square wave to exercise a latch/trigger input.
    TRIGGER_5V_1KHZ = FG_Setting(
        waveform=Waveforms.SQUARE,
        period=0.001,
        duty_cycle=50.0,
        low_v=0.0,
        high_v=5.0,
    )

    # Slow square wave you can follow with a DMM rather than a scope.
    TRIGGER_5V_1HZ = FG_Setting(
        waveform=Waveforms.SQUARE,
        period=1.0,
        duty_cycle=50.0,
        low_v=0.0,
        high_v=5.0,
    )

    # Short burst, for a latch that should fire once per pulse train.
    TRIGGER_BURST = FG_Setting(
        waveform=Waveforms.SQUARE,
        period=0.01,
        duty_cycle=50.0,
        low_v=0.0,
        high_v=5.0,
        burst=True,
        burst_cycles=3,
        burst_period=0.5,
    )


# ---------------------------------------------------------------------------
# Relay bank mapping
# ---------------------------------------------------------------------------


class Relays(IntEnum):
    """Which relay channel routes the DMM (or a load) to which node.

    Edit these to match how the fixture is actually wired, then steps read as
    `relay.open_only(Relays.COIL_SENSE)` instead of a bare channel number.
    """

    COIL_DRIVE = 1  # applies the coil drive path
    COIL_SENSE = 2  # DMM across the coil
    LATCH_SENSE = 3  # DMM on the latch state output
    SUPPLY_SENSE = 4  # DMM on the board supply rail
    TRIGGER_INJECT = 5  # routes the FG output to the trigger input
    LOAD_ENABLE = 6  # connects the dummy load
    SPARE_7 = 7
    SPARE_8 = 8


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


class Times:
    """One place for every sleep in the tester - makes tuning a run tractable."""

    BOOTUP_S = 1.0
    POWER_CYCLE_S = 0.5
    RELAY_SETTLE_S = 0.05
    DMM_SETTLE_S = 0.3
    LATCH_ACTUATE_S = 0.2
    SERIAL_TIMEOUT_S = 2.0
    SERIAL_BOOT_TIMEOUT_S = 5.0
    WAIT_TIMEOUT_S = 10.0


class Retries:
    SERIAL = 3
    MEASUREMENT = 2


class Thresholds:
    """Decision thresholds used inside step logic.

    Pass/fail limits belong in result_details.toml; these are the thresholds a
    step needs to interpret a reading at all (what counts as 'high', etc).
    """

    LOGIC_LOW_V = 0.8
    LOGIC_HIGH_V = 2.0
    CONTINUITY_OHMS = 10.0
    OPEN_CIRCUIT_OHMS = 1_000_000.0


# ---------------------------------------------------------------------------
# Serial console: response parsers
# ---------------------------------------------------------------------------
# Each parser is a dataclass with a `pattern` whose capture groups line up with
# its fields, in order. Replace these with whatever your firmware prints.


@dataclass
class VersionInfo(BaseSerialCommandParser):
    """Parses: 'ePBR27-LB v1.2.3'"""

    pattern = r"ePBR27-LB\s+v(?P<version>[\d.]+)"
    version: str


@dataclass
class SerialNumberInfo(BaseSerialCommandParser):
    """Parses: 'SN EPBR27-LB-0042'"""

    pattern = r"SN\s+(?P<serial_number>[\w-]+)"
    serial_number: str


@dataclass
class LatchStatus(BaseSerialCommandParser):
    """Parses: 'LATCH LATCHED CURRENT 120 mA'"""

    pattern = r"LATCH\s+(?P<state>\w+)\s+CURRENT\s+(?P<current_ma>-?\d+)\s*mA"
    state: str
    current_ma: str

    @property
    def is_latched(self) -> bool:
        return self.state.upper() == LatchState.LATCHED

    @property
    def current_amps(self) -> float:
        return int(self.current_ma) / 1000.0


@dataclass
class RailInfo(BaseSerialCommandParser):
    """Parses a multi-line rail dump:
    'VIN  12034 mV'
    '3V3   3298 mV'
    """

    pattern = r"VIN\s+(?P<vin_mv>-?\d+)\s*mV[\s\S]*?3V3\s+(?P<v3v3_mv>-?\d+)\s*mV"
    vin_mv: str
    v3v3_mv: str

    @property
    def vin_volts(self) -> float:
        return int(self.vin_mv) / 1000.0

    @property
    def v3v3_volts(self) -> float:
        return int(self.v3v3_mv) / 1000.0


class LatchState:
    LATCHED = "LATCHED"
    UNLATCHED = "UNLATCHED"
    FAULT = "FAULT"


# ---------------------------------------------------------------------------
# Serial console: commands
# ---------------------------------------------------------------------------


class SerialCommands:
    """The board's console commands.

    A command with a parser can be used with `send_command_and_parse()`; one
    without just returns raw text from `send_command()`.
    """

    ENTER = SerialCommand("")
    HELP = SerialCommand("help")
    RESET = SerialCommand("reset")

    VERSION = SerialCommand("version", VersionInfo)
    SERIAL_NUMBER = SerialCommand("sn", SerialNumberInfo)
    SET_SERIAL_NUMBER = SerialCommand("sn", SerialNumberInfo)  # .with_args("EPBR27-LB-0042")

    LATCH_STATUS = SerialCommand("latch status", LatchStatus)
    LATCH_SET = SerialCommand("latch set")
    LATCH_CLEAR = SerialCommand("latch clear")

    RAILS = SerialCommand("rails", RailInfo)

    # Sent to confirm the board rejects nonsense rather than hanging.
    INVALID = SerialCommand("thiscommanddoesnotexist")
