"""Where results go once a run finishes: a JSON file per run + a rolling CSV.

This is the seam that NetSuite/ERP occupied in the original framework. If you
ever want results in a database or on a dashboard, add a class with a
`write(run)` method and hand it to the TestRunner - nothing else changes.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Protocol

from core.logger import logger

CSV_COLUMNS = [
    "timestamp",
    "run_id",
    "tester",
    "part_number",
    "serial_number",
    "operator",
    "test_name",
    "step",
    "measured",
    "units",
    "expected",
    "validation_type",
    "passed",
    "duration_s",
]


class ResultSink(Protocol):
    """Anything that can persist a finished run."""

    def write(self, run: Dict[str, Any]) -> None: ...


class JsonResultSink:
    """One timestamped JSON file per run - the complete record."""

    def __init__(self, results_dir: Path) -> None:
        self.results_dir = Path(results_dir)

    def write(self, run: Dict[str, Any]) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        verdict = "PASS" if run.get("passed") else "FAIL"
        filename = f"{run['run_id']}_{run.get('serial_number', 'noserial')}_{verdict}.json"
        path = self.results_dir / filename
        with path.open("w", encoding="utf-8") as f:
            json.dump(run, f, indent=2)
        logger.info(f"Results written to {path}")


class CsvResultSink:
    """Appends one row per measurement to a single CSV - easy to open in Excel."""

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = Path(csv_path)

    def write(self, run: Dict[str, Any]) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.csv_path.exists()

        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            for test_name, result in run.get("results", {}).items():
                writer.writerow(
                    {
                        "timestamp": run.get("started_at", ""),
                        "run_id": run.get("run_id", ""),
                        "tester": run.get("tester", ""),
                        "part_number": run.get("part_number", ""),
                        "serial_number": run.get("serial_number", ""),
                        "operator": run.get("operator", ""),
                        "test_name": test_name,
                        "step": result.get("step", ""),
                        "measured": result.get("measured", ""),
                        "units": result.get("units", ""),
                        "expected": result.get("expected", ""),
                        "validation_type": result.get("validation_type", ""),
                        "passed": result.get("passed", False),
                        "duration_s": result.get("duration_s", 0),
                    }
                )
        logger.debug(f"Appended {len(run.get('results', {}))} rows to {self.csv_path}")


def default_sinks(results_dir: Path) -> List[ResultSink]:
    """JSON detail + CSV summary, the standard local-file setup."""
    return [JsonResultSink(results_dir), CsvResultSink(results_dir / "summary.csv")]


def make_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
