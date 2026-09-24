"""Cross-checks with the FG output wired into the DMM input.

Two instruments that agree on a voltage are decent evidence both are working.
These steps also exercise the framework the way a real tester does - drive
something, measure it, report the error - so they're a reasonable template for
the board testers you'll write later.

All of them need one cable: FG CH1 output to the DMM's V/ohm and COM inputs.
"""

from __future__ import annotations

from core.decorators import operator_confirm, test_step_result
from core.logger import logger
from core.runner import TestRunner
from testers.instrument_checkout.config import (
    Expected,
    FG_Settings,
    Prompts,
)
from testers.instrument_checkout.utils import (
    describe,
    drive,
    drive_dc,
    measure_ac_volts,
    measure_dc_volts,
    measure_frequency,
    percent_error,
    warn_if_doubled,
    worst_error,
)


@test_step_result("BENCH_LOOPBACK_DC_ERROR")
@operator_confirm(Prompts.CONNECT_LOOPBACK)
def LOOPBACK_DC_LEVELS(runner: TestRunner):
    """Step the FG through several DC levels and see whether the DMM agrees.

    The reported result is the worst error across the sweep, so one limit
    covers every level. Sweeping rather than testing a single point catches a
    gain error, which a single mid-scale reading can hide.
    """
    errors = []

    with drive(FG_Settings.OFF) as fg:
        for level in Expected.DC_SWEEP_LEVELS:
            drive_dc(fg, level)
            measured = measure_dc_volts()
            error = measured - level

            logger.info(f"FG set to {level:.3f} V -> DMM reads {describe(measured, level, 'V')}")
            warn_if_doubled(measured, level)

            errors.append(error)

    worst = worst_error(errors)
    logger.info(f"Worst DC error across the sweep: {worst:+.4f} V")

    runner.add_result("BENCH_LOOPBACK_DC_ERROR", abs(worst))


@test_step_result("BENCH_LOOPBACK_SQUARE_AVERAGE")
@operator_confirm(Prompts.CONNECT_LOOPBACK)
def LOOPBACK_SQUARE_AVERAGE(runner: TestRunner):
    """A 0-5 V square wave at 50% duty should average 2.5 V on the DMM's DC range.

    This works because a DMM integrates over many cycles at 1 kHz. It's a neat
    way to confirm both the FG's levels and the DMM's DC path at once.
    """
    with drive(FG_Settings.SQUARE_0_5V):
        measured = measure_dc_volts()

    logger.info(f"Square wave average: {describe(measured, Expected.SQUARE_AVERAGE_V, 'V')}")

    runner.add_result("BENCH_LOOPBACK_SQUARE_AVERAGE", measured)


@test_step_result("BENCH_LOOPBACK_DUTY_AVERAGE")
@operator_confirm(Prompts.CONNECT_LOOPBACK)
def LOOPBACK_DUTY_CYCLE(runner: TestRunner):
    """Check duty cycle with a DMM and no scope.

    A 0-4 V square at 25% duty averages 1.0 V. Since the levels were already
    confirmed by the DC sweep, the average is a direct read-out of the duty
    cycle - which is how you measure duty on a bench that has no scope.
    """
    with drive(FG_Settings.SQUARE_25_PERCENT):
        measured = measure_dc_volts()

    implied_duty = (measured / FG_Settings.SQUARE_25_PERCENT.high_v) * 100.0
    logger.info(
        f"25% duty average: {describe(measured, Expected.DUTY_AVERAGE_V, 'V')} "
        f"-> implies {implied_duty:.1f}% duty"
    )

    runner.add_result("BENCH_LOOPBACK_DUTY_AVERAGE", measured)


@test_step_result("BENCH_LOOPBACK_SINE_RMS")
@operator_confirm(Prompts.CONNECT_LOOPBACK)
def LOOPBACK_SINE_RMS(runner: TestRunner):
    """A 2 Vpp sine should read 0.707 V RMS on the DMM's AC range.

    Confirms the DMM's AC path and the FG's amplitude together: the ratio
    between peak and RMS is fixed for a sine, so agreement means both ends are
    behaving.
    """
    with drive(FG_Settings.SINE_2VPP_1KHZ):
        measured = measure_ac_volts()

    logger.info(f"Sine RMS: {describe(measured, Expected.SINE_RMS_V, 'V')}")

    runner.add_result("BENCH_LOOPBACK_SINE_RMS", measured)


@test_step_result("BENCH_LOOPBACK_FREQUENCY_ERROR")
@operator_confirm(Prompts.CONNECT_LOOPBACK)
def LOOPBACK_FREQUENCY(runner: TestRunner):
    """Check the DMM's frequency counter against the FG's timebase.

    Both instruments are crystal-referenced, so this should agree very closely.
    A big error here usually means too small an amplitude for the DMM to
    trigger on, which is why the sine is 5 Vpp rather than 2.
    """
    with drive(FG_Settings.SINE_5VPP_1KHZ):
        measured = measure_frequency()

    error_pct = percent_error(measured, Expected.FREQUENCY_HZ)
    logger.info(f"Frequency: {measured:.3f} Hz vs {Expected.FREQUENCY_HZ:.3f} Hz ({error_pct:+.4f}%)")

    runner.add_result("BENCH_LOOPBACK_FREQUENCY_ERROR", abs(error_pct))


@test_step_result("BENCH_LOOPBACK_DISCONNECTED")
def LOOPBACK_TEARDOWN(runner: TestRunner):
    """Switch the FG off and have the operator unhook the cable."""
    from testers.instrument_checkout.utils import stop_fg
    from utils.operator import confirm

    stop_fg()
    disconnected = confirm(Prompts.DISCONNECT_LOOPBACK, default=True)

    runner.add_result("BENCH_LOOPBACK_DISCONNECTED", disconnected)
