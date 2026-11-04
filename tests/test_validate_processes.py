"""Tests for validation/validate_processes.py.

They run the validator against the three sample files that came with the
assessment, plus small hand-written processes for the edge cases. If a later
change to the rules or the code breaks the expected results, these fail first.

Run with:  python -m pytest
"""

from __future__ import annotations

from pathlib import Path

import pytest

import validate_processes as vp

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = REPO_ROOT / "boomi-processes"

# The four IDs named in the assessment. Removing one from the rules file
# should be a deliberate decision, so the test pins them.
REQUIRED_BLOCKLIST = {
    "ab12cd34-5678-90ef-ghij-klmnopqrstuv",
    "ff00aa11-2233-4455-6677-889900bbccdd",
    "151411ac-6724-21ae-giz-00000000azz1a",
    "12345678-9abc-def0-1234-56789abcdef0",
}

ERROR_HANDLER = """
<shape name="shape9" shapetype="returndocuments" userlabel="Quality Control Error">
  <configuration><returndocuments label="Quality Control Error"/></configuration>
</shape>"""


@pytest.fixture(scope="module")
def standards() -> vp.Standards:
    return vp.load_standards(vp.DEFAULT_RULES_FILE)


def make_process(tmp_path: Path, shapes: str, name: str = "process.xml") -> Path:
    """Write a minimal Boomi-style process with the given <shape> elements."""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Component xmlns:bns="http://api.platform.boomi.com/" componentId="9a4d9681-c0e6-448f-a8af-d9b45364e34a" name="Test Process" type="process">
  <bns:object>
    <process>
      <shapes>{shapes}
      </shapes>
    </process>
  </bns:object>
</Component>
"""
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return path


def failed_rules(report: vp.FileReport) -> set[str]:
    return {r.rule.id for r in report.results if not r.passed}


# --- The provided sample files ------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected_failures"),
    [
        ("example_file_valid.xml", set()),
        ("example_missing_error_handling.xml", {"error-handling"}),
        # This file breaks both rules. Both must be reported, not just the first.
        ("example_with_deprecated_component.xml", {"error-handling", "deprecated-components"}),
    ],
)
def test_provided_samples(standards, filename, expected_failures):
    report = vp.validate_file(SAMPLES / filename, standards)
    assert report.parse_error is None
    assert failed_rules(report) == expected_failures
    assert report.passed is (not expected_failures)


def test_deprecated_finding_names_shape_component_and_line(standards):
    report = vp.validate_file(SAMPLES / "example_with_deprecated_component.xml", standards)
    result = next(r for r in report.results if r.rule.id == "deprecated-components")
    # The ID appears on the shape and on its nested script step: report it once.
    assert len(result.outcome.findings) == 1
    finding = result.outcome.findings[0]
    assert "shape2" in finding.message
    assert "Legacy Taffy Puller v1.0" in finding.message
    assert finding.line == 15


# --- Rules file -----------------------------------------------------------------


def test_rules_file_contains_required_blocklist(standards):
    assert REQUIRED_BLOCKLIST <= set(standards.deprecated_components)


@pytest.mark.parametrize(
    "toml",
    [
        "",  # nothing at all
        '[error_handling]\nshape_type = "returndocuments"\n',  # no keyword, no blocklist
        '[error_handling]\nshape_type = "returndocuments"\nlabel_keyword = "error"\n'
        '[[deprecated_components]]\nname = "missing its id"\n',
        "this is = = not toml",
    ],
)
def test_invalid_rules_file_raises_config_error(tmp_path, toml):
    rules = tmp_path / "rules.toml"
    rules.write_text(toml, encoding="utf-8")
    with pytest.raises(vp.ConfigError):
        vp.load_standards(rules)


# --- Error-handling rule --------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["Quality Control Error", "QUALITY CONTROL ERROR", "error handler", "OnError"],
)
def test_error_label_is_case_insensitive(tmp_path, standards, label):
    shape = f'<shape name="s" shapetype="returndocuments" userlabel="{label}"/>'
    report = vp.validate_file(make_process(tmp_path, shape), standards)
    assert "error-handling" not in failed_rules(report)


def test_error_label_in_configuration_only_counts(tmp_path, standards):
    shape = """
<shape name="s" shapetype="returndocuments" userlabel="">
  <configuration><returndocuments label="Recipe Error"/></configuration>
</shape>"""
    report = vp.validate_file(make_process(tmp_path, shape), standards)
    assert "error-handling" not in failed_rules(report)


def test_error_label_on_other_shape_type_does_not_count(tmp_path, standards):
    shape = '<shape name="s" shapetype="stop" userlabel="Error"/>'
    report = vp.validate_file(make_process(tmp_path, shape), standards)
    assert "error-handling" in failed_rules(report)


def test_returndocuments_without_error_label_fails(tmp_path, standards):
    shape = '<shape name="s" shapetype="returndocuments" userlabel="Processing Complete"/>'
    report = vp.validate_file(make_process(tmp_path, shape), standards)
    assert "error-handling" in failed_rules(report)


# --- Deprecated-components rule -------------------------------------------------


@pytest.mark.parametrize("component_id", sorted(REQUIRED_BLOCKLIST))
def test_each_blocklisted_component_is_caught(tmp_path, standards, component_id):
    shapes = f'<shape name="s" shapetype="dataprocess" componentId="{component_id}"/>' + ERROR_HANDLER
    report = vp.validate_file(make_process(tmp_path, shapes), standards)
    assert failed_rules(report) == {"deprecated-components"}


def test_component_id_match_ignores_case_and_whitespace(tmp_path, standards):
    shapes = (
        '<shape name="s" shapetype="dataprocess" componentId=" FF00AA11-2233-4455-6677-889900BBCCDD "/>'
        + ERROR_HANDLER
    )
    report = vp.validate_file(make_process(tmp_path, shapes), standards)
    assert failed_rules(report) == {"deprecated-components"}


def test_component_nested_inside_shape_is_caught(tmp_path, standards):
    # No componentId on the shape itself, only on its configuration.
    shapes = (
        """
<shape name="shape4" shapetype="dataprocess" userlabel="Temper">
  <configuration>
    <dataprocessscript componentId="ff00aa11-2233-4455-6677-889900bbccdd"/>
  </configuration>
</shape>"""
        + ERROR_HANDLER
    )
    report = vp.validate_file(make_process(tmp_path, shapes), standards)
    result = next(r for r in report.results if r.rule.id == "deprecated-components")
    assert len(result.outcome.findings) == 1
    assert "shape4" in result.outcome.findings[0].message


def test_allowed_component_passes(tmp_path, standards):
    shapes = (
        '<shape name="s" shapetype="dataprocess" componentId="cf0dd5db-90d7-4087-a29d-d7a5363b4f7e"/>'
        + ERROR_HANDLER
    )
    report = vp.validate_file(make_process(tmp_path, shapes), standards)
    assert report.passed


# --- Bad input ------------------------------------------------------------------


def test_malformed_xml_is_reported_not_crashed(tmp_path, standards):
    path = tmp_path / "broken.xml"
    path.write_text("<Component>\n  <shapes>\n</Component>\n", encoding="utf-8")
    report = vp.validate_file(path, standards)
    assert not report.passed
    assert report.parse_error is not None
    assert "not well-formed" in str(report.parse_error)
    assert report.parse_error.line == 3


def test_doctype_is_rejected(tmp_path, standards):
    # A tiny "billion laughs" style payload. It must be refused, not expanded.
    path = tmp_path / "entities.xml"
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>\n'
        "<Component>&lol2;</Component>\n",
        encoding="utf-8",
    )
    report = vp.validate_file(path, standards)
    assert report.parse_error is not None
    assert "DOCTYPE" in str(report.parse_error)


# --- Output ---------------------------------------------------------------------


def test_annotations_escape_untrusted_values():
    report = vp.FileReport(
        path="xml-processes/odd,name:1.xml",
        parse_error=vp.XMLParseError("bad\n::error::injected", line=2),
    )
    [command] = vp.github_annotations([report])
    assert "\n" not in command
    assert command.startswith("::error file=xml-processes/odd%2Cname%3A1.xml,line=2,")
    assert command.endswith("::bad%0A::error::injected")


def test_untrusted_text_is_rendered_as_inline_code():
    # Inside a code span, @mentions and Markdown from a PR can't take effect.
    # Backticks can't close the span early and pipes can't break the table.
    assert vp._md_code("Done | @everyone `x`") == "`Done \\| @everyone 'x'`"
    assert vp._md_code("line one\nline two") == "`line one line two`"
    assert vp._md_code("") == "—"


def test_markdown_report_lists_each_file(tmp_path, standards):
    shape = '<shape name="s" shapetype="returndocuments" userlabel="Processing Complete"/>'
    report = vp.validate_file(make_process(tmp_path, shape), standards)
    markdown = vp.render_markdown([report])
    assert "❌ 1 of 1 process file(s) failed" in markdown
    assert "| ❌ Fail |" in markdown
    assert "`Test Process`" in markdown


def test_markdown_when_nothing_to_validate():
    assert "No process XML files to validate" in vp.render_markdown([])


# --- Command line and exit codes ------------------------------------------------


def test_cli_exit_codes(tmp_path, capsys):
    assert vp.main([str(SAMPLES / "example_file_valid.xml")]) == vp.EXIT_OK
    assert vp.main([str(SAMPLES)]) == vp.EXIT_VALIDATION_FAILED
    assert vp.main([str(tmp_path / "does-not-exist.xml")]) == vp.EXIT_USAGE_ERROR
    assert vp.main([]) == vp.EXIT_USAGE_ERROR

    bad_rules = tmp_path / "rules.toml"
    bad_rules.write_text("not = = toml", encoding="utf-8")
    assert vp.main(["--rules", str(bad_rules), str(SAMPLES)]) == vp.EXIT_USAGE_ERROR


def test_cli_files_from_and_markdown_report(tmp_path):
    listing = tmp_path / "changed.txt"
    listing.write_text(
        f"{SAMPLES / 'example_file_valid.xml'}\n\n{SAMPLES / 'example_missing_error_handling.xml'}\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.md"
    code = vp.main(["--files-from", str(listing), "--markdown", str(report)])
    assert code == vp.EXIT_VALIDATION_FAILED
    assert "1 of 2 process file(s) failed" in report.read_text(encoding="utf-8")


def test_cli_empty_files_from_passes(tmp_path):
    # A PR that only deletes XML files leaves nothing to check, which is fine.
    listing = tmp_path / "changed.txt"
    listing.write_text("", encoding="utf-8")
    assert vp.main(["--files-from", str(listing)]) == vp.EXIT_OK
