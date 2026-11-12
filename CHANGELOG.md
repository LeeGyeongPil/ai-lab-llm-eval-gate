# Changelog

## 0.2.2

- Documentation: README screenshots are now taken per display language (English in `README.md`, Korean in `README.ko.md`). The tool itself is unchanged.

## 0.2.1

- Fixed: the test suite failed on machines whose locale is not Korean (for example the GitHub Actions runner, `LANG=C.UTF-8`). Every test now pins the output language, so the suite passes under any `LANG`. The tool's own behaviour is unchanged.

## 0.2.0

- Added: English and Korean output. Pick it with `--lang en|ko`, the `EVALGATE_LANG` environment variable, or `LC_ALL` / `LC_MESSAGES` / `LANG` (anything that is not Korean falls back to English).
- Added: the CLI messages, errors, `--help`, and the HTML / Markdown reports follow the chosen language.
- Unchanged: JSON keys, exit codes, the judge prompt and the recording format.

## 0.1.1

- Fixed: record mode now warns when it never calls the model.
- Documentation: English README as the default, offline quick start, corrected experiment notes.

## 0.1.0

- First release: scorers (exact, regex, contains, similarity, LLM judge), baseline comparison with standard error, gate with exit codes, offline mock mode, HTML report.
