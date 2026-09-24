"""The test runner: resolves steps to functions, runs them, collects results.

A run is driven entirely by data. `parts.toml` names the steps; the runner finds
the function with that name in the tester's modules, calls it with itself as the
only argument, and the step reports measurements back via `runner.add_result()`.
A step that raises does not stop the run - its results are recorded as failures
and the next step goes ahead (see `test_step_result` in core.decorators).

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import importlib
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config.paths import Logs, Results
from config.settings import set_simulate
from core.discovery import (
    get_test_result_details,
    get_test_steps,
    get_tester_module_paths,
    get_tester_version,
)
from core.logger import logger
from core.results import ERROR_RESULT, TestResult
from core.sinks import ResultSink, default_sinks, make_run_id

HEADER_WIDTH = 60


class TestRunner:
    """Carries the state of one run. Test steps receive it as their only argument."""

    def __init__(
        self,
        tester_name: str,
        test_steps: List[str],
        test_results: Dict[str, TestResult],
        part_number: str = "",
        serial_number: str = "",
        operator: str = "",
        tester_version: str = "",
        sinks: Optional[List[ResultSink]] = None,
        result_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        simulate: bool = False,
    ) -> None:
        self.tester_name = tester_name
        self.test_steps = test_steps
        self.test_results = test_results
        self.part_number = part_number
        self.serial_number = serial_number
        self.operator = operator
        self.tester_version = tester_version
        self.sinks = sinks if sinks is not None else default_sinks(Results.BASE)
        self.result_callback = result_callback
        self.simulate = simulate

        self.run_id = make_run_id()
        self.overall_result = True
        self.current_step = ""
        self.step_times: Dict[str, float] = {}
        self.started_at = ""
        self._step_start = time.time()
        self._result_start = time.time()

        # Scratch space for steps that need to pass data to a later step
        # (e.g. a serial number read in one step, checked in another).
        self.context: Dict[str, Any] = {}

    # ---------------------------------------------------------------- running

    def run_tests(self) -> bool:
        self.started_at = datetime.now().isoformat(timespec="seconds")
        module_paths = get_tester_module_paths(self.tester_name)

        logger.header(f"{self.tester_name} v{self.tester_version} | {self.part_number} | SN {self.serial_number}")
        if self.simulate:
            logger.warning("SIMULATE mode - no real hardware is being driven")
        logger.info(f"Steps: {', '.join(self.test_steps) if self.test_steps else '(none)'}")

        for test_step in self.test_steps:
            self.current_step = test_step
            self._step_start = time.time()
            self._result_start = time.time()

            logger.info("-" * HEADER_WIDTH)
            logger.info(f"Running step: {test_step}")

            module = self.get_module_for_test_step(module_paths, test_step)
            self.run_test_step(module, test_step)

            elapsed = round(time.time() - self._step_start, 2)
            self.step_times[test_step] = elapsed
            logger.info(f"Done step: {test_step} - took {elapsed:.2f}s")

        self.current_step = ""
        self._finish_missing_results()
        self.log_summary()
        self.publish()
        return self.overall_result

    def get_module_for_test_step(self, module_paths: List[str], test_step: str):
        for module_path in module_paths:
            try:
                module = importlib.import_module(module_path)
            except Exception as e:
                logger.error(f"Could not import '{module_path}': {e}")
                continue
            if hasattr(module, test_step):
                logger.debug(f"Found '{test_step}' in '{module_path}'")
                return module
        return None

    def run_test_step(self, module, test_step: str) -> None:
        if module is None:
            logger.error(f"Could not find test step '{test_step}' in any module of '{self.tester_name}'!")
            self.overall_result = False
            return

        func = getattr(module, test_step)
        try:
            func(self)
        except Exception as e:
            logger.error(f"Error during step '{test_step}' in '{module.__name__}': {e}", exc_info=True)
            self.overall_result = False

    # ---------------------------------------------------------------- results

    def add_result(self, test_result_id: str, result_value: Any) -> None:
        """Record a measurement. The limit spec decides pass/fail."""
        for key, result in self.test_results.items():
            if not key.startswith(test_result_id):
                continue
            if result.has_result:
                logger.debug(f"'{key}' already has a result, keeping the first one")
                return

            result.add_result(result_value)
            result.step = self.current_step
            result.duration_s = time.time() - self._result_start
            self._result_start = time.time()
            self.overall_result &= bool(result.passed)
            self.log_result(key)

            if self.result_callback:
                self.result_callback({"test_name": key, **result.as_dict()})
            return

        logger.warning(f"No result slot matches '{test_result_id}'. Declared slots: {list(self.test_results)}")

    def get_result(self, test_result_id: str) -> str:
        """Read back a measurement recorded earlier in this run."""
        for key, result in self.test_results.items():
            if key.startswith(test_result_id) and result.has_result:
                return result.measured
        logger.warning(f"No recorded result matches '{test_result_id}'")
        return ERROR_RESULT

    def has_result(self, test_result_id: str) -> bool:
        return any(k.startswith(test_result_id) and r.has_result for k, r in self.test_results.items())

    def log_result(self, key: str) -> None:
        result = self.test_results[key]
        units = result.test_detail.units
        verdict = "PASS" if result.passed else "FAIL"
        message = f"{verdict}: {key} = {result.measured}{units} | Expected: {result.test_detail.get_expected_value()}"
        (logger.info if result.passed else logger.error)(message)

    def _finish_missing_results(self) -> None:
        """Any declared result never reported is a failure, not a silent gap."""
        for key, result in self.test_results.items():
            if not result.has_result:
                logger.error(f"FAIL: {key} was never measured")
                result.passed = False
                result.error = "no result reported"
                self.overall_result = False

    def log_summary(self) -> None:
        logger.info("=" * HEADER_WIDTH)
        logger.info("All test results (testing complete):")

        passed_count = 0
        for key, result in self.test_results.items():
            if result.passed:
                passed_count += 1
            self.log_result(key)

        total = len(self.test_results)
        logger.info(f"Summary: {passed_count}/{total} passed, {total - passed_count} failed")
        verdict = "PASS" if self.overall_result else "FAIL"
        (logger.info if self.overall_result else logger.error)(f"Done testing: {verdict}")
        logger.info("=" * HEADER_WIDTH)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "tester": self.tester_name,
            "tester_version": self.tester_version,
            "part_number": self.part_number,
            "serial_number": self.serial_number,
            "operator": self.operator,
            "simulated": self.simulate,
            "passed": bool(self.overall_result),
            "steps": self.test_steps,
            "step_times_s": self.step_times,
            "results": {key: result.as_dict() for key, result in self.test_results.items()},
        }

    def publish(self) -> None:
        run = self.as_dict()
        for sink in self.sinks:
            try:
                sink.write(run)
            except Exception as e:
                logger.error(f"Result sink {type(sink).__name__} failed: {e}")


def create_test_runner(
    tester_name: str,
    part_number: str = "",
    serial_number: str = "",
    operator: str = "",
    steps: Optional[List[str]] = None,
    sinks: Optional[List[ResultSink]] = None,
    result_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    simulate: bool = False,
) -> TestRunner:
    test_steps = steps or get_test_steps(tester_name, part_number)
    test_results = get_test_result_details(tester_name, part_number)
    tester_version = get_tester_version(tester_name)

    logger.debug(f"Creating TestRunner for {tester_name} / {part_number} (v{tester_version})")

    return TestRunner(
        tester_name=tester_name,
        test_steps=test_steps,
        test_results=test_results,
        part_number=part_number,
        serial_number=serial_number,
        operator=operator,
        tester_version=tester_version,
        sinks=sinks,
        result_callback=result_callback,
        simulate=simulate,
    )


def run_test(
    tester_name: str,
    part_number: str,
    serial_number: str = "",
    operator: str = "",
    steps: Optional[List[str]] = None,
    sinks: Optional[List[ResultSink]] = None,
    result_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    simulate: bool = False,
    logs_dir: Optional[Path] = None,
) -> bool:
    """Run one part through one tester. Returns True if everything passed."""
    set_simulate(simulate)
    runner = create_test_runner(
        tester_name=tester_name,
        part_number=part_number,
        serial_number=serial_number,
        operator=operator,
        steps=steps,
        sinks=sinks,
        result_callback=result_callback,
        simulate=simulate,
    )

    logger.start_run_log(logs_dir or Logs.BASE, f"{tester_name}_{serial_number or 'noserial'}")
    try:
        return runner.run_tests()
    finally:
        logger.stop_run_log()
