"""BK Precision 4052 arbitrary/function generator.

MODEL NOTES
-----------
The BK 4050 series uses the Siglent-derived command set, where a whole waveform
is programmed in one comma-separated "basic wave" command:

    C1:BSWV WVTP,SQUARE,FRQ,1000HZ,AMP,5V,OFST,2.5V,DUTY,50
    C1:OUTP ON,LOAD,HZ
    C1:BTWV STATE,ON,TIME,3,PRD,0.75S      (burst)

Verify against the 4052 programming manual when the unit is on the bench - if
a verb differs, edit the `Scpi` class below and nothing else changes.

Note on levels: the instrument is programmed in amplitude + offset, but test
limits are almost always written as "low level / high level" volts. `FG_Setting`
takes low_v/high_v and converts, so your tester config reads the way you think
about the signal.

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config.settings import instrument_config, is_simulated
from core.logger import logger
from instruments.transport import Transport, build_transport

SETTLE_AFTER_SET_S = 0.05


class Waveforms(Enum):
    SINE = "SINE"
    SQUARE = "SQUARE"
    RAMP = "RAMP"
    PULSE = "PULSE"
    NOISE = "NOISE"
    DC = "DC"
    ARB = "ARB"


class Scpi:
    IDENTIFY = "*IDN?"
    RESET = "*RST"
    # {channel} is 1-based; the 4050 series addresses channels as C1:/C2:
    BASIC_WAVE = "C{channel}:BSWV {parameters}"
    GET_BASIC_WAVE = "C{channel}:BSWV?"
    OUTPUT_ON = "C{channel}:OUTP ON,LOAD,{load}"
    OUTPUT_OFF = "C{channel}:OUTP OFF"
    GET_OUTPUT = "C{channel}:OUTP?"
    BURST_ON = "C{channel}:BTWV STATE,ON,TIME,{cycles},PRD,{period}S"
    BURST_OFF = "C{channel}:BTWV STATE,OFF"


@dataclass(frozen=True)
class FG_Setting:
    """A named waveform. Define these in your tester's config.py.

    Levels are given as low_v/high_v; the driver converts to the amplitude and
    offset the instrument actually wants.
    """

    waveform: Waveforms = Waveforms.SQUARE
    period: float = 1.0  # seconds; frequency = 1/period
    duty_cycle: float = 50.0  # percent, square/pulse only
    low_v: float = 0.0
    high_v: float = 5.0
    channel: int = 1
    burst: bool = False
    burst_cycles: int = 1
    burst_period: float = 1.0
    settle_s: float = 0.0

    @property
    def frequency(self) -> float:
        if self.period <= 0:
            raise ValueError("FG_Setting.period must be greater than 0")
        return 1.0 / self.period

    @property
    def amplitude(self) -> float:
        return abs(self.high_v - self.low_v)

    @property
    def offset(self) -> float:
        return (self.high_v + self.low_v) / 2.0

    def __str__(self) -> str:
        base = f"{self.waveform.value} {self.low_v}..{self.high_v}V @ {self.frequency:.3f}Hz"
        if self.waveform in {Waveforms.SQUARE, Waveforms.PULSE}:
            base += f" {self.duty_cycle:.1f}%"
        if self.burst:
            base += f" burst x{self.burst_cycles} every {self.burst_period}s"
        return base


class FunctionGenerator:
    """Context-managed FG. Output is switched off on exit unless you opt out."""

    def __init__(
        self,
        transport: Optional[Transport] = None,
        off_on_exit: Optional[bool] = None,
        simulate: Optional[bool] = None,
    ) -> None:
        self.config = instrument_config("function_generator")
        self.simulate = is_simulated() if simulate is None else simulate
        self.transport = transport or build_transport(self.config, "function_generator", self.simulate)
        self.channels = int(self.config.get("channels", 2))
        self.default_channel = int(self.config.get("default_channel", 1))
        self.load = str(self.config.get("default_load", "HZ"))
        self.off_on_exit = bool(self.config.get("off_on_exit", True)) if off_on_exit is None else off_on_exit

    def __enter__(self) -> "FunctionGenerator":
        self.transport.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if self.off_on_exit:
                self.disable_all_outputs()
        except Exception as e:
            logger.error(f"Could not turn the function generator off on exit: {e}")
        finally:
            self.transport.close()

    # ------------------------------------------------------------- plumbing

    def write(self, command: str) -> None:
        self.transport.write(command)

    def query(self, command: str) -> str:
        return self.transport.query(command)

    def _channel(self, channel: Optional[int]) -> int:
        return self.default_channel if channel is None else channel

    # -------------------------------------------------------------- control

    def identify(self) -> str:
        return self.query(Scpi.IDENTIFY)

    def apply_setting(self, setting: FG_Setting, channel: Optional[int] = None, enable: bool = False) -> None:
        """Program a whole waveform in one command."""
        ch = self._channel(channel if channel is not None else setting.channel)
        logger.debug(f"FG CH{ch} apply {setting}")

        parameters = [
            f"WVTP,{setting.waveform.value}",
            f"FRQ,{setting.frequency:.6f}HZ",
            f"AMP,{setting.amplitude:.4f}V",
            f"OFST,{setting.offset:.4f}V",
        ]
        if setting.waveform in {Waveforms.SQUARE, Waveforms.PULSE}:
            parameters.append(f"DUTY,{setting.duty_cycle:.2f}")

        self.write(Scpi.BASIC_WAVE.format(channel=ch, parameters=",".join(parameters)))

        if setting.burst:
            self.write(
                Scpi.BURST_ON.format(channel=ch, cycles=setting.burst_cycles, period=setting.burst_period)
            )
        else:
            self.write(Scpi.BURST_OFF.format(channel=ch))

        time.sleep(SETTLE_AFTER_SET_S)
        if enable:
            self.enable_output(ch)
        if setting.settle_s:
            time.sleep(setting.settle_s)

    def set_frequency(self, frequency: float, channel: Optional[int] = None) -> None:
        ch = self._channel(channel)
        self.write(Scpi.BASIC_WAVE.format(channel=ch, parameters=f"FRQ,{frequency:.6f}HZ"))

    def set_period(self, period: float, channel: Optional[int] = None) -> None:
        if period <= 0:
            raise ValueError("period must be greater than 0")
        self.set_frequency(1.0 / period, channel)

    def set_duty_cycle(self, duty_cycle: float, channel: Optional[int] = None) -> None:
        ch = self._channel(channel)
        self.write(Scpi.BASIC_WAVE.format(channel=ch, parameters=f"DUTY,{duty_cycle:.2f}"))

    def set_amplitude(self, amplitude: float, channel: Optional[int] = None) -> None:
        ch = self._channel(channel)
        self.write(Scpi.BASIC_WAVE.format(channel=ch, parameters=f"AMP,{amplitude:.4f}V"))

    def set_offset(self, offset: float, channel: Optional[int] = None) -> None:
        ch = self._channel(channel)
        self.write(Scpi.BASIC_WAVE.format(channel=ch, parameters=f"OFST,{offset:.4f}V"))

    def set_high_level(self, high_v: float, channel: Optional[int] = None) -> None:
        """Change only the high level, as a step sweeping a threshold does."""
        ch = self._channel(channel)
        self.write(Scpi.BASIC_WAVE.format(channel=ch, parameters=f"HLEV,{high_v:.4f}V"))

    def set_low_level(self, low_v: float, channel: Optional[int] = None) -> None:
        ch = self._channel(channel)
        self.write(Scpi.BASIC_WAVE.format(channel=ch, parameters=f"LLEV,{low_v:.4f}V"))

    def set_dc_level(self, voltage: float, channel: Optional[int] = None) -> None:
        """Drive a flat DC level - useful for feeding an analogue input a fixed voltage."""
        ch = self._channel(channel)
        self.write(Scpi.BASIC_WAVE.format(channel=ch, parameters=f"WVTP,DC,OFST,{voltage:.4f}V"))

    def enable_output(self, channel: Optional[int] = None) -> None:
        ch = self._channel(channel)
        self.write(Scpi.OUTPUT_ON.format(channel=ch, load=self.load))

    def disable_output(self, channel: Optional[int] = None) -> None:
        ch = self._channel(channel)
        self.write(Scpi.OUTPUT_OFF.format(channel=ch))

    def disable_all_outputs(self) -> None:
        for channel in range(1, self.channels + 1):
            self.disable_output(channel)

    def get_waveform(self, channel: Optional[int] = None) -> str:
        ch = self._channel(channel)
        return self.query(Scpi.GET_BASIC_WAVE.format(channel=ch))


# --------------------------------------------------------------------------
# Helpers used by the @with_fg / @with_fg_off decorators.
# --------------------------------------------------------------------------


def fg_on(setting: FG_Setting, channel: Optional[int] = None) -> None:
    logger.info(f"FG on: {setting}")
    with FunctionGenerator(off_on_exit=False) as fg:
        fg.apply_setting(setting, channel=channel, enable=True)


def fg_off(channel: Optional[int] = None) -> None:
    logger.info("FG off")
    with FunctionGenerator(off_on_exit=False) as fg:
        if channel is None:
            fg.disable_all_outputs()
        else:
            fg.disable_output(channel)


def main() -> None:
    """Smoke test: python -m instruments.function_generator"""
    setting = FG_Setting(waveform=Waveforms.SQUARE, period=0.001, duty_cycle=50.0, low_v=0.0, high_v=5.0)
    with FunctionGenerator() as fg:
        logger.info(f"IDN: {fg.identify()}")
        fg.apply_setting(setting, enable=True)
        time.sleep(2)
        logger.info(f"Waveform: {fg.get_waveform()}")


if __name__ == "__main__":
    main()
