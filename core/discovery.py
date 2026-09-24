"""Finds testers on disk and loads their TOML definitions.

Directory contract for every tester under testers/:

    testers/<tester_name>/
        parts.toml           which steps + which limits apply to a part number
        result_details.toml  the limit spec for every measurement
        config.py            constants, serial commands, PSU/FG settings
        utils.py             helpers shared by that tester's steps
        tester.py            top-level test steps
        tests/               more test steps, any depth of subfolders
        VERSION              tester version, recorded in every result file
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import logger
from core.results import ResultDetail, TestResult

TESTERS_DIR = Path("testers")
PARTS_TOML = "parts.toml"
RESULT_DETAILS_TOML = "result_details.toml"
VERSION_FILE = "VERSION"
UNKNOWN_VERSION = "?.?.?"


def _load_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def tester_path(tester_name: str) -> Path:
    return TESTERS_DIR / tester_name


def get_all_testers() -> List[str]:
    """Every directory under testers/ that has a parts.toml."""
    if not TESTERS_DIR.exists():
        return []
    return sorted(p.name for p in TESTERS_DIR.iterdir() if p.is_dir() and (p / PARTS_TOML).is_file())


def get_parts_for_tester(tester_name: str) -> Dict[str, Any]:
    return _load_toml(tester_path(tester_name) / PARTS_TOML)


def get_all_part_numbers() -> Dict[str, Dict[str, str]]:
    """part_number -> {desc, tester_name} across every tester."""
    parts: Dict[str, Dict[str, str]] = {}
    for tester_name in get_all_testers():
        for part_number, info in get_parts_for_tester(tester_name).items():
            parts[part_number] = {
                "desc": info.get("desc", ""),
                "tester_name": tester_name,
            }
    return parts


def find_part_number_prefix(part_number: str) -> Optional[str]:
    """parts.toml keys are prefixes, so 'EPBR-PDB-001-REV-A' matches key 'EPBR-PDB-001'."""
    best: Optional[str] = None
    for tester_name in get_all_testers():
        for key in get_parts_for_tester(tester_name):
            if part_number.startswith(key) and (best is None or len(key) > len(best)):
                best = key  # longest prefix wins, so a revision-specific key beats a generic one
    if best is None:
        logger.debug(f"No prefix in any {PARTS_TOML} matches part number '{part_number}'")
    return best


def find_tester_name_by_part_number(part_number: str) -> Optional[str]:
    for tester_name in get_all_testers():
        for key in get_parts_for_tester(tester_name):
            if part_number.startswith(key):
                return tester_name
    return None


def get_test_steps(tester_name: str, part_number: str) -> List[str]:
    parts = get_parts_for_tester(tester_name)
    prefix = find_part_number_prefix(part_number) or part_number
    return list(parts.get(prefix, {}).get("steps", []))


def get_result_details_for_part(tester_name: str, part_number: str) -> List[str]:
    parts = get_parts_for_tester(tester_name)
    prefix = find_part_number_prefix(part_number) or part_number
    return list(parts.get(prefix, {}).get("result_details", []))


def get_existing_result_detail_keys(tester_name: str) -> List[str]:
    return list(_load_toml(tester_path(tester_name) / RESULT_DETAILS_TOML).keys())


def get_test_result_details(tester_name: str, part_number: str) -> Dict[str, TestResult]:
    """Build the empty result slots this part number is expected to fill."""
    details = _load_toml(tester_path(tester_name) / RESULT_DETAILS_TOML)
    result_details: Dict[str, TestResult] = {}

    for result_id in get_result_details_for_part(tester_name, part_number):
        if result_id not in details:
            logger.warning(f"'{result_id}' is listed in {PARTS_TOML} but missing from {RESULT_DETAILS_TOML}")
            continue
        result_details[result_id] = TestResult(ResultDetail.from_dict(details[result_id]))

    return result_details


def get_tester_version(tester_name: str) -> str:
    version_path = tester_path(tester_name) / VERSION_FILE
    if version_path.exists():
        return version_path.read_text(encoding="utf-8").strip()
    return UNKNOWN_VERSION


# Files in a tester folder that hold configuration rather than steps. They are
# still imported if a step happens to live there, just searched last.
SUPPORT_MODULES = ("config", "utils")


def get_tester_module_paths(tester_name: str) -> List[str]:
    """Import paths to search for a step function.

    Order: tester.py, then any other top-level .py in the tester folder, then
    everything under tests/. That means a tester can be laid out either way -
    one file per subsystem at the top level (dmm.py, fg.py), or a tests/
    folder - whichever suits the job.
    """
    root = f"testers.{tester_name}"
    folder = tester_path(tester_name)
    module_paths = []

    if (folder / "tester.py").is_file():
        module_paths.append(f"{root}.tester")

    top_level = sorted(
        f.stem
        for f in folder.glob("*.py")
        if f.stem not in {"__init__", "tester"} and f.stem not in SUPPORT_MODULES
    )
    module_paths.extend(f"{root}.{name}" for name in top_level)

    tests_dir = folder / "tests"
    if tests_dir.is_dir():
        module_paths.extend(
            f"{root}.tests.{f.relative_to(tests_dir).with_suffix('').as_posix().replace('/', '.')}"
            for f in sorted(tests_dir.rglob("*.py"))
            if f.name != "__init__.py"
        )

    # Searched last: a step is unlikely to live here, but importing costs nothing.
    module_paths.extend(
        f"{root}.{name}" for name in SUPPORT_MODULES if (folder / f"{name}.py").is_file()
    )

    return module_paths


def get_available_test_steps(tester_name: str) -> List[str]:
    """Every decorated top-level function in a tester - i.e. everything runnable.

    Parsed with ast rather than imported, so listing steps never touches hardware.
    """
    root = tester_path(tester_name)
    module_files = [f for f in root.glob("*.py") if f.stem != "__init__"]
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        module_files.extend(f for f in tests_dir.rglob("*.py") if f.name != "__init__.py")

    steps = set()
    for module_file in module_files:
        if not module_file.exists():
            continue
        try:
            tree = ast.parse(module_file.read_text(encoding="utf-8"), filename=str(module_file))
        except SyntaxError as e:
            logger.error(f"Could not parse {module_file}: {e}")
            continue
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.decorator_list:
                steps.add(node.name)

    return sorted(steps)


def validate_tester(tester_name: str, part_number: str) -> List[str]:
    """Check a part number's definition without running anything. Returns problems found."""
    problems: List[str] = []

    steps = get_test_steps(tester_name, part_number)
    if not steps:
        problems.append(f"No steps defined for part number '{part_number}'")

    available = set(get_available_test_steps(tester_name))
    for step in steps:
        if step not in available:
            problems.append(f"Step '{step}' is listed in {PARTS_TOML} but no decorated function defines it")

    declared = set(get_existing_result_detail_keys(tester_name))
    for result_id in get_result_details_for_part(tester_name, part_number):
        if result_id not in declared:
            problems.append(f"Result '{result_id}' is listed in {PARTS_TOML} but missing from {RESULT_DETAILS_TOML}")

    return problems
