"""Decorators that wrap test steps.

Stack them on a step function; the runner calls the outermost wrapper:

    @test_step_result("LB_COIL_RESISTANCE", "LB_LATCH_CURRENT")
    @with_psu(PSU_Settings.LATCH_12V)
    @with_relay(RelayChannel.COIL)
    def LATCH_COIL_TEST(runner: TestRunner):
        ...

Order matters. `test_step_result` goes outermost so it catches anything raised
underneath, including failures in the setup/teardown decorators themselves.

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import functools
import time
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional

from core.logger import logger
from core.results import DEFAULT_RESULT

if TYPE_CHECKING:
    from core.runner import TestRunner


def test_step_result(*result_ids: str) -> Callable:
    """Guarantee every named result gets a value, even if the step blows up.

    Without this, an exception halfway through a step leaves its results
    unreported, and the operator sees a gap instead of a failure. Name every
    result the step is responsible for.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(runner: "TestRunner", *args: Any, **kwargs: Any) -> Any:
            try:
                return func(runner, *args, **kwargs)
            except Exception as e:
                logger.error(f"Exception in test step '{func.__name__}': {e}", exc_info=True)
                for result_id in result_ids:
                    if not runner.has_result(result_id):
                        runner.add_result(result_id, DEFAULT_RESULT)

        wrapper._test_step_results = result_ids  # type: ignore[attr-defined]
        return wrapper

    return decorator


def with_psu(setting, channel=None, settle_s: float = 0.0) -> Callable:
    """Power the DUT for the duration of the step, and cut power on the way out.

    The PSU is turned off in a `finally`, so a failing step never leaves the
    board energised.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from instruments.psu import psu_off, psu_on

            psu_on(setting, channel=channel)
            if settle_s:
                time.sleep(settle_s)
            try:
                return func(*args, **kwargs)
            finally:
                psu_off(channel=channel)

        return wrapper

    return decorator


def with_fg(setting, channel=None, settle_s: float = 0.0) -> Callable:
    """Drive a function-generator waveform for the duration of the step."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from instruments.function_generator import fg_off, fg_on

            fg_on(setting, channel=channel)
            if settle_s:
                time.sleep(settle_s)
            try:
                return func(*args, **kwargs)
            finally:
                fg_off(channel=channel)

        return wrapper

    return decorator


def with_fg_off(func: Callable) -> Callable:
    """Make sure the FG output is off after the step, however it ends."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from instruments.function_generator import fg_off

        try:
            return func(*args, **kwargs)
        finally:
            try:
                fg_off()
            except Exception as e:
                logger.warning(f"Could not turn the function generator off: {e}")

    return wrapper


def with_relay(*channels: int, settle_s: float = 0.05) -> Callable:
    """Close the named relay channels for the step, then open them again.

    Use it to route the DMM to a test point without repeating the
    open/close bookkeeping in every step.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from instruments.relay import RelayBank

            with RelayBank() as relay:
                relay.open_only(*channels)
                if settle_s:
                    time.sleep(settle_s)
                try:
                    return func(*args, **kwargs)
                finally:
                    relay.all_closed()

        return wrapper

    return decorator


def retry(attempts: int = 3, delay_s: float = 0.5, exceptions: tuple = (Exception,)) -> Callable:
    """Retry flaky hardware interactions. Re-raises the last exception if all attempts fail."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Optional[BaseException] = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_error = e
                    logger.warning(f"'{func.__name__}' attempt {attempt}/{attempts} failed: {e}")
                    if attempt < attempts:
                        time.sleep(delay_s)
            raise last_error  # type: ignore[misc]

        return wrapper

    return decorator


def timed(func: Callable) -> Callable:
    """Log how long a helper takes. Handy when hunting down slow steps."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.time()
        try:
            return func(*args, **kwargs)
        finally:
            logger.debug(f"'{func.__name__}' took {time.time() - start:.3f}s")

    return wrapper


def skip_if(condition: Callable[["TestRunner"], bool], reason: str = "") -> Callable:
    """Skip a step when a run-time condition holds (e.g. a board variant that lacks the feature)."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(runner: "TestRunner", *args: Any, **kwargs: Any) -> Any:
            if condition(runner):
                logger.warning(f"Skipping '{func.__name__}'{f': {reason}' if reason else ''}")
                return None
            return func(runner, *args, **kwargs)

        return wrapper

    return decorator


def requires_results(*result_ids: str) -> Callable:
    """Only run a step if earlier steps produced (and passed) the results it depends on."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(runner: "TestRunner", *args: Any, **kwargs: Any) -> Any:
            missing: Iterable[str] = [r for r in result_ids if not runner.has_result(r)]
            if missing:
                logger.warning(f"Skipping '{func.__name__}': prerequisites not met ({', '.join(missing)})")
                return None
            return func(runner, *args, **kwargs)

        return wrapper

    return decorator


def operator_prompt(message: str) -> Callable:
    """Pause for the operator before the step runs (fixture changes, jumper moves).

    Skipped automatically when simulating or running unattended, so a tester
    full of prompts still dry-runs end to end.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(runner: "TestRunner", *args: Any, **kwargs: Any) -> Any:
            from utils.operator import pause

            logger.warning(f"OPERATOR: {message}")
            pause()
            return func(runner, *args, **kwargs)

        return wrapper

    return decorator


def operator_confirm(message: str, default: bool = True) -> Callable:
    """Ask the operator to confirm something before the step runs.

    A "no" raises, so the step's results are recorded as failures by
    `test_step_result` rather than the run carrying on against a fixture that
    isn't set up. Auto-answers `default` when unattended.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(runner: "TestRunner", *args: Any, **kwargs: Any) -> Any:
            from utils.operator import confirm

            if not confirm(message, default=default):
                raise RuntimeError(f"Operator declined: {message}")
            return func(runner, *args, **kwargs)

        return wrapper

    return decorator
