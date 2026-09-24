"""String helpers, mostly for turning serial-console text into numbers safely.

A failed cast returns ERROR_RESULT (-9999) rather than raising, so a garbled
reply is recorded as an out-of-limits measurement instead of an exception.

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import re
from typing import List, Optional

from core.results import ERROR_RESULT

NUMBER_PATTERN = r"-?\d+(?:\.\d+)?"


def pretty(string: str) -> str:
    """LB_COIL_RESISTANCE -> 'Lb Coil Resistance', for display."""
    return string.replace("_", " ").title() if string else ""


def is_int(string: str) -> bool:
    try:
        int(str(string).strip())
        return True
    except (ValueError, TypeError):
        return False


def cast_int(string: str) -> int:
    return int(str(string).strip()) if is_int(string) else int(ERROR_RESULT)


def is_float(string: str) -> bool:
    try:
        float(str(string).strip())
        return True
    except (ValueError, TypeError):
        return False


def cast_float(string: str) -> float:
    return float(str(string).strip()) if is_float(string) else float(ERROR_RESULT)


def extract_number(text: str, pattern: str = NUMBER_PATTERN) -> float:
    """First number in a string. 'Vbat 12.34 V' -> 12.34"""
    match = re.search(pattern, text)
    return float(match.group()) if match else float(ERROR_RESULT)


def extract_numbers(text: str, pattern: str = NUMBER_PATTERN) -> List[float]:
    """Every number in a string, in order."""
    return [float(m) for m in re.findall(pattern, text)]


def extract_group(text: str, pattern: str, group: int | str = 1) -> Optional[str]:
    """One named or numbered capture group, or None if the pattern misses."""
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(group) if match else None


def contains_token(text: str, token: str) -> bool:
    """Whole-word match, so looking for 'OK' doesn't hit 'NOTOK'."""
    return bool(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", text))


def normalise(text: str) -> str:
    """Collapse runs of whitespace - makes console output easier to regex."""
    return re.sub(r"\s+", " ", text).strip()
