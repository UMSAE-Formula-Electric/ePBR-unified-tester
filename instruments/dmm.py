"""BK Precision 5492B bench DMM.

MODEL NOTES
-----------
The 5492B exposes a USB virtual COM port (a CP210x bridge, VID 0x10C4 /
PID 0xEA60) and takes SCPI over it at 9600-8N1.

Commands verified against a real unit (firmware Ver1.1.13.06.04) and against
the manual's Chapter 6:

    CONF:VOLT:DC         select the measurement function
    READ?                trigger and read on the current function
    CONF?                query the selected function, e.g. "volt:dc"
    VOLT:DC:RANG 10      pin the range

IMPORTANT - this instrument has no error queue and does not reject bad
commands gracefully. An unsupported command silently wedges its SCPI parser,
and every subsequent query times out until a valid command arrives. Two traps
found the hard way:

  * `FUNC "VOLT:DC"` is NOT accepted, despite being standard SCPI. Use
    `CONF:<function>`. The wedge is silent, so the symptom is a working
    connection whose reads all time out, and a function that never changed.
  * `<function>:RANG:AUTO ON` works on VOLT:DC and RES but wedges the parser
    on FREQ, VOLT:AC and CURR:DC. It is never sent automatically - CONFigure
    already defaults the function's controls, autoranging included.

So: only send commands from the `Scpi` class below, and only select functions
listed in `Function`. Capacitance and temperature are deliberately absent -
the 5492B cannot measure either, and asking it to wedges the parser.

Two ways to take a reading:

    dmm.measure_dc_voltage()          # one-shot: configure, trigger, read
    dmm.set_function(Function.DC_VOLTAGE, range_value=10)
    dmm.read()                        # repeat reads on a fixed range, faster

Pair it with the relay bank to move one DMM around the board:

    @with_relay(RelayChannel.COIL_SENSE)
    def MY_STEP(runner):
        with DMM() as dmm:
            runner.add_result("LB_COIL_V", dmm.measure_dc_voltage())

Author: Cedric Caparas
Date:   2026-09-24
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
    """The functions this DMM actually has, per the manual's CONFigure list.

    Anything not in here wedges the instrument's parser, so don't add a member
    without confirming the hardware accepts `CONF:<value>` first.
    """

    DC_VOLTAGE = "VOLT:DC"
    AC_VOLTAGE = "VOLT:AC"
    DC_CURRENT = "CURR:DC"
    AC_CURRENT = "CURR:AC"
    RESISTANCE = "RES"
    RESISTANCE_4W = "FRES"
    FREQUENCY = "FREQ"
    PERIOD = "PER"
    DIODE = "DIOD"
    CONTINUITY = "CONT"


class Scpi:
    IDENTIFY = "*IDN?"
    RESET = "*RST"
    CLEAR_STATUS = "*CLS"
    SET_FUNCTION = "CONF:{function}"
    GET_FUNCTION = "CONF?"
    SET_RANGE = "{function}:RANG {range_value}"
    # Present for completeness, but not sent automatically: it wedges the
    # parser on several functions, and CONFigure already enables autoranging.
    SET_AUTO_RANGE = "{function}:RANG:AUTO ON"
    MEASURE = "MEAS:{function}?"
    READ = "READ?"
    # FETCh returns the latest reading and needs a prior INITiate, so it is
    # only meaningful straight after a READ?. Not reliable standalone here.
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
        """Select a measurement function, optionally pinning the range.

        Sends `CONF:<function>`, which also resets that function's controls to
        their defaults - autoranging included. No autorange command is sent,
        because it wedges this instrument's parser on several functions.

        Pass `range_value` to pin the range, which is worth doing when reading
        the same node repeatedly: autoranging costs a few hundred ms a reading.
        """
        if not isinstance(function, Function):
            raise TypeError(f"Expected a Function, got {function!r}")

        if self._function is not function:
            self.write(Scpi.SET_FUNCTION.format(function=function.value))
            self._function = function
            time.sleep(self.settle_s)

        if range_value is not None:
            self.write(Scpi.SET_RANGE.format(function=function.value, range_value=range_value))
            time.sleep(self.settle_s)

    def get_function(self) -> str:
        """The function the DMM says it's on, e.g. "volt:dc".

        Useful as a liveness check: if this comes back empty, the parser is
        wedged and something sent a command the instrument doesn't accept.
        """
        return self.query(Scpi.GET_FUNCTION)

    def read(self) -> float:
        """Trigger and read using whatever function is already selected."""
        return self._query_float(Scpi.READ)

    def fetch(self) -> float:
        """Re-read the last reading without re-triggering.

        Only meaningful straight after a `read()`; on its own the instrument
        has nothing initiated and stays silent.
        """
        return self._query_float(Scpi.FETCH)

    def measure(self, function: Function) -> float:
        """Configure the function and take one reading.

        Uses CONFigure + READ? rather than `MEAS:<function>?`. The manual
        defines them as equivalent, but MEAS is unreliable on this firmware -
        `MEAS:RES?` in particular returns nothing.
        """
        self.set_function(function)
        return self.read()

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
