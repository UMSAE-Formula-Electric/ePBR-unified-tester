"""BK Precision 5492B bench DMM.

MODEL NOTES
-----------
The 5492B exposes a USB virtual COM port and takes SCPI over it (default
9600-8N1; confirm under the DMM's I/O setup menu). The commands used here are
the standard SCPI measurement set:

    FUNC "VOLT:DC"       select function
    MEAS:VOLT:DC?        one-shot configure + trigger + read
    READ?                trigger + read using the current function
    VOLT:DC:RANG 10      fix the range (much faster than autorange)

Two ways to take a reading:

    dmm.measure_dc_voltage()          # one-shot, simplest, ~autoranges
    dmm.set_function(Function.DC_VOLTAGE, range_value=10)
    dmm.read()                        # repeat reads on a fixed range, faster

Pair it with the relay bank to move one DMM around the board:

    @with_relay(RelayChannel.COIL_SENSE)
    def MY_STEP(runner):
        with DMM() as dmm:
            runner.add_result("LB_COIL_V", dmm.measure_dc_voltage())
"""

from __future__ import annotations

import time
from enum import Enum
from typing import List, Optional

from config.settings import instrument_config, is_simulated
from core.logger import logger
from instruments.transport import Transport, build_transport

INVALID_RESULT = -9999.0


class Function(Enum):
    """SCPI function names, as the DMM expects them."""

    DC_VOLTAGE = "VOLT:DC"
    AC_VOLTAGE = "VOLT:AC"
    DC_CURRENT = "CURR:DC"
    AC_CURRENT = "CURR:AC"
    RESISTANCE = "RES"
    RESISTANCE_4W = "FRES"
    CAPACITANCE = "CAP"
    FREQUENCY = "FREQ"
    PERIOD = "PER"
    DIODE = "DIOD"
    CONTINUITY = "CONT"
    TEMPERATURE = "TEMP"


class Scpi:
    IDENTIFY = "*IDN?"
    RESET = "*RST"
    CLEAR_STATUS = "*CLS"
    SET_FUNCTION = 'FUNC "{function}"'
    GET_FUNCTION = "FUNC?"
    SET_RANGE = "{function}:RANG {range_value}"
    SET_AUTO_RANGE = "{function}:RANG:AUTO ON"
    MEASURE = "MEAS:{function}?"
    READ = "READ?"
    FETCH = "FETC?"
    REMOTE = "SYST:REM"
    LOCAL = "SYST:LOC"


class DMM:
    """Context-managed DMM. Returns the instrument to local control on exit."""

    def __init__(
        self,
        transport: Optional[Transport] = None,
        simulate: Optional[bool] = None,
    ) -> None:
        self.config = instrument_config("dmm")
        self.simulate = is_simulated() if simulate is None else simulate
        self.transport = transport or build_transport(self.config, "dmm", self.simulate)
        self.settle_s = float(self.config.get("settle_s", 0.3))
        self._function: Optional[Function] = None

    def __enter__(self) -> "DMM":
        self.transport.open()
        try:
            self.write(Scpi.REMOTE)
        except Exception as e:
            # Not every model needs (or accepts) an explicit remote command.
            logger.debug(f"DMM did not accept a remote-mode command: {e}")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            self.write(Scpi.LOCAL)
        except Exception:
            pass
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
            logger.error(f"DMM query '{command}' failed: {e}")
            return INVALID_RESULT

    # -------------------------------------------------------------- control

    def identify(self) -> str:
        return self.query(Scpi.IDENTIFY)

    def reset(self) -> None:
        self.write(Scpi.RESET)
        self.write(Scpi.CLEAR_STATUS)
        self._function = None

    def set_function(self, function: Function, range_value: Optional[float] = None) -> None:
        """Select a function, optionally pinning the range.

        Fixing the range is worth it whenever you read the same node repeatedly:
        autoranging costs a few hundred ms per reading.
        """
        if self._function is not function:
            self.write(Scpi.SET_FUNCTION.format(function=function.value))
            self._function = function
            time.sleep(self.settle_s)

        if range_value is None:
            self.write(Scpi.SET_AUTO_RANGE.format(function=function.value))
        else:
            self.write(Scpi.SET_RANGE.format(function=function.value, range_value=range_value))

    def read(self) -> float:
        """Trigger and read using whatever function is already selected."""
        return self._query_float(Scpi.READ)

    def fetch(self) -> float:
        """Re-read the last reading without re-triggering."""
        return self._query_float(Scpi.FETCH)

    def measure(self, function: Function) -> float:
        """One-shot: configure, trigger and read in a single command."""
        self._function = function
        return self._query_float(Scpi.MEASURE.format(function=function.value))

    # ---------------------------------------------------- convenience reads

    def measure_dc_voltage(self) -> float:
        return self.measure(Function.DC_VOLTAGE)

    def measure_ac_voltage(self) -> float:
        return self.measure(Function.AC_VOLTAGE)

    def measure_dc_current(self) -> float:
        return self.measure(Function.DC_CURRENT)

    def measure_ac_current(self) -> float:
        return self.measure(Function.AC_CURRENT)

    def measure_resistance(self, four_wire: bool = False) -> float:
        return self.measure(Function.RESISTANCE_4W if four_wire else Function.RESISTANCE)

    def measure_capacitance(self) -> float:
        return self.measure(Function.CAPACITANCE)

    def measure_frequency(self) -> float:
        return self.measure(Function.FREQUENCY)

    def measure_diode(self) -> float:
        return self.measure(Function.DIODE)

    def is_continuous(self, threshold_ohms: float = 10.0) -> bool:
        """True when the node reads below `threshold_ohms` - a shorts/opens check."""
        resistance = self.measure_resistance()
        return 0 <= resistance <= threshold_ohms

    # ---------------------------------------------------------- averaging

    def measure_average(self, function: Function, samples: int = 5, delay_s: float = 0.05) -> float:
        """Mean of N readings on a fixed function - quiets down a noisy node."""
        readings = self.measure_samples(function, samples=samples, delay_s=delay_s)
        valid = [r for r in readings if r != INVALID_RESULT]
        if not valid:
            return INVALID_RESULT
        return round(sum(valid) / len(valid), 6)

    def measure_samples(self, function: Function, samples: int = 5, delay_s: float = 0.05) -> List[float]:
        """N readings on a fixed function. Use it to look at ripple or settling."""
        self.set_function(function)
        readings = []
        for _ in range(samples):
            readings.append(self.read())
            if delay_s:
                time.sleep(delay_s)
        return readings


def main() -> None:
    """Smoke test: python -m instruments.dmm"""
    with DMM() as dmm:
        logger.info(f"IDN: {dmm.identify()}")
        logger.info(f"DC voltage:  {dmm.measure_dc_voltage():.6f} V")
        logger.info(f"Resistance:  {dmm.measure_resistance():.6f} ohm")


if __name__ == "__main__":
    main()
