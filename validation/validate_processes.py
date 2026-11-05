"""Check Boomi process XML files against Wonka's Factory Safety Standards.

Two rules, from the assessment:
  1. Error handling: at least one "returndocuments" shape must have a label
     containing "error" (any case).
  2. No deprecated components: no shape may use a componentId listed in
     factory_standards.toml.

Usage:
    python validation/validate_processes.py FILE [FILE ...]

Prints a Markdown report. Exit code 0 means every file passed, 1 means at
least one file failed, and 2 means the rules file couldn't be loaded.
"""

import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

RULES_FILE = Path(__file__).with_name("factory_standards.toml")


def load_blocklist(path=RULES_FILE):
    """Read the deprecated components into a {component ID: name} dictionary.

    IDs are lowercased so the comparison ignores case. They're compared as
    plain text, not parsed as UUIDs, because some of them aren't valid UUIDs.
    """
    with open(path, "rb") as f:
        rules = tomllib.load(f)
    return {c["id"].strip().lower(): c["name"] for c in rules["deprecated_components"]}


def shape_name(shape):
    """A readable name for a shape, like 'shape2 (Legacy Taffy Puller)'."""
    label = shape.get("userlabel")
    return f"{shape.get('name')} ({label})" if label else shape.get("name")


def check_error_handling(root):
    """Rule 1. Returns a list of problems (an empty list means it passed)."""
    for shape in root.iter("shape"):
        if shape.get("shapetype") != "returndocuments":
            continue
        # The label can be on the shape itself (userlabel) or in its
        # configuration (<returndocuments label="...">). Either one counts.
        labels = [shape.get("userlabel", "")]
        labels += [config.get("label", "") for config in shape.iter("returndocuments")]
        if any("error" in label.lower() for label in labels):
            return []
    return ['No "returndocuments" shape has a label containing "Error".']


def check_deprecated_components(root, blocklist):
    """Rule 2. Returns one problem per shape that uses a blocklisted component."""
    problems = []
    for shape in root.iter("shape"):
        # The ID can be on the shape or on an element inside it, like the
        # script step in a Data Process shape, so check every element.
        ids = {el.get("componentId").strip().lower() for el in shape.iter() if el.get("componentId")}
        for component_id in sorted(ids & blocklist.keys()):
            problems.append(
                f"Shape {shape_name(shape)} uses deprecated component "
                f"{component_id} ({blocklist[component_id]})."
            )
    return problems


def validate_file(path, blocklist):
    """Run every rule on one file, so all of its problems get reported."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as e:
        return [f"Could not read the file as XML: {e}"]
    return check_error_handling(root) + check_deprecated_components(root, blocklist)


def main(paths):
    try:
        blocklist = load_blocklist()
    except (OSError, tomllib.TOMLDecodeError, KeyError) as e:
        print(f"Could not load the rules file {RULES_FILE}: {e}")
        return 2

    results = {path: validate_file(path, blocklist) for path in paths}
    failed = [path for path, problems in results.items() if problems]

    if not paths:
        headline = "no XML files to check"
    elif failed:
        headline = f"{len(failed)} of {len(paths)} file(s) failed"
    else:
        headline = f"all {len(paths)} file(s) passed"
    print(f"## Factory Safety Standards: {headline}\n")

    for path, problems in results.items():
        print(f"**{'FAIL' if problems else 'PASS'}** `{path}`")
        for problem in problems:
            print(f"- {problem}")
        print()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
