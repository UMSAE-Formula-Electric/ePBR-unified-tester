"""Framework core: logging, result assertion, the runner and its decorators."""

from core.decorators import (
    operator_prompt,
    requires_results,
    retry,
    skip_if,
    test_step_result,
    timed,
    with_fg,
    with_fg_off,
    with_psu,
    with_relay,
)
from core.logger import logger
from core.results import DEFAULT_RESULT, ERROR_RESULT, ResultDetail, TestResult, ValidationType
from core.runner import TestRunner, create_test_runner, run_test

__all__ = [
    "logger",
    "TestRunner",
    "create_test_runner",
    "run_test",
    "ResultDetail",
    "TestResult",
    "ValidationType",
    "DEFAULT_RESULT",
    "ERROR_RESULT",
    "test_step_result",
    "with_psu",
    "with_fg",
    "with_fg_off",
    "with_relay",
    "retry",
    "timed",
    "skip_if",
    "requires_results",
    "operator_prompt",
]
