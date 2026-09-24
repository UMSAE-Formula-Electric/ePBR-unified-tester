"""R221A08 8-channel relay bank (serial, 9600 baud).

Same board as the work tester. The protocol is a fixed 8-byte frame:

    55 56 00 00 00 <channel> <operation> <checksum>

where checksum is the low byte of the sum of the preceding seven. The original
framework hard-coded all 48 frames as hex literals; here they are generated, so
adding a channel or an operation is a one-line change and there are no typos to
hunt down in a table.

A note on the vendor's naming, kept here so the frames match the datasheet:
    OPEN   energises the relay, connecting COM to NO
    CLOSE  de-energises it, connecting COM to NC (the resting state)

Typical use is routing the DMM around the board:

    with RelayBank() as relay:
        relay.open_only(RelayChannel.COIL_SENSE)   # exactly one path live
        ...

or through the decorator, which handles the cleanup:

    @with_relay(RelayChannel.COIL_SENSE)
    def MY_STEP(runner): ...

Author: Cedric Caparas
Date:   2026-09-24
"""

from __future__ import annotations

import time
from enum import IntEnum
from typing import Dict, Iterable, Optional

from config.settings import instrument_config, is_simulated
from core.logger import logger

FRAME_HEADER = bytes([0x55, 0x56, 0x00, 0x00, 0x00])
MOMENTARY_DURATION_S = 0.2  # the board's own fixed pulse width
DEFAULT_SETTLE_S = 0.05


class Operation(IntEnum):
    READ = 0x00
    OPEN = 0x01  # energise: COM -> NO
    CLOSE = 0x02  # de-energise: COM -> NC
    TOGGLE = 0x03
    MOMENTARY = 0x04  # closes for ~200 ms, then opens
    INTERLOCK = 0x05  # energise this channel only, release all others


def build_frame(channel: int, operation: Operation) -> bytes:
    """The 8-byte command frame for one channel/operation pair."""
    if not 1 <= channel <= 8:
        raise ValueError(f"Relay channel must be 1-8, got {channel}")
    body = FRAME_HEADER + bytes([channel, int(operation)])
    checksum = sum(body) & 0xFF
    return body + bytes([checksum])


class Commands:
    """Pre-built frames, addressable as Commands.OPEN[3].

    Kept for parity with the work framework's Commands.OPEN.THREE style; you can
    also just call the RelayBank methods, which is usually clearer.
    """

    READ: Dict[int, bytes] = {ch: build_frame(ch, Operation.READ) for ch in range(1, 9)}
    OPEN: Dict[int, bytes] = {ch: build_frame(ch, Operation.OPEN) for ch in range(1, 9)}
    CLOSE: Dict[int, bytes] = {ch: build_frame(ch, Operation.CLOSE) for ch in range(1, 9)}
    TOGGLE: Dict[int, bytes] = {ch: build_frame(ch, Operation.TOGGLE) for ch in range(1, 9)}
    MOMENTARY: Dict[int, bytes] = {ch: build_frame(ch, Operation.MOMENTARY) for ch in range(1, 9)}
    INTERLOCK: Dict[int, bytes] = {ch: build_frame(ch, Operation.INTERLOCK) for ch in range(1, 9)}


class RelayBank:
    """Context-managed relay bank. All channels are released on exit."""

    def __init__(
        self,
        port: Optional[str] = None,
        release_on_exit: bool = True,
        simulate: Optional[bool] = None,
    ) -> None:
        self.config = instrument_config("relay")
        self.simulate = is_simulated() if simulate is None else simulate
        self.port = port
        self.baudrate = int(self.config.get("baudrate", 9600))
        self.timeout_s = float(self.config.get("timeout_s", 2.0))
        self.channel_count = int(self.config.get("channels", 8))
        self.release_on_exit = release_on_exit
        self.connection = None
        self.state: Dict[int, bool] = {ch: False for ch in range(1, self.channel_count + 1)}

    def __enter__(self) -> "RelayBank":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if self.release_on_exit:
                self.all_closed()
        except Exception as e:
            logger.error(f"Could not release the relay bank on exit: {e}")
        finally:
            self.close()

    # ------------------------------------------------------------- plumbing

    def open(self) -> None:
        if self.simulate:
            logger.debug("Relay bank: simulated, no port opened")
            return

        import serial

        from utils.ports import resolve_port

        port = self.port or resolve_port(self.config, "relay")
        self.connection = serial.Serial(port=port, baudrate=self.baudrate, timeout=self.timeout_s)
        logger.debug(f"Relay bank open on {port} @ {self.baudrate}")

    def close(self) -> None:
        if self.connection is not None and self.connection.is_open:
            self.connection.close()
        self.connection = None

    def send(self, channel: int, operation: Operation) -> None:
        frame = build_frame(channel, operation)
        logger.debug(f"Relay CH{channel} {operation.name} -> {frame.hex(' ').upper()}")

        if self.simulate:
            self._track(channel, operation)
            return

        if self.connection is None or not self.connection.is_open:
            raise RuntimeError("Relay bank is not open. Use it as a context manager: with RelayBank() as relay:")

        self.connection.write(frame)
        self.connection.flush()
        self._track(channel, operation)

    def _track(self, channel: int, operation: Operation) -> None:
        """Keep a local picture of the bank so `state` is meaningful in logs."""
        if operation is Operation.OPEN:
            self.state[channel] = True
        elif operation in {Operation.CLOSE, Operation.MOMENTARY}:
            self.state[channel] = False
        elif operation is Operation.TOGGLE:
            self.state[channel] = not self.state.get(channel, False)
        elif operation is Operation.INTERLOCK:
            self.state = {ch: ch == channel for ch in self.state}

    # -------------------------------------------------------------- control

    def open_channel(self, channel: int, settle_s: float = DEFAULT_SETTLE_S) -> None:
        """Energise one channel (COM -> NO), leaving the others as they are."""
        self.send(channel, Operation.OPEN)
        if settle_s:
            time.sleep(settle_s)

    def close_channel(self, channel: int, settle_s: float = DEFAULT_SETTLE_S) -> None:
        """De-energise one channel (COM -> NC)."""
        self.send(channel, Operation.CLOSE)
        if settle_s:
            time.sleep(settle_s)

    def toggle_channel(self, channel: int) -> None:
        self.send(channel, Operation.TOGGLE)

    def momentary(self, channel: int, wait: bool = True) -> None:
        """Fire the board's built-in ~200 ms pulse. Good for a momentary-switch input."""
        self.send(channel, Operation.MOMENTARY)
        if wait:
            time.sleep(MOMENTARY_DURATION_S)

    def pulse(self, channel: int, duration_s: float) -> None:
        """Hold a channel for an arbitrary duration, then release it."""
        self.open_channel(channel, settle_s=0)
        time.sleep(duration_s)
        self.close_channel(channel, settle_s=0)

    def interlock(self, channel: int, settle_s: float = DEFAULT_SETTLE_S) -> None:
        """Energise exactly this channel using the board's own interlock mode.

        One command instead of eight, and the bank is never briefly in a state
        where two paths are live - which matters when the channels select where
        the DMM is connected.
        """
        self.send(channel, Operation.INTERLOCK)
        if settle_s:
            time.sleep(settle_s)

    def open_only(self, *channels: int, settle_s: float = DEFAULT_SETTLE_S) -> None:
        """Energise exactly the channels given and release every other one.

        With a single channel this uses the board's interlock mode.
        """
        wanted = {int(ch) for ch in channels}

        if len(wanted) == 1:
            self.interlock(next(iter(wanted)), settle_s=settle_s)
            return

        for channel in range(1, self.channel_count + 1):
            if channel in wanted:
                self.send(channel, Operation.OPEN)
            else:
                self.send(channel, Operation.CLOSE)
        if settle_s:
            time.sleep(settle_s)

    def all_open(self) -> None:
        for channel in range(1, self.channel_count + 1):
            self.send(channel, Operation.OPEN)

    def all_closed(self) -> None:
        """The safe resting state: every relay de-energised."""
        for channel in range(1, self.channel_count + 1):
            self.send(channel, Operation.CLOSE)

    def set_channels(self, channels: Iterable[int], energised: bool = True) -> None:
        for channel in channels:
            self.send(channel, Operation.OPEN if energised else Operation.CLOSE)


class RelayChannel(IntEnum):
    """Name the channels for your fixture.

    Rename these to match how your fixture is actually wired - the point is that
    steps read as `relay.open_only(RelayChannel.COIL_SENSE)` rather than
    `relay.open_only(3)`. Unused by the equipment_tests tester, which needs
    no relay bank.
    """

    COIL_DRIVE = 1
    COIL_SENSE = 2
    LATCH_SENSE = 3
    SUPPLY_SENSE = 4
    SPARE_5 = 5
    SPARE_6 = 6
    SPARE_7 = 7
    SPARE_8 = 8


def main() -> None:
    """Smoke test: python -m instruments.relay - clicks each channel in turn."""
    with RelayBank() as relay:
        for channel in range(1, relay.channel_count + 1):
            logger.info(f"Channel {channel} on")
            relay.open_channel(channel)
            time.sleep(0.3)
            logger.info(f"Channel {channel} off")
            relay.close_channel(channel)


if __name__ == "__main__":
    main()
