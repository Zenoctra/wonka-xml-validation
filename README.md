# Wonka Factory XML Validation

A GitHub Actions check that validates Boomi process XML against Wonka's Factory
Safety Standards on every pull request.

## Approach

When a pull request changes anything in `xml-processes/`, the
[workflow](.github/workflows/xml-validation.yml) lists the files the pull request
added or changed and runs a [Python validator](validation/validate_processes.py) on
each one. It uses the validator and rules from the pull request's base branch
(usually `main`), not the pull request's own copy, so a pull request can't loosen the
rules it's checked against. Every rule runs on every file, and the report shows each
rule as passed or failed for each file. The report goes to the run summary and to one
comment on the pull request, which is updated on later pushes. If any file fails, the
check fails.

The validator reads each file as XML, a tree of shapes, instead of searching the
text. That way the word "Error" in a script comment doesn't count as error handling,
and a banned ID written with XML escape codes is still caught. For error handling, a
file passes if at least one Return Documents shape (`shapetype="returndocuments"`)
has "error", in any case, in either of its labels: the `userlabel` attribute or the
label in the shape's configuration. For deprecated components, it collects every
`componentId` on each shape and on everything inside it, and compares them to the
blocklist, ignoring case. The blocklist lives in
[`factory_standards.toml`](validation/factory_standards.toml), so banning a component
is a config change. Each rule is its own small function, so adding a rule doesn't
touch the others. The validator uses only Python's standard library.

I followed one rule: harden the supported path, which is Boomi process XML in
`xml-processes/`, and fail loudly on anything unsupported. A file in the folder that
isn't readable XML fails instead of being skipped. A broken blocklist file exits with
`2` (the tool broke) instead of `1` (a file failed), and if validation stops before
writing a report, the summary and comment say so instead of going blank. The workflow
can only read the repository and comment on pull requests, and it uses GitHub's own
checkout and Python actions, pinned to exact commits. The rules are custom code, since
no marketplace action checks Wonka's standards for Boomi processes. The
[tests](validation/test_validate_processes.py) cover the three samples plus edge cases
like broken or empty files and IDs nested inside a shape, and the
[demo pull requests](https://github.com/Zenoctra/wonka-xml-validation/pulls) run it on
GitHub.

## Running it locally

```bash
python validation/validate_processes.py boomi-processes/*.xml
pip install pytest
python -m pytest
```

## Assumptions

- **Folder.** The assessment says to trigger on `xml-processes/`, but the samples
  came in `boomi-processes/`. I followed the assessment. The samples stay in
  `boomi-processes/` as test fixtures, and the demo pull requests add copies to
  `xml-processes/`.
- **Which label.** A Return Documents shape has a label in two places: the
  `userlabel` attribute and `<returndocuments label="...">` inside it. "Error" in
  either one counts.
- **"Contains Error"** is a case-insensitive substring match, as written.
- **Component IDs** are checked on the shape and on every element inside it, because
  the bad sample has the banned ID on both the shape and its script step. IDs are
  compared as plain text, ignoring case, since two of the four aren't valid UUIDs.
- **Changed files only.** A pull request checks every file it adds or changes in
  `xml-processes/`, including subfolders. Deleted files are skipped. A file that
  isn't readable XML fails, so nothing in the folder skips validation.
- **Forks.** This repo is public, so reviewers may open pull requests from forks.
  Those get a read-only token, so the check still runs but skips the comment. 
- **Other workflows.** A real repo likely has other workflows commenting on pull
  requests as the same bot, so this workflow finds its own comment by a hidden
  marker instead of editing the bot's last comment.


## Potential improvements

- **The rule checks labels, not whether errors are handled.** A Return Documents
  shape labeled "Error" with nothing connected to it would pass, and so would a
  success path labeled "Complete (No Errors)". A potential improvement would require 
  the error shape to be reachable from a failure route. The valid sample already meets
  that, so adding the rule wouldn't break it.
- **Make it a real gate.** A failed check doesn't stop anyone from merging. Mark it
  as required in branch protection for `main`. One gotcha: this workflow only runs
  when `xml-processes/` changes, so a required check would wait forever on other
  pull requests. The fix is to always run it and skip the work when nothing there
  changed.
- **Check existing processes when the deprecated component blocklist changes.** This 
  check only looks at the files a pull request changes, so a new ban won't flag 
  processes that are already merged. 
  Running the validator on all of `xml-processes/` when the blocklist changes
  would list what's affected. What to do about them is a team decision, and it can
  depend on why the component was banned: fix everything now (a security issue), set
  a deadline and track the rest as tech debt, or open automatic fix pull requests when
  there's a drop-in replacement. A severity or deadline per blocklist entry could
  support that, warning first and failing later. Either way, the full check should
  report what's affected, not suddenly block unrelated pull requests.
- **Scale the report.** For a pull request with many files, put only the failures in
  the comment and link to the full summary, which also stays under GitHub's comment
  size limit. 
- **Inline annotations** on the failing line in the pull request diff.
- **Alerts and trends.** Notify the team when the validator itself breaks (exit code
  `2`), and track which rules fail most often.

