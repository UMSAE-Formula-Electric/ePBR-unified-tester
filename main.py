"""ePBR27 unified tester - command line entry point.

    python main.py run BENCH-COMMS -S BENCH01    run a checkout / a board
    python main.py run BENCH-FULL -s DMM_IDENTITY  run one step only
    python main.py list                            testers and part numbers
    python main.py steps instrument_checkout       every runnable step
    python main.py check BENCH-FULL                validate the TOML wiring
    python main.py ports                           serial ports on this PC
    python main.py instruments                     ping each instrument
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

# Make the repo importable no matter where the CLI is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import Env, set_simulate  # noqa: E402
from core.discovery import (  # noqa: E402
    find_tester_name_by_part_number,
    get_all_part_numbers,
    get_all_testers,
    get_available_test_steps,
    get_existing_result_detail_keys,
    get_parts_for_tester,
    get_test_steps,
    get_tester_version,
    validate_tester,
)
from core.logger import logger  # noqa: E402
from core.runner import run_test  # noqa: E402

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


@click.group()
@click.option("-l", "--log-level", type=click.Choice(LOG_LEVELS, case_sensitive=False), default=None)
def cli(log_level: str | None) -> None:
    """Production tester for the ePBR27 Formula Electric car."""
    logger.set_level(log_level or Env.LOG_LEVEL)


@cli.command()
@click.argument("part_number")
@click.option("-S", "--serial-number", default="", help="Serial number of the board under test")
@click.option("-s", "--step", multiple=True, help="Run only this step (repeatable)")
@click.option("-o", "--operator", default=None, help="Operator name recorded in the results")
@click.option("-t", "--tester", default=None, help="Force a tester instead of matching on part number")
@click.option("--simulate", is_flag=True, help="Run against fake instruments - no hardware needed")
@click.option("--no-save", is_flag=True, help="Do not write result files (logs only)")
def run(
    part_number: str,
    serial_number: str,
    step: tuple,
    operator: str | None,
    tester: str | None,
    simulate: bool,
    no_save: bool,
) -> None:
    """Test one board. Exits non-zero if anything failed, so CI and scripts can branch on it."""
    tester_name = tester or find_tester_name_by_part_number(part_number)
    if not tester_name:
        known = ", ".join(get_all_part_numbers()) or "none"
        raise click.ClickException(
            f"No tester claims part number '{part_number}'.\nKnown part numbers: {known}"
        )

    problems = validate_tester(tester_name, part_number)
    if problems:
        logger.warning(f"{len(problems)} problem(s) in the tester definition:")
        for problem in problems:
            logger.warning(f"  - {problem}")

    # Set this before anything constructs an instrument: drivers are built deep
    # inside steps and decorators, and they read the flag from settings.Runtime.
    set_simulate(simulate or Env.SIMULATE)

    logger.info(f"Tester:        {tester_name} v{get_tester_version(tester_name)}")
    logger.info(f"Part number:   {part_number}")
    logger.info(f"Serial number: {serial_number or '(none)'}")

    passed = run_test(
        tester_name=tester_name,
        part_number=part_number,
        serial_number=serial_number,
        operator=operator or Env.OPERATOR,
        steps=list(step) if step else None,
        sinks=[] if no_save else None,
        simulate=simulate or Env.SIMULATE,
    )

    sys.exit(0 if passed else 1)


@cli.command(name="list")
def list_testers() -> None:
    """Every tester and the part numbers it covers."""
    testers = get_all_testers()
    if not testers:
        logger.warning("No testers found under testers/")
        return

    for tester_name in testers:
        logger.info(f"{tester_name}  (v{get_tester_version(tester_name)})")
        parts = get_parts_for_tester(tester_name)
        if not parts:
            logger.warning("    no part numbers defined in parts.toml")
        for part_number, info in parts.items():
            steps = len(info.get("steps", []))
            results = len(info.get("result_details", []))
            logger.info(
                f"    {part_number:<24} {info.get('desc', '')}  [{steps} steps, {results} results]"
            )


@cli.command()
@click.argument("tester_name")
def steps(tester_name: str) -> None:
    """Every runnable step in a tester (found by parsing, so no hardware is touched)."""
    if tester_name not in get_all_testers():
        raise click.ClickException(f"Unknown tester '{tester_name}'. Known: {', '.join(get_all_testers())}")

    available = get_available_test_steps(tester_name)
    logger.info(f"{len(available)} step(s) defined in '{tester_name}':")
    for step_name in available:
        logger.info(f"    {step_name}")

    logger.info("")
    logger.info("Steps wired up per part number:")
    for part_number in get_parts_for_tester(tester_name):
        configured = get_test_steps(tester_name, part_number)
        logger.info(f"    {part_number}: {', '.join(configured) or '(none)'}")

    unused = sorted(
        set(available)
        - {s for pn in get_parts_for_tester(tester_name) for s in get_test_steps(tester_name, pn)}
    )
    if unused:
        logger.warning(f"Defined but not run by any part number: {', '.join(unused)}")


@cli.command()
@click.argument("part_number")
@click.option("-t", "--tester", default=None, help="Force a tester instead of matching on part number")
def check(part_number: str, tester: str | None) -> None:
    """Validate a part number's TOML wiring without running anything."""
    tester_name = tester or find_tester_name_by_part_number(part_number)
    if not tester_name:
        raise click.ClickException(f"No tester claims part number '{part_number}'")

    problems = validate_tester(tester_name, part_number)
    if not problems:
        logger.info(f"'{part_number}' on '{tester_name}' checks out:")
        logger.info(f"    steps:   {', '.join(get_test_steps(tester_name, part_number))}")
        logger.info(f"    results: {len(get_existing_result_detail_keys(tester_name))} declared")
        return

    for problem in problems:
        logger.error(f"  - {problem}")
    raise click.ClickException(f"{len(problems)} problem(s) found")


@cli.command()
def ports() -> None:
    """List serial ports, with VID/PID so you can pin them in station.toml."""
    from utils.ports import print_ports

    print_ports()


@cli.command()
@click.option("--simulate", is_flag=True, help="Exercise the drivers without hardware")
def instruments(simulate: bool) -> None:
    """Ping each configured instrument and print its *IDN? response."""
    from config.settings import STATION
    from instruments.dmm import DMM
    from instruments.function_generator import FunctionGenerator
    from instruments.psu import PSU
    from instruments.relay import RelayBank

    use_sim = simulate or Env.SIMULATE
    set_simulate(use_sim)
    drivers = [("psu", PSU), ("function_generator", FunctionGenerator), ("dmm", DMM)]
    failures = 0

    for name, driver in drivers:
        if not STATION.get(name, {}).get("enabled", True):
            logger.warning(f"{name}: disabled in station.toml, skipping")
            continue
        try:
            with driver(simulate=use_sim) as instrument:
                logger.info(f"{name}: {instrument.identify()}")
        except Exception as e:
            failures += 1
            logger.error(f"{name}: {e}")

    # The relay bank has no *IDN? - opening the port is the connectivity check.
    if STATION.get("relay", {}).get("enabled", True):
        try:
            with RelayBank(simulate=use_sim):
                logger.info("relay: port opened, bank released")
        except Exception as e:
            failures += 1
            logger.error(f"relay: {e}")

    if failures:
        raise click.ClickException(f"{failures} instrument(s) did not respond")
    logger.info("All configured instruments responded.")


if __name__ == "__main__":
    cli()
