# Wonka Factory XML Validation

A GitHub Actions check that validates Boomi process XML against Wonka's Factory
Safety Standards on every pull request.

## Approach

When a pull request changes XML files in `xml-processes/`, the
[workflow](.github/workflows/xml-validation.yml) uses `git diff` to find those files
and runs a [Python script](validation/validate_processes.py) on them. The script
checks the two rules (quality control error handling and no deprecated components)
and prints a Markdown report. The workflow adds the report to the run summary and
posts it as a comment on the pull request, updating the same comment on later
pushes. If any file fails, the check fails.

The script reads each file as XML instead of searching the text. Text search is
fragile. It would count "Error" in a script comment as error handling, and it would
miss a component ID written with an XML character reference (`&#97;b12cd34-…`),
which any XML reader, Boomi included, still reads as the banned ID. Each rule is its
own function, and every rule runs on every file, so one run reports all of a file's
problems. The blocklist lives in
[`factory_standards.toml`](validation/factory_standards.toml), so banning a component
is a config change, not a code change. Exit codes: `0` means every file passed, `1`
means a file failed, and `2` means the rules file couldn't be loaded. The script uses
only Python's standard library. The [tests](validation/test_validate_processes.py) use
pytest.

I kept it deliberately small. The workflow can only read the repository and comment
on pull requests. It uses GitHub's own actions for checkout and Python setup, pinned
to exact commits. The rules are custom code, since no marketplace action knows
Boomi's rules. Things I considered and left out are listed under potential
improvements.

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
- **Changed files only.** A pull request checks the XML files it adds or changes.
  Deleted files are skipped. A file that isn't valid XML fails.
- **Forks.** This repo is public, so reviewers may open pull requests from forks.
  Those get a read-only token, so the check still runs but skips the comment. Inside
  a company, people would normally use branches instead.
- **Other workflows.** A real repo likely has other workflows commenting on pull
  requests as the same bot, so this workflow finds its own comment by a hidden
  marker instead of editing the bot's last comment.

## Things I noticed in the samples

- **The rule checks labels, not whether errors are handled.** A Return Documents
  shape labeled "Error" with nothing connected to it would pass, and so would a
  success path labeled "Complete (No Errors)". A stronger rule would require the
  error shape to be reachable from a failure route. The valid sample already meets
  that, so adding the rule wouldn't break it.
- **All three samples share one process ID** (`9a4d9681-…`). That's probably
  copy-paste in the samples. In production, two files with the same ID would
  overwrite each other on deploy, which a "no duplicate IDs" check would catch.

## Potential improvements

- **Make it a real gate.** A failed check doesn't stop anyone from merging. Mark it
  as required in branch protection for `main`. One gotcha: this workflow only runs
  when XML changes, so a required check would wait forever on other pull requests.
  The fix is to always run it and skip the work when no XML changed.
- **Close the bypass.** The rules live in the same repo, so one pull request could
  delete a blocklist entry and add the banned component, and the check would pass.
  Requiring code-owner review for `validation/` (CODEOWNERS) would close that. A
  stronger option is to load the rules from the base branch or a separate, locked repo.
- **Check existing processes when the rules change.** This check only looks at the
  files a pull request changes, so a new ban won't flag processes that are already
  merged. Running the validator on all of `xml-processes/` when the blocklist changes
  would list what's affected. What to do about them is a team decision, and it can
  depend on why the component was banned: fix everything now (a security issue), set
  a deadline and track the rest as tech debt, or open automatic fix pull requests when
  there's a drop-in replacement. A severity or deadline per blocklist entry could
  support that, warning first and failing later. Either way, the full check should
  report what's affected, not suddenly block unrelated pull requests.
- **One rule set for every repo.** Move the validator and rules into a shared,
  versioned workflow, so every integration repo enforces the same standards.
- **More rule options.** A severity per rule (warn or fail), exceptions that expire,
  and matching "error" as a whole word (today a "Terror Tunnel Tour" label counts).
  Also the two stronger rules under "Things I noticed in the samples."
- **Treat the XML as untrusted input.** Reject files with a DOCTYPE, and escape text
  from the XML before it goes into the comment, so a crafted label can't add
  formatting or `@mention` people.
- **Scale the report.** For a pull request with many files, put only the failures in
  the comment and link to the full summary, which also stays under GitHub's comment
  size limit. Some teams would skip the comment entirely when everything passes.
- **Inline annotations** on the failing line in the pull request diff.
- **Comments on fork pull requests**, using a follow-up `workflow_run` workflow.
- **Cancel outdated runs** when a new commit is pushed to the same pull request,
  which also stops two runs from racing to post the comment.
- **Alerts and trends.** Notify the team when the validator itself breaks (exit code
  `2`), and track which rules fail most often.
- **Run the tests in CI** with pinned test dependencies, and use Dependabot to keep
  the pinned actions up to date, with a waiting period so a bad release gets caught
  before it's adopted.
