# Wonka Factory XML Validation

A GitHub Actions check that blocks Boomi integration processes from deployment
until they meet Wonka's Factory Safety Standards. The two standards are quality
control error handling and no deprecated candy-making components.

## Approach

Every pull request that adds or changes an XML file in `xml-processes/` runs the
[**XML Validation**](.github/workflows/xml-validation.yml) workflow. The workflow
uses `git diff` against the base branch to find the changed files and passes them
to a small Python validator. The check fails if any file breaks a rule. Failures
show up in three places, so nobody has to dig through logs. Each problem is an
inline annotation on the exact line in the PR's *Files changed* tab. A results
table goes to the run summary. One PR comment holds the results and is updated on
every push rather than posting a new one each time. If the rules or the validator
change, every process gets re-checked, not just the changed files, because a new
rule can break a file that passed yesterday.

The [validator](validation/validate_processes.py) parses each file as XML instead
of searching the text. That way, "Error" in a script comment or on the wrong shape
type doesn't count as error handling. Each rule is its own function in a `RULES`
list. The settings, including the deprecated-component blocklist, live in
[`factory_standards.toml`](validation/factory_standards.toml), so banning a new
component means adding three lines of config, with no code change. Every rule runs
against every file, so a file with two problems reports both. Malformed XML gets a
clear message instead of a stack trace. Exit codes have fixed meanings: `0` means
pass, `1` means validation failed, and `2` means a usage or configuration error.
The validator uses only Python's standard library, so CI has no `pip install` step
to break or compromise. [Tests](tests/test_validate_processes.py) run it against the
three provided samples and the edge cases below. They run in their own workflow
whenever the validator changes.

For security, the workflow starts with `permissions: {}`. The job that reads the
PR's files gets `contents: read`. A separate job that never runs code from the PR
gets `pull-requests: write`, and only to post the comment. It uses `pull_request`
rather than `pull_request_target`, so code from forks never runs with secrets or
write access. Every action is pinned to a full commit SHA, and Dependabot keeps the
pins current. Text that comes from the PR, such as file names and shape labels, is
escaped before it goes into annotations or the comment, so it can't inject workflow
commands or @mention anyone. XML with a DOCTYPE is rejected, which rules out
entity-expansion attacks. I used first-party marketplace actions for the general
plumbing: checkout, Python setup, artifacts and the GitHub API. The Boomi-specific
rules are custom code, since no marketplace action knows them. I deliberately
didn't use a third-party "changed files" action, because the most popular one
(`tj-actions/changed-files`) was compromised in 2025, and `git diff` does the same
job. The validation steps are packaged as a
[composite action](.github/actions/validate-process-xml/action.yml) so other
workflows can reuse them.

## Repository layout

| Path | What it is |
|---|---|
| `.github/workflows/xml-validation.yml` | The PR check: selects files, validates, and comments on the PR |
| `.github/actions/validate-process-xml/` | Composite action: sets up Python, runs the validator, writes the summary |
| `.github/workflows/validator-tests.yml` | Unit tests for the validator, on Python 3.11 and 3.13 |
| `validation/validate_processes.py` | The validator (standard library only) |
| `validation/factory_standards.toml` | The rules and the deprecated-component blocklist |
| `tests/` | pytest suite |
| `xml-processes/` | Processes to deploy. The workflow watches this folder |
| `boomi-processes/` | The three sample files as provided, used as test fixtures |
| `.github/CODEOWNERS`, `.github/dependabot.yml` | Review ownership of the rules, and automatic action-pin updates |

## Running it locally

Requires Python 3.11 or newer.

```bash
# Validate files or whole folders
python validation/validate_processes.py boomi-processes/
python validation/validate_processes.py xml-processes/my_process.xml --markdown report.md

# Run the tests
python -m pip install -r requirements-dev.txt
python -m pytest
```

The workflow files can be linted locally with
[actionlint](https://github.com/rhysd/actionlint), and run end to end with
[act](https://github.com/nektos/act).

## Assumptions

- **Folder name.** The README says to trigger on `xml-processes/`, but the samples
  came in `boomi-processes/`. I followed the README. The samples stay unchanged in
  `boomi-processes/` as test fixtures, and the demo PRs add copies to
  `xml-processes/`.
- **Which label.** A Return Documents shape has a label in two places: the
  `userlabel` attribute and `<returndocuments label="...">` in its configuration.
  "Error" in either one counts.
- **"Contains Error"** is a case-insensitive substring match, per the requirement,
  so `Quality Control Error`, `ERROR` and `OnError` all count.
- **Where component IDs live.** The requirement names shapes, but in Boomi exports
  a component reference often sits inside the shape's configuration. The bad sample
  has the banned ID on both the shape and its nested script step. I check the
  `componentId` on every element and report each hit against the shape that
  contains it. A process whose own ID is on the blocklist is blocked too.
- **Component IDs are plain text,** compared trimmed and case-insensitively. They
  aren't parsed as UUIDs, because two of the four blocklisted IDs aren't valid
  UUIDs (e.g. `151411ac-6724-21ae-giz-00000000azz1a`).
- **Changed files only.** A PR checks the XML files it adds or modifies (deleted
  files have nothing to check), plus every file when the validation tooling
  changes. Files are assumed to be Boomi *process* exports. Malformed XML fails
  the check.

## Potential improvements

- **Make it a real gate.** A red X alone doesn't stop anyone from merging. The next
  step is to mark the check as required in branch protection for `main`. One
  gotcha: a path-filtered workflow doesn't run at all on PRs that don't touch XML,
  so a required check would sit at "pending" forever. The fix is to always run the
  workflow and skip the work inside the job when no relevant files changed.
- **Close the bypass from inside the PR.** The rules and validator live in the same
  repo, so one PR could delete a blocklist entry *and* add the banned component,
  and the check would pass. `CODEOWNERS` is included for this, but it only protects
  anything once "Require review from Code Owners" is enabled. A stronger option is
  to run the validator and rules from the base branch, or from a separate, locked
  repo.
- **Comments on fork PRs.** GitHub gives fork PRs a read-only token, so the comment
  job skips them. The check, the annotations and the summary still work. A
  follow-up `workflow_run` workflow could post those comments safely.
- **One rule set for every repo.** Move the composite action and rules to a shared,
  versioned actions repo (or a reusable workflow), so every integration repo
  enforces the same standards.
- **Richer rules.** Add a severity per rule (warn vs fail), and allowlist exceptions
  that expire. Validate the overall Boomi export structure. Match "error" on word
  boundaries if "Terror Tunnel Tour" ever becomes a real shape label.
- **Operations.** Notify a channel when the check fails on `main` or the validator
  itself errors (exit code `2`). Track failure rates by rule to see which standards
  people trip over. Pin the test dependencies with hashes (`--require-hashes`).
