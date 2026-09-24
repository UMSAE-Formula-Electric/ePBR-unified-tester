"""Talking to the DUT's serial console: send a command, parse the reply.

Three pieces work together:

  SerialCommand              the text to send, plus the parser for its reply
  BaseSerialCommandParser    a dataclass whose regex pulls fields out of the reply
  SerialManager              the connection, with prompt detection and timeouts

Declare commands and their parsers in your tester's config.py:

    @dataclass
    class LatchStatus(BaseSerialCommandParser):
        pattern = r"LATCH\\s+(?P<state>\\w+)\\s+CURRENT\\s+(?P<current_ma>-?\\d+)\\s*mA"
        state: str
        current_ma: str

    class SerialCommands:
        LATCH_STATUS = SerialCommand("latch status", LatchStatus)

then in a step:

    with SerialManager(SerialDevices.DUT) as ser:
        status = ser.send_command_and_parse(SerialCommands.LATCH_STATUS)
        runner.add_result("LB_LATCH_CURRENT", int(status.current_ma))

The regex groups map onto the dataclass fields in order, so parsing failures
surface as a clear ValueError instead of an IndexError three lines later.

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Dict, Generic, Optional, Type, TypeVar

import serial

from config.settings import Retries, Timeouts, instrument_config, is_simulated, simulation_config
from core.logger import logger
from core.results import ERROR_RESULT

SERIAL_ERROR_RESPONSE = -9999
COMMAND_TERMINATOR = "\r"
POLL_INTERVAL_S = 0.05
POST_WRITE_DELAY_S = 0.1

# Common console prompts. Add your firmware's here.
RE_PROMPT_ARROW = re.compile(rb"~>")
RE_PROMPT_SHELL = re.compile(rb".*:~[$#]\s*$")
RE_PROMPT_CHEVRON = re.compile(rb">\s*$")
RE_PROMPT_ANY_NEWLINE = re.compile(rb"\n")

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """Remove colour codes so a regex sees the text the human sees."""
    return ANSI_ESCAPE.sub("", text)


@dataclass
class BaseSerialCommandParser:
    """Subclass with a `pattern` and one field per capture group."""

    pattern: ClassVar[str]

    @classmethod
    def parse(cls, response: str) -> "BaseSerialCommandParser":
        match = re.search(cls.pattern, response, re.MULTILINE)
        if not match:
            raise ValueError(f"No match for {cls.__name__} in response: {response!r}")

        groups = match.groups()
        flds = fields(cls)

        if len(groups) != len(flds):
            raise ValueError(
                f"{cls.__name__}: pattern has {len(groups)} capture groups but the dataclass has "
                f"{len(flds)} fields ({', '.join(f.name for f in flds)})"
            )

        return cls(*groups)

    @classmethod
    def try_parse(cls, response: str) -> Optional["BaseSerialCommandParser"]:
        """Parse, or None if the reply doesn't match. Use when absence is a valid outcome."""
        try:
            return cls.parse(response)
        except ValueError:
            return None

    def as_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


T = TypeVar("T", bound=BaseSerialCommandParser)


class SerialCommand(Generic[T]):
    """A console command and the parser for its response."""

    def __init__(
        self,
        command_str: str,
        parser: Type[T] = BaseSerialCommandParser,  # type: ignore[assignment]
        separator: str = ":",
    ) -> None:
        self.command_str = command_str
        self.parser = parser
        self.separator = separator

    def with_args(self, *args: Any) -> "SerialCommand[T]":
        """Append arguments, e.g. SET_SN.with_args("EPBR-0042") -> 'sn:EPBR-0042'."""
        command = self.command_str
        for arg in args:
            command += self.separator + str(arg)
        return SerialCommand(command, self.parser, self.separator)

    def __repr__(self) -> str:
        return f"SerialCommand({self.command_str!r})"


class SerialDevice:
    """One addressable serial endpoint: where it is, how fast, what its prompt looks like."""

    def __init__(
        self,
        name: str,
        port: str = "",
        baudrate: int = 115200,
        prompt_regex: re.Pattern = RE_PROMPT_ARROW,
        config_key: str = "",
    ) -> None:
        self.name = name
        self.port = port
        self.baudrate = baudrate
        self.prompt_regex = prompt_regex
        self.config_key = config_key

    def resolve_port(self) -> str:
        """An explicit port wins; otherwise take it from station.toml (by COM name or USB id)."""
        if self.port:
            return self.port

        from utils.ports import resolve_port

        config = instrument_config(self.config_key or self.name)
        return resolve_port(config, self.config_key or self.name)

    def resolve_baudrate(self) -> int:
        config = instrument_config(self.config_key or self.name)
        return int(config.get("baudrate", self.baudrate))

    def __str__(self) -> str:
        return f"{self.name}({self.port or 'auto'}@{self.baudrate})"


class SerialDevices:
    """The serial endpoints on this station.

    Ports come from config/station.toml so they can differ per machine. Add one
    entry per board or console you talk to.
    """

    DUT = SerialDevice("dut_serial", baudrate=115200, prompt_regex=RE_PROMPT_ARROW, config_key="dut_serial")
    RELAY = SerialDevice("relay", baudrate=9600, prompt_regex=RE_PROMPT_ARROW, config_key="relay")


class SerialManager:
    """An open serial connection with command/response helpers.

    Always use it as a context manager so the port is released even when a step
    fails - a stuck-open COM port is the usual cause of a mysterious
    'Access is denied' on the next run.
    """

    def __init__(
        self,
        device: SerialDevice,
        timeout: Optional[float] = Timeouts.SERIAL_S,
        simulate: Optional[bool] = None,
    ) -> None:
        self.device = device
        self.timeout = timeout
        self.simulate = is_simulated() if simulate is None else simulate
        self.connection: Optional[serial.Serial] = None
        # In simulate mode, canned replies keyed by command text, taken from the
        # [<device>.simulation] table in station.toml. "*" is the fallback.
        # Assign to this dict directly to override them inside a single step.
        self.simulated_responses: Dict[str, str] = simulation_config(
            device.config_key or device.name
        )

    def __enter__(self) -> "SerialManager":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    # ------------------------------------------------------------- plumbing

    def open(self) -> None:
        if self.simulate:
            logger.debug(f"{self.device} simulated, no port opened")
            return
        if self.connection is None or not self.connection.is_open:
            self.connection = serial.Serial(
                port=self.device.resolve_port(),
                baudrate=self.device.resolve_baudrate(),
                timeout=self.timeout,
            )
            logger.debug(f"Opened {self.device}")

    def close(self) -> None:
        if self.connection is not None and self.connection.is_open:
            self.connection.close()
            logger.debug(f"Closed {self.device}")
        self.connection = None

    @property
    def is_open(self) -> bool:
        return self.simulate or (self.connection is not None and self.connection.is_open)

    def _require_open(self) -> serial.Serial:
        if self.connection is None or not self.connection.is_open:
            raise RuntimeError(f"{self.device} is not open. Use: with SerialManager(...) as ser:")
        return self.connection

    # ----------------------------------------------------------- raw access

    def write(self, data: bytes) -> None:
        """Write raw bytes - for binary protocols like the relay board."""
        if self.simulate:
            logger.debug(f"[SIM] {self.device} <- {data!r}")
            return
        connection = self._require_open()
        connection.write(data)
        connection.flush()
        logger.debug(f"Sent {data!r} to {self.device}")

    def read(self, num_bytes: int) -> str:
        if self.simulate:
            return ""
        connection = self._require_open()
        data = connection.read(num_bytes)
        return data.decode(errors="ignore")

    def readline(self) -> str:
        if self.simulate:
            return ""
        return self._require_open().readline().decode(errors="ignore")

    def read_all(self) -> str:
        """Everything sitting in the input buffer right now."""
        if self.simulate:
            return ""
        connection = self._require_open()
        if connection.in_waiting:
            return connection.read(connection.in_waiting).decode(errors="ignore")
        return ""

    def flush(self) -> None:
        if self.simulate:
            return
        connection = self._require_open()
        connection.reset_input_buffer()
        connection.reset_output_buffer()

    # ------------------------------------------------------ command/response

    def send_command(
        self,
        command: SerialCommand,
        timeout: float = Timeouts.SERIAL_S,
        wait_response: bool = True,
        log_response: bool = False,
        expected_string: Optional[str] = None,
    ) -> str:
        """Send a command and collect the reply.

        Reading stops at whichever comes first: `expected_string` appearing in
        the reply, the device's prompt regex matching, or `timeout`. The echoed
        command and any ANSI codes are stripped from what you get back.
        """
        if self.simulate:
            response = self.simulated_responses.get(
                command.command_str, self.simulated_responses.get("*", "")
            )
            logger.debug(f"[SIM] {self.device} '{command.command_str}' -> {response!r}")
            return response

        connection = self._require_open()
        self.flush()

        logger.debug(f"Sending command: '{command.command_str}'")
        connection.write((command.command_str + COMMAND_TERMINATOR).encode())
        connection.flush()
        time.sleep(POST_WRITE_DELAY_S)

        if not wait_response:
            return ""

        raw = ""
        stripped = ""
        start_time = time.time()
        finished = False

        while time.time() - start_time < timeout:
            if connection.in_waiting:
                raw += connection.read(connection.in_waiting).decode("utf-8", errors="ignore")
                stripped = strip_ansi(raw)

                if expected_string is not None:
                    if re.search(r"(?<!\w)" + re.escape(expected_string) + r"(?!\w)", stripped):
                        logger.debug(f"Found '{expected_string}' after {time.time() - start_time:.2f}s")
                        finished = True
                        break
                elif self.device.prompt_regex.search(stripped.encode("utf-8")):
                    finished = True
                    break

            time.sleep(POLL_INTERVAL_S)

        if not finished:
            logger.warning(f"Command '{command.command_str}' timed out after {timeout}s")

        # Drop the echoed command and normalise line endings.
        cleaned = stripped.replace("\r", "").replace(command.command_str, "", 1)
        response = cleaned.strip()

        if log_response:
            logger.debug(f"'{command.command_str}' response:\n{response}")

        self.flush()
        return response

    def send_command_and_parse(
        self,
        command: SerialCommand[T],
        timeout: float = Timeouts.SERIAL_S,
        log_response: bool = False,
        expected_string: Optional[str] = None,
    ) -> T:
        """Send a command and parse the reply with the command's parser.

        Raises ValueError if the reply doesn't match - which is usually what you
        want, because @test_step_result turns it into a recorded failure.
        """
        response = self.send_command(
            command, timeout=timeout, log_response=log_response, expected_string=expected_string
        )
        return command.parser.parse(response)  # type: ignore[return-value]

    def send_command_expect(
        self,
        command: SerialCommand,
        expected_string: str,
        timeout: float = Timeouts.SERIAL_S,
    ) -> bool:
        """True if `expected_string` shows up in the reply before the timeout."""
        response = self.send_command(command, timeout=timeout, expected_string=expected_string)
        return bool(re.search(r"(?<!\w)" + re.escape(expected_string) + r"(?!\w)", response))

    def wait_for(self, pattern: str, timeout: float = Timeouts.SERIAL_S) -> Optional[re.Match]:
        """Watch the stream for a regex without sending anything.

        Use it for unprompted output - a boot banner, a fault message.
        """
        if self.simulate:
            return None

        connection = self._require_open()
        buffer = ""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if connection.in_waiting:
                buffer += connection.read(connection.in_waiting).decode("utf-8", errors="ignore")
                match = re.search(pattern, strip_ansi(buffer))
                if match:
                    return match
            time.sleep(POLL_INTERVAL_S)

        logger.warning(f"Timed out waiting for /{pattern}/ on {self.device}")
        return None

    def read_until_prompt(self, timeout: float = Timeouts.SERIAL_S) -> str:
        """Drain the stream until the device's prompt appears. Good after a reset."""
        if self.simulate:
            return ""

        connection = self._require_open()
        buffer = b""
        start_time = time.time()

        while time.time() - start_time < timeout:
            chunk = connection.read(1)
            if not chunk:
                continue
            buffer += chunk
            if self.device.prompt_regex.search(strip_ansi(buffer.decode(errors="ignore")).encode("utf-8")):
                break

        return strip_ansi(buffer.decode(errors="ignore"))


# --------------------------------------------------------------------------
# One-shot helpers: open, send, close. Convenient for a single reading;
# hold a SerialManager yourself when a step sends several commands.
# --------------------------------------------------------------------------


def send_command_get_string(
    command: SerialCommand,
    device: SerialDevice,
    timeout: float = Timeouts.SERIAL_S,
    retries: int = Retries.SERIAL,
) -> str:
    """Retry until the device says something. Empty string if it never does."""
    for attempt in range(1, retries + 1):
        with SerialManager(device) as ser:
            result = ser.send_command(command, timeout=timeout)
        if result:
            return result
        logger.warning(f"Empty response to '{command.command_str}' (attempt {attempt}/{retries})")

    logger.error(f"No valid response to '{command.command_str}' after {retries} attempts")
    return ""


def send_command_get_int(
    command: SerialCommand,
    device: SerialDevice,
    timeout: float = Timeouts.SERIAL_S,
    retries: int = Retries.SERIAL,
) -> int:
    """Retry until the reply parses as an int, else SERIAL_ERROR_RESPONSE."""
    for attempt in range(1, retries + 1):
        with SerialManager(device) as ser:
            result = ser.send_command(command, timeout=timeout)
        try:
            return int(result.strip())
        except (ValueError, AttributeError):
            logger.warning(f"Non-integer response {result!r} (attempt {attempt}/{retries})")

    logger.error(f"No valid integer response to '{command.command_str}' after {retries} attempts")
    return SERIAL_ERROR_RESPONSE


def send_command_get_float(
    command: SerialCommand,
    device: SerialDevice,
    timeout: float = Timeouts.SERIAL_S,
    retries: int = Retries.SERIAL,
) -> float:
    for attempt in range(1, retries + 1):
        with SerialManager(device) as ser:
            result = ser.send_command(command, timeout=timeout)
        try:
            return float(result.strip())
        except (ValueError, AttributeError):
            logger.warning(f"Non-float response {result!r} (attempt {attempt}/{retries})")

    logger.error(f"No valid float response to '{command.command_str}' after {retries} attempts")
    return float(ERROR_RESULT)
