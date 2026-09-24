"""Result assertion: limits declared in TOML, measurements validated against them.

A tester declares every measurement it can produce in `result_details.toml`:

    ["LB_COIL_RESISTANCE"]
    validation_type = "range"
    units = "ohm"
    min = 8.0
    max = 12.0

At runtime a test step calls `runner.add_result("LB_COIL_RESISTANCE", 9.7)` and
the framework decides PASS/FAIL. Steps never assert for themselves, so the limits
live in one reviewable file instead of being scattered through the test code.

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, Optional

DEFAULT_RESULT = -9999
ERROR_RESULT = "-9999"
DECIMAL_PLACES = 3

TRUE = "true"
FALSE = "false"


class ValidationType(Enum):
    RANGE = "range"  # min <= measured <= max
    ABOVE = "above"  # measured >= expected_value
    BELOW = "below"  # measured <= expected_value
    TOLERANCE = "tolerance"  # |measured - expected_value| <= tolerance
    STRING = "string"  # measured == expected_value (exact)
    REGEX = "regex"  # re.search(expected_value, measured)
    BOOLEAN = "boolean"  # measured truthiness == expected_value


class ResultDetail:
    """The limit spec for a single measurement, loaded from result_details.toml."""

    def __init__(
        self,
        validation_type: ValidationType = ValidationType.RANGE,
        units: str = "",
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        expected_value: Any = None,
        tolerance: Optional[float] = None,
        description: str = "",
    ) -> None:
        self.validation_type = validation_type
        self.units = units
        self.min_value = min_value
        self.max_value = max_value
        self.expected_value = expected_value
        self.tolerance = tolerance
        self.description = description

    @classmethod
    def from_dict(cls, details: Dict[str, Any]) -> "ResultDetail":
        raw_type = details.get("validation_type", ValidationType.STRING.value)
        try:
            validation_type = ValidationType(raw_type)
        except ValueError:
            valid = ", ".join(v.value for v in ValidationType)
            raise ValueError(f"Unknown validation_type '{raw_type}'. Valid options: {valid}")

        return cls(
            validation_type=validation_type,
            units=details.get("units", ""),
            min_value=details.get("min"),
            max_value=details.get("max"),
            expected_value=details.get("expected_value"),
            tolerance=details.get("tolerance"),
            description=details.get("desc", details.get("description", "")),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "validation_type": self.validation_type.value,
            "units": self.units,
            "min": self.min_value,
            "max": self.max_value,
            "expected_value": self.expected_value,
            "tolerance": self.tolerance,
            "description": self.description,
        }

    @staticmethod
    def _to_float(value: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Measured value '{value}' cannot be converted to a float for validation.")

    def _require(self, **fields: Any) -> None:
        missing = [name for name, value in fields.items() if value is None]
        if missing:
            raise ValueError(
                f"{', '.join(missing)} must be set for {self.validation_type.value.upper()} validation."
            )

    def validate(self, measured_value: str) -> bool:
        vt = self.validation_type

        if vt is ValidationType.RANGE:
            self._require(min=self.min_value, max=self.max_value)
            return self.min_value <= self._to_float(measured_value) <= self.max_value

        if vt is ValidationType.ABOVE:
            self._require(expected_value=self.expected_value)
            return self._to_float(measured_value) >= float(self.expected_value)

        if vt is ValidationType.BELOW:
            self._require(expected_value=self.expected_value)
            return self._to_float(measured_value) <= float(self.expected_value)

        if vt is ValidationType.TOLERANCE:
            self._require(expected_value=self.expected_value, tolerance=self.tolerance)
            return abs(self._to_float(measured_value) - float(self.expected_value)) <= float(self.tolerance)

        if vt is ValidationType.STRING:
            self._require(expected_value=self.expected_value)
            return measured_value == str(self.expected_value)

        if vt is ValidationType.REGEX:
            self._require(expected_value=self.expected_value)
            return bool(re.search(str(self.expected_value), measured_value))

        if vt is ValidationType.BOOLEAN:
            expected = self.expected_value
            if expected is None:
                expected = True
            expected_str = TRUE if bool(expected) else FALSE
            return measured_value.strip().lower() == expected_str

        raise ValueError(f"Unknown validation type: {vt}")

    def get_expected_value(self) -> str:
        """Human-readable limit, shown in logs and written to result files."""
        vt = self.validation_type
        u = self.units

        if vt is ValidationType.RANGE:
            return f"{self.min_value}{u} - {self.max_value}{u}"
        if vt is ValidationType.ABOVE:
            return f">={self.expected_value}{u}"
        if vt is ValidationType.BELOW:
            return f"<={self.expected_value}{u}"
        if vt is ValidationType.TOLERANCE:
            return f"{self.expected_value}{u} +/-{self.tolerance}{u}"
        if vt is ValidationType.REGEX:
            return f"matches /{self.expected_value}/"
        if vt is ValidationType.BOOLEAN:
            expected = True if self.expected_value is None else bool(self.expected_value)
            return TRUE if expected else FALSE
        if vt is ValidationType.STRING:
            return f"{self.expected_value}"
        return "???"


class TestResult:
    """One measurement slot: its limit spec, the measured value, and pass/fail."""

    def __init__(self, result_detail: ResultDetail, passed: Optional[bool] = None) -> None:
        self.measured = "-"
        self.test_detail = result_detail
        self.passed = passed
        self.has_result = False
        self.error: str = ""
        self.duration_s: float = 0.0
        self.step: str = ""

    def validate(self) -> None:
        try:
            self.passed = self.test_detail.validate(self.measured)
        except ValueError as e:
            self.passed = False
            self.error = str(e)

    def add_result(self, value: Any) -> None:
        self.has_result = True
        if isinstance(value, bool):
            self.measured = TRUE if value else FALSE
        elif isinstance(value, float):
            self.measured = str(round(value, DECIMAL_PLACES))
        else:
            self.measured = str(value)
        self.validate()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "measured": self.measured,
            "expected": self.test_detail.get_expected_value(),
            "units": self.test_detail.units,
            "validation_type": self.test_detail.validation_type.value,
            "passed": bool(self.passed),
            "has_result": self.has_result,
            "duration_s": round(self.duration_s, 3),
            "description": self.test_detail.description,
            "error": self.error,
        }
