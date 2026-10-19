# RebuildPilot

RebuildPilot is a deterministic CLI that inspects a local project for the files and instructions needed to rebuild it on another machine. It does not modify the inspected project and does not call an external AI service.

## Features

- Detects project type, likely languages, dependency manifests, and lockfiles.
- Checks runtime/version declarations, environment-variable templates, and reproducible runtime definitions.
- Finds test configuration and likely test commands.
- Reports machine-specific paths, unreadable or malformed inputs, missing Git metadata, and incomplete README setup instructions.
- Produces an explainable reproducibility score from 0 to 100.
- Writes Markdown, JSON, or self-contained HTML reports and exits non-zero when critical findings are present.
- Validates detected test commands in a temporary copy of the target, with optional Docker build verification.
- Creates a safe `fix --plan` remediation plan without changing the inspected project.

## Supported checks

The MVP recognizes common Python, JavaScript/TypeScript, Go, Rust, Java, Ruby, and PHP manifests. It checks files such as `pyproject.toml`, `requirements.txt`, `package.json`, `go.mod`, `Cargo.toml`, lockfiles, `.python-version`, `.nvmrc`, Docker/Compose files, `.env.example`, README files, and common test configurations. Directory traversal skips `.git`, `node_modules`, virtual environments, caches, build output, and coverage output.

## Installation

Python 3.12 is required. From a clean clone:

```bash
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-build-isolation --no-deps .
```

The lockfile pins direct and runtime dependencies. `.python-version` records the intended Python minor version.

## CLI usage

```bash
rebuildpilot --help
rebuildpilot analyze ./path-to-project
rebuildpilot analyze ./path-to-project --format markdown
rebuildpilot analyze ./path-to-project --format json
rebuildpilot analyze ./path-to-project --format html --output ./reports
rebuildpilot validate ./path-to-project
rebuildpilot validate ./path-to-project --docker
rebuildpilot fix ./path-to-project --plan
```

Without `--output`, the report is written to standard output. With `--output`, RebuildPilot creates the requested directory and writes the corresponding report file: `rebuildpilot-report.md`, `rebuildpilot-report.json`, or `rebuildpilot-report.html`. Validation and remediation use `rebuildpilot-validation.*` and `rebuildpilot-fix-plan.*` filenames. An output directory inside the analyzed project is rejected.

`validate` first performs the static analysis, then runs recognized test commands such as `python -m pytest` in a temporary copy so test caches and generated files do not change the target. `--skip-tests` performs only static validation. `--docker` is opt-in because a Docker build can require a local daemon and base images.

`fix --plan` only turns findings into ordered recommendations. It never edits, installs dependencies in, or executes commands from the target. The command returns `1` when the analysis contains a critical finding.

`analyze` returns exit code `1` when at least one critical finding exists. `validate` returns `1` when a requested check fails. All commands return `2` for an invalid target path or report destination.

## Development setup

```bash
python -m pip install -r requirements.lock
python -m pip install --no-build-isolation --no-deps .
python -m pytest
```

The single offline test command is `python -m pytest`; its fixture projects are stored under `tests/fixtures/` and do not require network access.

## Docker

Build the CLI image and run its help:

```bash
docker build --tag rebuildpilot .
docker run --rm rebuildpilot --help
```

To analyze a host project without allowing writes to it, mount it read-only:

```bash
docker run --rm -v "$PWD:/project:ro" rebuildpilot analyze /project --format html
```

In Windows PowerShell, use:

```powershell
docker run --rm -v "${PWD.Path}:/project:ro" rebuildpilot analyze /project --format html
```

## Deployment

Publish the verified image to a registry you control, replacing the placeholder registry and organization:

```bash
docker build --tag ghcr.io/your-org/rebuildpilot:0.1.0 .
docker push ghcr.io/your-org/rebuildpilot:0.1.0
```

Run the published image with a read-only project mount and the same `analyze`, `validate`, or `fix --plan` arguments shown above.

## Architecture

`src/rebuildpilot/scanner.py` inventories the target once, skips known generated directories, and passes an immutable `ScanContext` to focused detectors under `detectors/`. Typed Pydantic models in `models.py` carry findings, validation checks, and reports. `scoring.py` applies fixed severity deductions. Reporters under `reporters/` serialize reports as Markdown, JSON, or HTML. `validator.py` executes only recognized local commands in a temporary copy, and `planner.py` produces plan-only recommendations. `cli.py` handles command validation, output, and exit codes.

## Sample output

```text
Reproducibility score: 28/100
critical: machine-specific absolute path detected
high: dependency manifest has no lockfile
medium: environment template is incomplete
```

The exact report includes rule IDs, locations, explanations, remediations, and score rationale.

## Clean-clone verification

```bash
cd rebuildpilot-check
python --version
python -m pip install -r requirements.lock
python -m pip install --no-build-isolation --no-deps .
python -m pytest
python -m rebuildpilot --help
python -m rebuildpilot analyze tests/fixtures/sample-project --format markdown
python -m rebuildpilot analyze tests/fixtures/sample-project --format json
python -m rebuildpilot validate tests/fixtures/healthy-project --format json
```

The sample project is intentionally incomplete, so its analysis is expected to report findings and exit with code `1` because it contains a deliberate absolute path. The healthy fixture has no critical or high-severity findings and passes local validation; a fixture stored outside Git may still receive the medium Git metadata reminder.

## Limitations

RebuildPilot uses deterministic file names, regular expressions, and lightweight manifest parsing. Static analysis does not install or execute the target project's dependencies. `validate` executes detected test commands only in a temporary copy and can optionally build a Dockerfile when Docker is available; it does not prove every deployment path or resolve every package-manager format. It does not inspect remote repositories or infer undocumented behavior. A passing scan or validation is evidence, not a guarantee that every clean-machine build will succeed.
