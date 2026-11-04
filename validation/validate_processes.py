#!/usr/bin/env python3
"""Validate Boomi process XML exports against Wonka's Factory Safety Standards.

The rules themselves live in factory_standards.toml next to this file:

  * error-handling        At least one "returndocuments" shape must have a label
                          containing "error" (case-insensitive).
  * deprecated-components No element may reference a blocklisted componentId.

Every rule runs against every file, so one run reports all of a file's problems,
not just the first one.

Usage:
    python validation/validate_processes.py xml-processes/
    python validation/validate_processes.py --files-from changed.txt --markdown report.md

Exit codes:
    0  every file passed (or there was nothing to validate)
    1  at least one file failed validation, including malformed XML
    2  usage or configuration error (bad arguments, missing or invalid rules file)

Only the Python standard library is used, so CI needs no `pip install` step.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.parsers import expat

EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_USAGE_ERROR = 2

DEFAULT_RULES_FILE = Path(__file__).with_name("factory_standards.toml")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


class ConfigError(Exception):
    """The rules file is missing or invalid."""


@dataclass(frozen=True)
class DeprecatedComponent:
    id: str
    name: str
    reason: str


@dataclass(frozen=True)
class Standards:
    """The validation rules, loaded from factory_standards.toml."""

    error_shape_type: str
    error_label_keyword: str
    # Keyed by normalise_id(id) so lookups ignore case and stray whitespace.
    deprecated_components: dict[str, DeprecatedComponent]


def normalise_id(component_id: str) -> str:
    """Compare component IDs as plain text: trimmed and case-insensitive.

    They are deliberately not parsed as UUIDs, because some blocklisted IDs
    (for example "151411ac-6724-21ae-giz-00000000azz1a") are not valid UUIDs.
    """
    return component_id.strip().casefold()


def load_standards(path: Path) -> Standards:
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"rules file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"rules file {path} is not valid TOML: {exc}") from None

    try:
        error_handling = raw["error_handling"]
        shape_type = str(error_handling["shape_type"]).strip()
        keyword = str(error_handling["label_keyword"]).strip()
        components: dict[str, DeprecatedComponent] = {}
        for entry in raw["deprecated_components"]:
            component = DeprecatedComponent(
                id=str(entry["id"]).strip(),
                name=str(entry["name"]),
                reason=str(entry.get("reason", "")),
            )
            components[normalise_id(component.id)] = component
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"rules file {path} is missing required setting {exc}") from None

    if not shape_type or not keyword:
        raise ConfigError(f"rules file {path}: error_handling settings must not be empty")
    return Standards(shape_type, keyword, components)


# --------------------------------------------------------------------------
# XML parsing
# --------------------------------------------------------------------------


class XMLParseError(Exception):
    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line


def local_name(tag: str) -> str:
    """'bns:object' -> 'object', 'shape' -> 'shape'."""
    return tag.rsplit(":", 1)[-1]


@dataclass
class ProcessDocument:
    """A parsed process file, plus the source line of every element."""

    path: str
    root: ET.Element
    line_of: dict[ET.Element, int]

    @property
    def process_name(self) -> str:
        return self.root.get("name", "")

    def elements(self, name: str) -> list[ET.Element]:
        return [el for el in self.root.iter() if local_name(el.tag) == name]

    def line(self, element: ET.Element | None) -> int | None:
        return None if element is None else self.line_of.get(element)


def parse_process(path: Path, display_path: str) -> ProcessDocument:
    """Parse an XML file into an ElementTree, recording each element's line number.

    ElementTree on its own does not keep line numbers, so this drives the expat
    parser directly and feeds a TreeBuilder. The line numbers let CI put error
    annotations on the exact line of the pull request diff.

    Any DOCTYPE is rejected. Boomi exports never contain one, and refusing it
    rules out entity-expansion attacks such as "billion laughs" from a
    malicious file in a pull request.
    """
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate()
    line_of: dict[ET.Element, int] = {}

    def start_element(tag: str, attrs: dict[str, str]) -> None:
        line_of[builder.start(tag, attrs)] = parser.CurrentLineNumber

    def reject_doctype(*_args: object) -> None:
        raise XMLParseError("DOCTYPE declarations are not allowed", parser.CurrentLineNumber)

    parser.StartElementHandler = start_element
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = reject_doctype

    try:
        with path.open("rb") as fh:
            parser.ParseFile(fh)
    except expat.ExpatError as exc:
        reason = expat.ErrorString(exc.code)
        raise XMLParseError(
            f"XML is not well-formed: {reason} (line {exc.lineno}, column {exc.offset})",
            exc.lineno,
        ) from None
    except OSError as exc:
        raise XMLParseError(f"could not read file: {exc.strerror or exc}") from None

    return ProcessDocument(display_path, builder.close(), line_of)


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One specific problem, with the line it was found on when there is one."""

    message: str
    line: int | None = None


@dataclass(frozen=True)
class RuleOutcome:
    detail: str  # one-line summary, shown whether the rule passed or failed
    findings: list[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    check: Callable[[ProcessDocument, Standards], RuleOutcome]


def describe_shape(doc: ProcessDocument, shape: ET.Element, with_line: bool = True) -> str:
    """'shape6 "Quality Control Error" (line 45)'"""
    label = shape.get("userlabel", "")
    text = f'{shape.get("name", "?")} "{label}"' if label else shape.get("name", "?")
    line = doc.line(shape) if with_line else None
    return f"{text} (line {line})" if line else text


def check_error_handling(doc: ProcessDocument, standards: Standards) -> RuleOutcome:
    shape_type = standards.error_shape_type.casefold()
    keyword = standards.error_label_keyword.casefold()

    handlers = []
    for shape in doc.elements("shape"):
        if shape.get("shapetype", "").casefold() != shape_type:
            continue
        # The label can be on the shape (userlabel) or in its configuration,
        # e.g. <returndocuments label="Quality Control Error"/>. Either counts.
        labels = [shape.get("userlabel", "")]
        labels += [el.get("label", "") for el in shape.iter() if local_name(el.tag) == shape_type]
        if any(keyword in label.casefold() for label in labels):
            handlers.append(shape)

    if handlers:
        found = ", ".join(describe_shape(doc, shape) for shape in handlers)
        return RuleOutcome(f"Found error handling: {found}")

    shapes = doc.elements("shapes")
    anchor = shapes[0] if shapes else doc.root
    return RuleOutcome(
        "No error handling found",
        [
            Finding(
                f'No "{standards.error_shape_type}" shape has a label containing '
                f'"{standards.error_label_keyword}". Add a Return Documents shape '
                'such as "Quality Control Error" so failures are handled safely.',
                doc.line(anchor),
            )
        ],
    )


def check_deprecated_components(doc: ProcessDocument, standards: Standards) -> RuleOutcome:
    # The requirement names shapes, but in Boomi exports a shape's component
    # references often sit on nested elements (e.g. the script step inside a
    # Data Process shape). Checking every element covers both, and each hit is
    # reported against the shape that contains it.
    parent_of = {child: parent for parent in doc.root.iter() for child in parent}

    def enclosing_shape(element: ET.Element) -> ET.Element | None:
        node: ET.Element | None = element
        while node is not None and local_name(node.tag) != "shape":
            node = parent_of.get(node)
        return node

    references = 0
    findings: list[Finding] = []
    reported: set[tuple[int, str]] = set()  # one finding per (shape, component)
    for element in doc.root.iter():
        component_id = element.get("componentId")
        if component_id is None:
            continue
        references += 1
        banned = standards.deprecated_components.get(normalise_id(component_id))
        if banned is None:
            continue

        shape = enclosing_shape(element)
        key = (id(shape), normalise_id(component_id))
        if key in reported:
            continue
        reported.add(key)

        where = (
            f"Shape {describe_shape(doc, shape, with_line=False)}"
            if shape is not None
            else "The process itself"
        )
        reason = f" {banned.reason}" if banned.reason else ""
        findings.append(
            Finding(
                f'{where} uses deprecated component "{component_id.strip()}" '
                f"({banned.name}).{reason}",
                doc.line(element),
            )
        )

    if findings:
        return RuleOutcome(f"Found {len(findings)} deprecated component use(s)", findings)
    return RuleOutcome(
        f"None of {references} componentId reference(s) are on the blocklist "
        f"of {len(standards.deprecated_components)}"
    )


# The checks that run against every file. To add a rule, write a check
# function above (and any settings it needs in factory_standards.toml), then
# list it here.
RULES: tuple[Rule, ...] = (
    Rule("error-handling", "Quality control error handling", check_error_handling),
    Rule("deprecated-components", "No deprecated components", check_deprecated_components),
)


# --------------------------------------------------------------------------
# Running the rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    outcome: RuleOutcome

    @property
    def passed(self) -> bool:
        return not self.outcome.findings


@dataclass(frozen=True)
class FileReport:
    path: str
    process_name: str = ""
    results: list[RuleResult] = field(default_factory=list)
    parse_error: XMLParseError | None = None

    @property
    def passed(self) -> bool:
        return self.parse_error is None and all(r.passed for r in self.results)


def validate_file(path: Path, standards: Standards, display_path: str | None = None) -> FileReport:
    shown = display_path or path.as_posix()
    try:
        doc = parse_process(path, shown)
    except XMLParseError as exc:
        return FileReport(shown, parse_error=exc)
    results = [RuleResult(rule, rule.check(doc, standards)) for rule in RULES]
    return FileReport(shown, doc.process_name, results)


def collect_files(paths: Iterable[str]) -> list[Path]:
    """Expand directories to the .xml files inside them. Files are kept as given."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".xml")
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(raw)
    return sorted(set(files), key=lambda p: p.as_posix())


# --------------------------------------------------------------------------
# Output: console text, GitHub annotations and a Markdown report
# --------------------------------------------------------------------------


def render_text(reports: list[FileReport]) -> str:
    lines = [f"Validating {len(reports)} process file(s) against the Factory Safety Standards", ""]
    for report in reports:
        status = "PASS" if report.passed else "FAIL"
        name = f"  ({report.process_name})" if report.process_name else ""
        lines.append(f"[{status}] {report.path}{name}")
        if report.parse_error:
            lines.append(f"    [FAIL] Well-formed XML: {report.parse_error}")
        for result in report.results:
            mark = "PASS" if result.passed else "FAIL"
            lines.append(f"    [{mark}] {result.rule.title}: {result.outcome.detail}")
            for finding in result.outcome.findings:
                where = f"line {finding.line}: " if finding.line else ""
                lines.append(f"           - {where}{finding.message}")
        lines.append("")
    failed = sum(not r.passed for r in reports)
    lines.append(f"Summary: {len(reports) - failed} passed, {failed} failed")
    return "\n".join(lines)


def _escape_data(value: str) -> str:
    # Escaping used by GitHub's own toolkit (@actions/core). Without it, a file
    # name or label containing a newline could inject extra workflow commands.
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def github_annotations(reports: list[FileReport]) -> list[str]:
    """`::error` workflow commands, which GitHub shows inline on the PR diff."""
    commands = []

    def annotate(path: str, line: int | None, title: str, message: str) -> None:
        props = f"file={_escape_property(path)}"
        if line:
            props += f",line={line}"
        props += f",title={_escape_property(title)}"
        commands.append(f"::error {props}::{_escape_data(message)}")

    for report in reports:
        if report.parse_error:
            annotate(report.path, report.parse_error.line, "Well-formed XML", str(report.parse_error))
        for result in report.results:
            for finding in result.outcome.findings:
                annotate(report.path, finding.line, result.rule.title, finding.message)
    return commands


def _md_code(value: str) -> str:
    """Render untrusted text (file names, labels) as inline code.

    Inside a code span, Markdown, HTML and @mentions from a pull request
    cannot render or notify anyone. Pipes are escaped so table cells stay intact.
    """
    cleaned = " ".join(value.split()).replace("`", "'").replace("|", "\\|")
    return f"`{cleaned}`" if cleaned else "—"


def render_markdown(reports: list[FileReport]) -> str:
    failed = [r for r in reports if not r.passed]
    if not reports:
        headline = "✅ No process XML files to validate"
    elif failed:
        headline = f"❌ {len(failed)} of {len(reports)} process file(s) failed"
    else:
        headline = f"✅ All {len(reports)} process file(s) passed"

    out = [f"## 🍫 Factory Safety Standards: {headline}", ""]
    if not reports:
        return "\n".join(out + ["No added or modified XML files under `xml-processes/`.", ""])

    rule_titles = " | ".join(rule.title for rule in RULES)
    out.append(f"| Result | File | Process | {rule_titles} |")
    out.append("|---|---|---|" + "---|" * len(RULES))
    for report in reports:
        if report.parse_error:
            cells = ["⚠️ not checked"] * len(RULES)
        else:
            cells = ["✅" if r.passed else "❌" for r in report.results]
        result = "✅ Pass" if report.passed else "❌ Fail"
        out.append(
            f"| {result} | {_md_code(report.path)} | {_md_code(report.process_name)} | "
            + " | ".join(cells)
            + " |"
        )
    out.append("")

    for report in failed:
        out.append(f"### ❌ {_md_code(report.path)}")
        out.append("")
        if report.parse_error:
            line = f" (line {report.parse_error.line})" if report.parse_error.line else ""
            out.append(f"- **Well-formed XML**{line}: {_md_code(str(report.parse_error))}")
        for result in report.results:
            for finding in result.outcome.findings:
                line = f" (line {finding.line})" if finding.line else ""
                out.append(f"- **{result.rule.title}**{line}: {_md_code(finding.message)}")
        out.append("")

    out += [
        "<details><summary>What these checks enforce</summary>",
        "",
        "- **Quality control error handling**: at least one `returndocuments` shape "
        'must have a label containing "error" (case-insensitive).',
        "- **No deprecated components**: no element may use a `componentId` from the "
        "blocklist in `validation/factory_standards.toml`.",
        "",
        "</details>",
        "",
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Boomi process XML files against the Factory Safety Standards."
    )
    parser.add_argument("paths", nargs="*", help="XML files, or directories to search for *.xml")
    parser.add_argument(
        "--files-from",
        metavar="FILE",
        help="read more XML file paths from FILE, one per line (used by CI)",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=DEFAULT_RULES_FILE,
        help="rules file (default: %(default)s)",
    )
    parser.add_argument("--markdown", metavar="FILE", type=Path, help="also write a Markdown report")
    parser.add_argument(
        "--github-annotations",
        action="store_true",
        default=os.environ.get("GITHUB_ACTIONS") == "true",
        help="print GitHub ::error annotations (on by default inside GitHub Actions)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    inputs = list(args.paths)
    if args.files_from:
        try:
            listed = Path(args.files_from).read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            print(f"error: cannot read --files-from {args.files_from}: {exc}", file=sys.stderr)
            return EXIT_USAGE_ERROR
        inputs += [line.strip() for line in listed if line.strip()]
    elif not inputs:
        parser.print_usage(sys.stderr)
        print("error: give at least one path, or --files-from", file=sys.stderr)
        return EXIT_USAGE_ERROR

    try:
        standards = load_standards(args.rules)
        files = collect_files(inputs)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    except FileNotFoundError as exc:
        print(f"error: path not found: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    reports = [validate_file(path, standards) for path in files]

    if reports:
        print(render_text(reports))
    else:
        print("No XML files to validate.")
    if args.github_annotations:
        for command in github_annotations(reports):
            print(command)
    if args.markdown:
        args.markdown.write_text(render_markdown(reports), encoding="utf-8")

    return EXIT_OK if all(r.passed for r in reports) else EXIT_VALIDATION_FAILED


if __name__ == "__main__":
    sys.exit(main())
