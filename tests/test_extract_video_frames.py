from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "extract_video_frames.py"
SPEC = importlib.util.spec_from_file_location("extract_video_frames", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_times_accepts_spaces_commas_sorts_and_deduplicates() -> None:
    assert MODULE.parse_times(["30", "1, 15", "15.0"]) == [1.0, 15.0, 30.0]


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "abc"])
def test_parse_times_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        MODULE.parse_times([value])


def test_output_paths_and_frame_names_are_lesson_scoped(tmp_path: Path) -> None:
    frames, contact = MODULE.output_paths(tmp_path, "108")
    assert frames == tmp_path / "f108"
    assert contact == tmp_path / "f108-contact.png"
    assert MODULE.frame_filename(1) == "t001.00.png"
    assert MODULE.frame_filename(315.5) == "t315.50.png"


@pytest.mark.parametrize("value", ["../108", "108/next", "", "课108"])
def test_validate_lesson_rejects_unsafe_output_names(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        MODULE.validate_lesson(value)
