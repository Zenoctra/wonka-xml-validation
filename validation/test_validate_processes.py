"""Tests for validate_processes.py. Run with: python -m pytest"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import validate_processes as vp

SAMPLES = Path(__file__).parent.parent / "boomi-processes"
BLOCKLIST = vp.load_blocklist()


def process(shapes):
    """Build a minimal process around some <shape> XML."""
    return ET.fromstring(f"<process><shapes>{shapes}</shapes></process>")


@pytest.mark.parametrize(
    "filename, expected_failed_rules",
    [
        ("example_file_valid.xml", []),
        ("example_missing_error_handling.xml", ["Quality control error handling"]),
        (
            "example_with_deprecated_component.xml",  # breaks both rules
            ["Quality control error handling", "No deprecated components"],
        ),
    ],
)
def test_provided_samples(filename, expected_failed_rules):
    checks = vp.validate_file(SAMPLES / filename, BLOCKLIST)
    assert [rule for rule, problems in checks.items() if problems] == expected_failed_rules


def test_error_label_counts_in_any_case_and_either_place():
    on_shape = '<shape shapetype="returndocuments" userlabel="QUALITY ERROR"/>'
    in_config = (
        '<shape shapetype="returndocuments"><configuration>'
        '<returndocuments label="Recipe error"/></configuration></shape>'
    )
    assert vp.check_error_handling(process(on_shape)) == []
    assert vp.check_error_handling(process(in_config)) == []


def test_error_label_on_another_shape_type_does_not_count():
    assert vp.check_error_handling(process('<shape shapetype="stop" userlabel="Error"/>')) != []


def test_deprecated_component_nested_inside_shape_in_any_case():
    shape = (
        '<shape name="shape4"><configuration>'
        '<dataprocessscript componentId="FF00AA11-2233-4455-6677-889900BBCCDD"/>'
        "</configuration></shape>"
    )
    assert len(vp.check_deprecated_components(process(shape), BLOCKLIST)) == 1


@pytest.mark.parametrize(
    "content",
    [
        "<process><shapes></process>",  # broken tags
        '<?xml version="1.0" encoding="x-bogus"?><process/>',  # unknown encoding
        "",  # empty file
    ],
)
def test_unreadable_file_is_reported_not_crashed(tmp_path, content):
    bad = tmp_path / "bad.xml"
    bad.write_text(content)
    problems = vp.validate_file(bad, BLOCKLIST)["Readable XML"]
    assert "Could not read the file as XML" in problems[0]
