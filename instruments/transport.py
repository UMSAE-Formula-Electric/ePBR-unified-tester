"""How SCPI commands physically reach an instrument.

Instrument drivers (PSU, FG, DMM) only ever call `write()` and `query()`. This
module supplies three implementations of that pair:

    VisaTransport    - USB-TMC / GPIB / TCPIP via pyvisa
    SerialTransport  - SCPI text over a COM port via pyserial
    SimulatedTransport - answers plausibly, touches nothing

Because the choice is config-driven, moving an instrument from USB-TMC to RS-232
is a one-line edit in config/station.toml, not a driver rewrite.

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional, Protocol

from config.settings import Timeouts, is_simulated, simulation_config
from core.logger import logger

SCPI_TERMINATOR = "\n"
DEFAULT_READ_DELAY_S = 0.05


class Transport(Protocol):
    """The whole interface an instrument driver depends on."""

    def open(self) -> "Transport": ...
    def close(self) -> None: ...
    def write(self, command: str) -> None: ...
    def query(self, command: str) -> str: ...


class TransportError(RuntimeError):
    pass


class VisaTransport:
    """pyvisa-backed transport for USB-TMC / GPIB / TCPIP instruments."""

    def __init__(
        self,
        resource: str = "",
        resource_regex: str = "",
        timeout_s: float = Timeouts.SCPI_S,
        read_delay_s: float = DEFAULT_READ_DELAY_S,
        name: str = "visa",
    ) -> None:
        self.resource = resource
        self.resource_regex = resource_regex
        self.timeout_s = timeout_s
        self.read_delay_s = read_delay_s
        self.name = name
        self.rm = None
        self.device = None

    def _discover(self) -> str:
        if self.resource:
            return self.resource

        resources = self.rm.list_resources()  # type: ignore[union-attr]
        if not resources:
            raise TransportError(
                f"No VISA resources found for '{self.name}'. Check the USB cable and that the "
                f"instrument is in remote/USB-TMC mode."
            )

        if self.resource_regex:
            matching = [r for r in resources if re.fullmatch(self.resource_regex, r)]
            if not matching:
                raise TransportError(
                    f"No VISA resource for '{self.name}' matches /{self.resource_regex}/. Saw: {list(resources)}"
                )
            resources = matching

        if len(resources) > 1:
            logger.warning(
                f"{len(resources)} VISA resources match '{self.name}': {list(resources)}. "
                f"Using the first. Pin it down with visa_resource in config/station.toml."
            )

        logger.debug(f"Discovered VISA resource for '{self.name}': {resources[0]}")
        return resources[0]

    def open(self) -> "VisaTransport":
        import pyvisa

        if self.device is not None:
            return self  # already open; opening twice would leak the handle

        self.rm = pyvisa.ResourceManager("@py")
        resource = self._discover()
        self.device = self.rm.open_resource(resource)
        self.device.timeout = int(self.timeout_s * 1000)  # pyvisa wants ms
        return self

    def close(self) -> None:
        try:
            if self.device is not None:
                self.device.close()
        finally:
            if self.rm is not None:
                self.rm.close()
            self.device = None
            self.rm = None

    def write(self, command: str) -> None:
        if self.device is None:
            raise TransportError(f"'{self.name}' transport is not open")
        logger.debug(f"[{self.name}] -> {command}")
        self.device.write(command)

    def query(self, command: str) -> str:
        if self.device is None:
            raise TransportError(f"'{self.name}' transport is not open")
        logger.debug(f"[{self.name}] -> {command}")
        time.sleep(self.read_delay_s)
        response = self.device.query(command).strip()
        logger.debug(f"[{self.name}] <- {response}")
        return response


class SerialTransport:
    """SCPI text over a COM port. Used for instruments on a USB virtual COM port."""

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout_s: float = Timeouts.SCPI_S,
        read_delay_s: float = DEFAULT_READ_DELAY_S,
        terminator: str = SCPI_TERMINATOR,
        name: str = "serial",
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.read_delay_s = read_delay_s
        self.terminator = terminator
        self.name = name
        self.connection = None

    def open(self) -> "SerialTransport":
        import serial

        if self.connection is not None and self.connection.is_open:
            return self  # already open; a second open on the same COM port is refused

        self.connection = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=self.timeout_s)
        logger.debug(f"Opened {self.name} on {self.port} @ {self.baudrate}")
        return self

    def close(self) -> None:
        if self.connection is not None and self.connection.is_open:
            self.connection.close()
        self.connection = None

    def _require_open(self):
        if self.connection is None or not self.connection.is_open:
            raise TransportError(f"'{self.name}' transport is not open")
        return self.connection

    def write(self, command: str) -> None:
        connection = self._require_open()
        logger.debug(f"[{self.name}] -> {command}")
        connection.reset_input_buffer()
        connection.write((command + self.terminator).encode())
        connection.flush()

    def query(self, command: str) -> str:
        connection = self._require_open()
        self.write(command)
        time.sleep(self.read_delay_s)
        response = connection.readline().decode(errors="ignore").strip()
        logger.debug(f"[{self.name}] <- {response}")
        if not response:
            raise TransportError(f"'{self.name}' did not answer '{command}' within {self.timeout_s}s")
        return response


class SimulatedTransport:
    """Stands in for hardware so a tester can be written and dry-run on any PC.

    Answers `*IDN?` and any query ending in '?' with something parseable. Supply
    `responses` to pin specific commands to specific answers in a test fixture.
    """

    # A write of FUNC "VOLT:DC" puts a DMM into DC-volts mode, and a later bare
    # READ? means something different because of it. Tracking that lets the
    # simulation answer READ? per function instead of returning one value for
    # every measurement the tester takes.
    MODE_PATTERN = re.compile(r'FUNC\w*\s+"?([A-Z:]+)"?', re.IGNORECASE)
    MODE_SEPARATOR = "@"

    def __init__(self, name: str = "sim", responses: Optional[Dict[str, str]] = None) -> None:
        self.name = name
        self.responses = responses or {}
        self.history: list[str] = []
        self.mode: str = ""

    def open(self) -> "SimulatedTransport":
        logger.debug(f"[{self.name}] simulated transport open")
        return self

    def close(self) -> None:
        pass

    def write(self, command: str) -> None:
        self.history.append(command)
        match = self.MODE_PATTERN.search(command)
        if match:
            self.mode = match.group(1).upper()
            logger.debug(f"[{self.name}:SIM] mode is now {self.mode}")
        logger.debug(f"[{self.name}:SIM] -> {command}")

    def query(self, command: str) -> str:
        self.history.append(command)
        # "READ?@RES" wins over a plain "READ?" while the instrument is in
        # resistance mode, so one simulated DMM can serve every measurement.
        response = None
        if self.mode:
            response = self.responses.get(f"{command}{self.MODE_SEPARATOR}{self.mode}")
        if response is None:
            response = self.responses.get(command)
        if response is None:
            response = self.responses.get("*")
        if response is None:
            if "IDN" in command.upper():
                response = f"SIMULATED,{self.name},0,0.0"
            else:
                response = "0.0"
        logger.debug(f"[{self.name}:SIM] -> {command} <- {response}")
        return response


def build_transport(config: Dict[str, Any], name: str, simulate: Optional[bool] = None) -> Transport:
    """Make the transport a station.toml block describes.

    `simulate` defaults to the SIMULATE env flag, so one switch puts the whole
    framework into dry-run.
    """
    if simulate is None:
        simulate = is_simulated()

    if simulate:
        return SimulatedTransport(name=name, responses=simulation_config(name))

    kind = str(config.get("transport", "serial")).lower()
    timeout_s = float(config.get("timeout_s", Timeouts.SCPI_S))

    if kind == "visa":
        return VisaTransport(
            resource=config.get("visa_resource", ""),
            resource_regex=config.get("visa_resource_regex", ""),
            timeout_s=timeout_s,
            name=name,
        )

    if kind == "serial":
        from utils.ports import resolve_port

        return SerialTransport(
            port=resolve_port(config, name),
            baudrate=int(config.get("baudrate", 9600)),
            timeout_s=timeout_s,
            name=name,
        )

    raise TransportError(f"Unknown transport '{kind}' for '{name}'. Use 'visa' or 'serial'.")
