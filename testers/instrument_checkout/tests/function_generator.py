"""Function generator checks that need no cable.

Without a scope or a meter attached there's a limit to what can be proven
here: these steps confirm the FG accepts a waveform and reads it back
correctly, which catches wrong SCPI verbs and a wedged instrument. Whether the
output is actually *right* is settled by the loopback tests.
"""

from __future__ import annotations

from core.decorators import test_step_result
from core.logger import logger
from core.runner import TestRunner
from instruments.function_generator import FunctionGenerator
from testers.instrument_checkout.config import FG_CHANNEL, FG_Settings
from testers.instrument_checkout.utils import stop_fg


@test_step_result("BENCH_FG_WAVEFORM_ECHO", "BENCH_FG_ACCEPTS_SETTINGS")
def FG_PROGRAMMING(runner: TestRunner):
    """Program a square wave, then read the FG's own description of it back.

    If the readback doesn't mention the waveform we asked for, the command set
    in instruments/function_generator.py doesn't match this model. That's the
    first thing to check when the loopback numbers look nonsensical.
    """
    echo = ""
    accepted = False

    try:
        with FunctionGenerator(off_on_exit=True) as fg:
            fg.apply_setting(FG_Settings.SQUARE_0_5V, channel=FG_CHANNEL, enable=False)
            echo = fg.get_waveform(channel=FG_CHANNEL)
            accepted = True
    except Exception as e:
        logger.error(f"Could not program the function generator: {e}")

    logger.info(f"FG waveform readback: {echo or '(nothing)'}")

    runner.add_result("BENCH_FG_ACCEPTS_SETTINGS", accepted)
    runner.add_result("BENCH_FG_WAVEFORM_ECHO", echo)


@test_step_result("BENCH_FG_OUTPUT_TOGGLES")
def FG_OUTPUT_CONTROL(runner: TestRunner):
    """Switch the output on and off again, confirming both are accepted.

    Cheap, but it's the command every `@with_fg` step depends on to leave the
    bench safe, so it's worth proving it works before trusting it.
    """
    toggled = False

    try:
        with FunctionGenerator(off_on_exit=True) as fg:
            fg.apply_setting(FG_Settings.OFF, channel=FG_CHANNEL, enable=False)
            fg.enable_output(FG_CHANNEL)
            fg.disable_output(FG_CHANNEL)
            toggled = True
    except Exception as e:
        logger.error(f"Could not toggle the function generator output: {e}")
    finally:
        stop_fg()

    runner.add_result("BENCH_FG_OUTPUT_TOGGLES", toggled)
