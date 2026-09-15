"""Instrument drivers. Import from here so tester code stays short:

    from instruments import PSU, PSU_Setting, DMM, Function, RelayBank
"""

from instruments.dmm import DMM, Function
from instruments.function_generator import FG_Setting, FunctionGenerator, Waveforms, fg_off, fg_on
from instruments.psu import PSU, PSU_Setting, psu_off, psu_on
from instruments.relay import Operation, RelayBank, RelayChannel

__all__ = [
    "PSU",
    "PSU_Setting",
    "psu_on",
    "psu_off",
    "FunctionGenerator",
    "FG_Setting",
    "Waveforms",
    "fg_on",
    "fg_off",
    "DMM",
    "Function",
    "RelayBank",
    "RelayChannel",
    "Operation",
]
