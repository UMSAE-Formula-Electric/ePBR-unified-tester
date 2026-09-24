"""Asking the operator things, backed by questionary.

Used for the parts of a test a program can't do on its own: confirming a cable
is connected, asking which resistor is in the fixture, choosing a variant.

Every prompt here is safe to call from an unattended run. When the framework is
in simulate mode, or when there's no terminal to prompt on (output piped to a
file, run from a script, run from CI), the prompt is skipped and the default is
used, with a line in the log saying so. That means a tester full of operator
prompts still dry-runs end to end without hanging.

    from utils.operator import ask_float, confirm

    if not confirm("Connect FG CH1 to the DMM input. Ready?"):
        return
    nominal = ask_float("Resistor value in ohms", default=10_000.0, minimum=0.0)

Ctrl+C at a prompt raises KeyboardInterrupt, which stops the run rather than
being recorded as a test failure - an operator walking away is not a bad board.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

import questionary

from config.settings import is_simulated
from core.logger import logger


def interactive() -> bool:
    """Can we actually prompt right now?"""
    if is_simulated():
        return False
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _auto(message: str, answer) -> None:
    logger.warning(f"[auto-answered] {message} -> {answer}")


def confirm(message: str, default: bool = True) -> bool:
    """Yes/no. Returns `default` when unattended."""
    if not interactive():
        _auto(message, default)
        return default
    return bool(questionary.confirm(message, default=default).unsafe_ask())


def pause(message: str = "Press any key to continue") -> None:
    """Wait for the operator. Returns immediately when unattended."""
    if not interactive():
        _auto(message, "continue")
        return
    questionary.press_any_key_to_continue(f"{message}...").unsafe_ask()


def ask_text(message: str, default: str = "") -> str:
    if not interactive():
        _auto(message, default)
        return default
    return str(questionary.text(message, default=default).unsafe_ask())


def ask_float(
    message: str,
    default: Optional[float] = None,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    """A number, re-asked until it parses and fits the range."""
    if not interactive():
        value = 0.0 if default is None else default
        _auto(message, value)
        return value

    def validate(text: str):
        try:
            value = float(text)
        except ValueError:
            return "Enter a number"
        if minimum is not None and value < minimum:
            return f"Must be at least {minimum}"
        if maximum is not None and value > maximum:
            return f"Must be at most {maximum}"
        return True

    answer = questionary.text(
        message,
        default="" if default is None else str(default),
        validate=validate,
    ).unsafe_ask()
    return float(answer)


def select(message: str, choices: Sequence[str], default: Optional[str] = None) -> str:
    """Pick one of a list. Returns the default (or the first choice) when unattended."""
    if not choices:
        raise ValueError("select() needs at least one choice")

    if not interactive():
        answer = default if default in choices else choices[0]
        _auto(message, answer)
        return answer

    return str(
        questionary.select(message, choices=list(choices), default=default).unsafe_ask()
    )


def checkbox(message: str, choices: Sequence[str], default: Optional[Sequence[str]] = None) -> list:
    """Pick any number from a list. Returns `default` (or nothing) when unattended."""
    if not interactive():
        answer = list(default or [])
        _auto(message, answer)
        return answer

    return list(questionary.checkbox(message, choices=list(choices)).unsafe_ask() or [])


def instruct(message: str) -> None:
    """Tell the operator to do something, and wait until they say it's done.

    Raises if they say they couldn't, so the step fails with a clear reason
    rather than measuring a fixture that isn't set up.
    """
    if not confirm(message, default=True):
        raise RuntimeError(f"Operator did not complete: {message}")
