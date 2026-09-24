"""Programmable power supply (BK Precision, model TBD).

MODEL NOTES
-----------
This driver uses the generic SCPI command set that most BK bench supplies
accept (9130B, 9140, 1785B and friends):

    INST:NSEL 1          select channel
    VOLT 12.000          set voltage
    CURR 2.000           set current limit
    OUTP ON|OFF          output on/off
    MEAS:VOLT?           measured voltage
    MEAS:CURR?           measured current

When you identify the exact model, open its programming manual and check those
six verbs. If they differ, edit the `Scpi` class below - nothing outside this
file needs to change. Single-channel supplies ignore the channel select; set
`channels = 1` in config/station.toml and it is skipped entirely.

Usage in a test step:

    with PSU() as psu:
        psu.apply(PSU_Setting(voltage=12.0, current=2.0))
        psu.enable_output()
        voltage = psu.measure_voltage()

or, more usually, let the decorator handle it:

    @with_psu(PSU_Settings.LATCH_12V)
    def MY_STEP(runner): ...

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from config.settings import instrument_config, is_simulated
from core.logger import logger
from instruments.transport import Transport, build_transport

INVALID_RESULT = -9999.0
SETTLE_AFTER_SET_S = 0.05


class Scpi:
    """Every command string the driver sends. One place to fix per-model quirks."""

    IDENTIFY = "*IDN?"
    RESET = "*RST"
    CLEAR_STATUS = "*CLS"
    SELECT_CHANNEL = "INST:NSEL {channel}"
    SET_VOLTAGE = "VOLT {voltage:.3f}"
    SET_CURRENT = "CURR {current:.3f}"
    OUTPUT_ON = "OUTP ON"
    OUTPUT_OFF = "OUTP OFF"
    GET_OUTPUT_STATE = "OUTP?"
    MEASURE_VOLTAGE = "MEAS:VOLT?"
    MEASURE_CURRENT = "MEAS:CURR?"
    GET_VOLTAGE_SETTING = "VOLT?"
    GET_CURRENT_SETTING = "CURR?"


@dataclass(frozen=True)
class PSU_Setting:
    """A named rail configuration. Define these in your tester's config.py."""

    voltage: float = 0.0
    current: float = 0.0
    channel: int = 1
    settle_s: float = 0.0

    def __str__(self) -> str:
        return f"{self.voltage:.3f}V @ {self.current:.3f}A (CH{self.channel})"


class PSU:
    """Context-managed PSU. The output is dropped on exit unless you opt out."""

    def __init__(
        self,
        transport: Optional[Transport] = None,
        off_on_exit: Optional[bool] = None,
        simulate: Optional[bool] = None,
    ) -> None:
        self.config = instrument_config("psu")
        self.simulate = is_simulated() if simulate is None else simulate
        self.transport = transport or build_transport(self.config, "psu", self.simulate)
        self.channels = int(self.config.get("channels", 1))
        self.off_on_exit = bool(self.config.get("off_on_exit", True)) if off_on_exit is None else off_on_exit
        self._selected_channel: Optional[int] = None

    def __enter__(self) -> "PSU":
        self.transport.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if self.off_on_exit:
                self.turn_off()
        except Exception as e:
            logger.error(f"Could not turn the PSU off on exit: {e}")
        finally:
            self.transport.close()

    # ------------------------------------------------------------- plumbing

    def write(self, command: str) -> None:
        self.transport.write(command)

    def query(self, command: str) -> str:
        return self.transport.query(command)

    def _query_float(self, command: str) -> float:
        try:
            return float(self.query(command))
        except Exception as e:
            logger.error(f"PSU query '{command}' failed: {e}")
            return INVALID_RESULT

    def select_channel(self, channel: int = 1) -> None:
        """No-op on single-channel supplies, and skipped if already selected."""
        if self.channels <= 1 or channel == self._selected_channel:
            return
        self.write(Scpi.SELECT_CHANNEL.format(channel=channel))
        self._selected_channel = channel

    # -------------------------------------------------------------- control

    def identify(self) -> str:
        return self.query(Scpi.IDENTIFY)

    def set_voltage(self, voltage: float, channel: int = 1) -> None:
        self.select_channel(channel)
        self.write(Scpi.SET_VOLTAGE.format(voltage=voltage))

    def set_current(self, current: float, channel: int = 1) -> None:
        self.select_channel(channel)
        self.write(Scpi.SET_CURRENT.format(current=current))

    def set(self, voltage: float = 0.0, current: float = 0.0, channel: int = 1) -> None:
        self.select_channel(channel)
        self.write(Scpi.SET_VOLTAGE.format(voltage=voltage))
        self.write(Scpi.SET_CURRENT.format(current=current))
        time.sleep(SETTLE_AFTER_SET_S)

    def apply(self, setting: PSU_Setting, enable: bool = True) -> None:
        """Program a named setting and (by default) switch the output on."""
        logger.debug(f"PSU apply {setting}")
        self.set(voltage=setting.voltage, current=setting.current, channel=setting.channel)
        if enable:
            self.enable_output(setting.channel)
        if setting.settle_s:
            time.sleep(setting.settle_s)

    def enable_output(self, channel: int = 1) -> None:
        self.select_channel(channel)
        self.write(Scpi.OUTPUT_ON)

    def disable_output(self, channel: int = 1) -> None:
        self.select_channel(channel)
        self.write(Scpi.OUTPUT_OFF)

    def is_output_on(self, channel: int = 1) -> bool:
        self.select_channel(channel)
        return self.query(Scpi.GET_OUTPUT_STATE).strip().upper() in {"1", "ON"}

    def turn_off(self) -> None:
        """Zero and disable every channel - the safe resting state."""
        for channel in range(1, self.channels + 1):
            self.set(voltage=0.0, current=0.0, channel=channel)
            self.disable_output(channel)

    # ---------------------------------------------------------- measurement

    def measure_voltage(self, channel: int = 1) -> float:
        self.select_channel(channel)
        return self._query_float(Scpi.MEASURE_VOLTAGE)

    def measure_current(self, channel: int = 1) -> float:
        self.select_channel(channel)
        return self._query_float(Scpi.MEASURE_CURRENT)

    def measure_power(self, channel: int = 1) -> float:
        return round(self.measure_voltage(channel) * self.measure_current(channel), 3)

    def get_voltage_setting(self, channel: int = 1) -> float:
        self.select_channel(channel)
        return self._query_float(Scpi.GET_VOLTAGE_SETTING)

    def get_current_setting(self, channel: int = 1) -> float:
        self.select_channel(channel)
        return self._query_float(Scpi.GET_CURRENT_SETTING)


# --------------------------------------------------------------------------
# Module-level helpers, used by the @with_psu decorator. They open and close a
# connection per call, which keeps steps simple; open a PSU() yourself when a
# step needs to hold the connection across several operations.
# --------------------------------------------------------------------------


def psu_on(setting: PSU_Setting, channel: Optional[int] = None) -> None:
    effective = setting if channel is None else PSU_Setting(
        voltage=setting.voltage, current=setting.current, channel=channel, settle_s=setting.settle_s
    )
    logger.info(f"PSU on: {effective}")
    with PSU(off_on_exit=False) as psu:
        psu.apply(effective)


def psu_off(channel: Optional[int] = None) -> None:
    logger.info("PSU off")
    with PSU(off_on_exit=False) as psu:
        if channel is None:
            psu.turn_off()
        else:
            psu.set(0.0, 0.0, channel=channel)
            psu.disable_output(channel)


def main() -> None:
    """Smoke test: python -m instruments.psu"""
    with PSU() as psu:
        logger.info(f"IDN: {psu.identify()}")
        psu.apply(PSU_Setting(voltage=5.0, current=0.5))
        time.sleep(1)
        logger.info(f"Measured: {psu.measure_voltage():.3f}V @ {psu.measure_current():.3f}A")


if __name__ == "__main__":
    main()
