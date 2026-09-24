"""Communication and identity steps for the bench instruments.

These need no cabling at all: USB to both instruments and nothing else. Run
them first when something stops working, to find out whether the problem is
the bench or the test.
"""

from __future__ import annotations

from core.decorators import operator_confirm, test_step_result
from core.logger import logger
from core.runner import TestRunner
from instruments.dmm import DMM
from instruments.function_generator import FunctionGenerator
from testers.instrument_checkout.config import (
    EXPECTED_DMM_HINTS,
    EXPECTED_FG_HINTS,
    Prompts,
)
from testers.instrument_checkout.utils import report_identity, stop_fg


@test_step_result("BENCH_SETUP_READY")
@operator_confirm(Prompts.BENCH_READY)
def SETUP(runner: TestRunner):
    """Confirm the bench is powered up, and leave the FG output off."""
    stop_fg()
    logger.info("Function generator output off, starting checkout")
    runner.add_result("BENCH_SETUP_READY", True)


@test_step_result("BENCH_DMM_RESPONDS", "BENCH_DMM_IDN")
def DMM_IDENTITY(runner: TestRunner):
    """Ask the DMM who it is.

    A failure here is almost always the COM port or the DMM's I/O menu, not the
    instrument. `python main.py ports` shows what the PC can see.
    """
    idn = ""
    try:
        with DMM() as dmm:
            idn = dmm.identify()
    except Exception as e:
        logger.error(f"Could not reach the DMM: {e}")

    report_identity("DMM", idn, EXPECTED_DMM_HINTS)

    runner.add_result("BENCH_DMM_RESPONDS", bool(idn))
    runner.add_result("BENCH_DMM_IDN", idn)


@test_step_result("BENCH_FG_RESPONDS", "BENCH_FG_IDN")
def FG_IDENTITY(runner: TestRunner):
    """Ask the function generator who it is.

    If this fails while the DMM works, it's usually the USB-TMC side: the FG
    needs a WinUSB driver bound (Zadig) or NI-VISA installed.
    """
    idn = ""
    try:
        with FunctionGenerator(off_on_exit=False) as fg:
            idn = fg.identify()
    except Exception as e:
        logger.error(f"Could not reach the function generator: {e}")

    report_identity("Function generator", idn, EXPECTED_FG_HINTS)

    runner.add_result("BENCH_FG_RESPONDS", bool(idn))
    runner.add_result("BENCH_FG_IDN", idn)


@test_step_result("BENCH_TEARDOWN_SAFE")
def TEARDOWN(runner: TestRunner):
    """Leave the FG output off so nothing is driving the bench afterwards."""
    stop_fg()
    runner.add_result("BENCH_TEARDOWN_SAFE", True)
