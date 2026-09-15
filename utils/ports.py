"""Finding serial ports on Windows without hard-coding COM numbers.

Windows assigns COM numbers per USB device *per port*, so moving a cable to a
different jack renames it and every hard-coded "COM5" in your config breaks.
Address devices by USB VID/PID (and serial number if you have two of the same
adapter) and let this module resolve the port at connect time.

    python main.py ports     # list everything plugged in, with VID/PID
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from serial.tools import list_ports

from core.logger import logger


def _as_int(value: Any) -> Optional[int]:
    """Accept 0x1A86, '0x1A86', '1A86' or 6790 and return an int."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    try:
        return int(text, 16) if text.startswith("0x") else int(text, 16 if not text.isdigit() else 10)
    except ValueError:
        logger.warning(f"Could not read '{value}' as a USB id")
        return None


def list_serial_ports() -> List[Dict[str, Any]]:
    """Every serial port the OS can see, as plain dicts."""
    ports = []
    for p in list_ports.comports():
        ports.append(
            {
                "port": p.device,
                "description": p.description or "",
                "manufacturer": p.manufacturer or "",
                "product": p.product or "",
                "vid": f"0x{p.vid:04X}" if p.vid is not None else "",
                "pid": f"0x{p.pid:04X}" if p.pid is not None else "",
                "serial_number": p.serial_number or "",
                "hwid": p.hwid or "",
            }
        )
    return sorted(ports, key=lambda x: x["port"])


def find_port(
    vid: Any = None,
    pid: Any = None,
    serial_number: str = "",
    description_contains: str = "",
) -> Optional[str]:
    """First port matching every filter you supply. None if nothing matches."""
    want_vid = _as_int(vid)
    want_pid = _as_int(pid)

    for p in list_ports.comports():
        if want_vid is not None and p.vid != want_vid:
            continue
        if want_pid is not None and p.pid != want_pid:
            continue
        if serial_number and (p.serial_number or "") != serial_number:
            continue
        if description_contains and description_contains.lower() not in (p.description or "").lower():
            continue
        return p.device

    return None


def resolve_port(config: Dict[str, Any], instrument_name: str = "instrument") -> str:
    """Turn a station.toml block into an actual port name.

    An explicit `port` wins; otherwise match on vid/pid/serial_number.
    Raises with an actionable message when nothing matches, because a silent
    fallback to the wrong COM port is far worse than a clear failure.
    """
    explicit = str(config.get("port", "") or "").strip()
    if explicit:
        return explicit

    port = find_port(
        vid=config.get("vid"),
        pid=config.get("pid"),
        serial_number=config.get("serial_number", ""),
        description_contains=config.get("description_contains", ""),
    )
    if port:
        logger.debug(f"Resolved {instrument_name} to {port} by USB id")
        return port

    available = ", ".join(p["port"] for p in list_serial_ports()) or "none"
    raise RuntimeError(
        f"Could not find a serial port for '{instrument_name}'. "
        f"Set [{instrument_name}].port in config/station.toml, or its vid/pid. "
        f"Ports currently available: {available}. Run 'python main.py ports' to inspect them."
    )


def print_ports() -> None:
    ports = list_serial_ports()
    if not ports:
        logger.warning("No serial ports found.")
        return

    header = f"{'PORT':<8} {'VID':<8} {'PID':<8} {'SERIAL':<20} DESCRIPTION"
    logger.info(header)
    logger.info("-" * len(header))
    for p in ports:
        logger.info(
            f"{p['port']:<8} {p['vid']:<8} {p['pid']:<8} {p['serial_number'][:20]:<20} {p['description']}"
        )
