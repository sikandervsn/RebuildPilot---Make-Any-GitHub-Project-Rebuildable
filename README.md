# RebuildPilot

RebuildPilot is a deterministic CLI that inspects a local project for the files and instructions needed to rebuild it on another machine. It can also apply a small, explicit set of safe metadata repairs or perform a clean rebuild in a disposable copy. It does not call an external AI service.

The score is a risk indicator, not a completeness judgment. Rules are contextual: a machine-specific path in production code is more serious than one in a test or fixture, and a missing lockfile is an advisory application/library risk rather than proof that a project is broken. A project can be complete and useful while still receiving recommendations.

## Features

- Detects project type, likely languages, dependency manifests, and lockfiles.
- Checks runtime/version declarations, environment-variable templates, and reproducible runtime definitions.
- Finds test configuration and likely test commands.
- Reports machine-specific paths, unreadable or malformed inputs, missing Git metadata, and incomplete README setup instructions.
- Produces an explainable reproducibility score from 0 to 100.
- Writes Markdown, JSON, or self-contained HTML reports and exits non-zero when critical findings are present.
- Validates detected test commands in a temporary copy of the target, with optional Docker build verification.
- Runs recognized dependency setup commands and tests in a disposable copy with `rebuild`.
- Creates a safe `fix --plan` remediation plan or applies bounded metadata repairs with `fix --apply`.

## Supported checks

The MVP recognizes common Python, JavaScript/TypeScript, Go, Rust, Java, Ruby, and PHP manifests. It checks files such as `pyproject.toml`, `requirements.txt`, `package.json`, `go.mod`, `Cargo.toml`, lockfiles, `.python-version`, `.nvmrc`, Docker/Compose files, `.env.example`, README files, and common test configurations. Directory traversal skips `.git`, `node_modules`, virtual environments, caches, build output, and coverage output.

Computer-vision and machine-learning projects receive additional reproducibility checks. RebuildPilot detects OpenCV, scikit-learn, random-forest, NumPy, pandas, PyTorch, TensorFlow, and Joblib usage; serialized model artifacts; dataset artifacts; common training/inference entry points; missing dependency declarations; undocumented model-loading paths; missing deterministic seeds; and missing dataset provenance. These checks do not diagnose medical conditions or judge model quality. They identify the setup, versioning, data, and artifact information required to rerun an ML workflow after the original environment changes.

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
rebuildpilot
rebuildpilot chat
rebuildpilot analyze ./path-to-project
rebuildpilot analyse ./path-to-project
rebuildpilot analyze ./path-to-project --format markdown
rebuildpilot analyze ./path-to-project --format json
rebuildpilot analyze ./path-to-project --format html --output ./reports
rebuildpilot validate ./path-to-project
rebuildpilot validate ./path-to-project --docker
rebuildpilot rebuild ./path-to-project --format markdown
rebuildpilot fix ./path-to-project --plan
rebuildpilot fix ./path-to-project --apply --backup
rebuildpilot dashboard
rebuildpilot onboard https://github.com/owner/project.git
rebuildpilot diff ./cloned-project
rebuildpilot commit ./cloned-project -m "Improve reproducibility"
rebuildpilot publish ./cloned-project --pull-request --confirm
```

Running `rebuildpilot` from a project folder opens an interactive terminal
workbench. It starts in the current directory, so the Windows workflow can be
as simple as opening a folder in Terminal and typing `rebuildpilot`. Use the
Up/Down arrow keys and Enter to select analysis, safe repairs, sandbox
validation, or a disposable clean rebuild. While work is running, one status
line cycles through comments such as “Reading project files,” “Checking
dependency manifests,” and “Running detected test commands.” When input is
redirected, a typed number fallback remains available.

Before analysis, RebuildPilot checks the selected workspace. Empty folders and
folders containing no recognizable source code or project manifest are
rejected with a clear message. If a workspace contains multiple project
roots, RebuildPilot lists them (including their detected manifests) and asks
which project to analyze first instead of silently choosing one. Use
**Change project folder** to select another workspace or project.

Without `--output`, the report is written to standard output. With `--output`, RebuildPilot creates the requested directory and writes the corresponding report file: `rebuildpilot-report.md`, `rebuildpilot-report.json`, or `rebuildpilot-report.html`. Validation and remediation use `rebuildpilot-validation.*` and `rebuildpilot-fix-plan.*` filenames. An output directory inside the analyzed project is rejected.

`validate` first performs the static analysis, then runs recognized test commands such as `python -m pytest` in a temporary copy so test caches and generated files do not change the target. Missing test executables are failures, not successful skips. `--skip-tests` performs only static validation. `--docker` is opt-in because a Docker build can require a local daemon and base images.

`rebuild` copies the target to a temporary directory, prepares recognized dependencies there, and runs detected tests there. Python projects get a temporary virtual environment so `pip install` never modifies the tool's environment or the target. The command fails unless static analysis has no critical finding, dependency setup succeeds, and at least one detected test command passes.

`fix --plan` only turns findings into ordered recommendations. `fix --apply` is deliberately narrower: it can create or update a non-secret `.env.example` template and create `.python-version` when project metadata contains one exact Python major/minor version. It never rewrites source code, fabricates lockfiles, initializes Git, or invents documentation. `--backup` writes non-overwriting `.rebuildpilot.bak` files before changing existing files. Unresolved findings remain in the repair report.

The interactive **Fix safe problems and verify** action applies these same
bounded repairs with backups, re-analyzes the project, and validates it. A
score of 100% cannot be promised automatically: source-code bugs, missing
credentials or services, incompatible native dependencies, and unresolved
dependency ranges require project-specific decisions. Remaining critical and
high findings are shown explicitly rather than being hidden behind a
success-looking result.

`analyze` returns exit code `1` when at least one critical finding exists. `validate` returns `1` when a requested check fails. All commands return `2` for an invalid target path or report destination.

## Dashboard

The local dashboard provides a GUI workflow on top of the same analysis engine used by the CLI:

```bash
rebuildpilot dashboard
```

It opens a browser window on `http://127.0.0.1:8765` and supports:

- Opening a local project folder or a ZIP upload.
- Guided analysis with score, severity counts, and prioritized findings.
- A developer workbench view for inspecting the result as structured JSON.
- Safe-fix plan previews.
- Validation in a temporary copy.
- Clean rebuild verification in a disposable copy.

The dashboard is local by default and binds only to `127.0.0.1`. Use `--no-browser` for scripted startup or `--port 0` to select a free port. Uploaded ZIP archives are extracted into a temporary workspace with archive path traversal checks. The current dashboard does not expose the local filesystem or run arbitrary user-provided command strings.

The Windows executable distribution will package this dashboard command together with the CLI. Until release artifacts are published, run it from the Python installation described above.

## Desktop application

The native desktop workflow uses PySide6 and does not open a browser:

```powershell
python -m pip install --no-build-isolation --no-deps ".[desktop]"
rebuildpilot desktop
```

The first desktop slice supports opening a local project, cloning a GitHub
repository, selecting among multiple detected project roots, deterministic
analysis, isolated safe repair proposals, verification, diff review, and
explicit approval before changes are copied back. The original project remains
unchanged until **Apply approved diff** is confirmed; changed files receive
backups under `.rebuildpilot-backups`.

Repair proposals are shown in a file-by-file review panel, and each analysis,
repair, apply, discard, and verification attempt is recorded in the repair
history. Verification can be repeated against the isolated workspace before
the original project is changed.

Cloud AI is disabled by default. The desktop settings expose Gemini, Groq, and
OpenRouter as opt-in advisors. Configure the provider's API key through its
environment variable and review the privacy implications before sending any
selected project context. The deterministic engine does not call an AI
provider automatically. After analysis, the desktop **AI Review** tab supports
focused review of finding-related files or an explicit whole-readable-project
review for cross-file diagnosis. Whole-project review excludes `.env` files,
generated/dependency directories, binaries, and unreadable files, redacts
common secret assignments, and applies a bounded context limit. AI output is
advisory only; it does not modify files.

## GitHub repository workflow

`onboard` is the end-to-end repository workflow. It accepts a GitHub HTTPS or SSH clone URL, clones into an isolated temporary workspace, creates the `rebuildpilot/fix-reproducibility` branch, analyzes the project, applies only bounded safe repairs with backups, and runs the disposable rebuild verification:

```bash
rebuildpilot onboard https://github.com/owner/project.git
```

The command keeps the workspace so changes can be reviewed and published with separate explicit commands:

```bash
rebuildpilot diff C:\path\to\workspace\project
rebuildpilot commit C:\path\to\workspace\project -m "Improve reproducibility"
rebuildpilot publish C:\path\to\workspace\project --pull-request --confirm
```

Publishing always requires `--confirm`. The default is a new repair branch rather than a direct push to the base branch. `--pull-request` uses the GitHub CLI (`gh`) to open a pull request after pushing; authenticate it separately with `gh auth login`. RebuildPilot never stores GitHub credentials in the project or report.

The dashboard exposes the same flow through **Clone and onboard**, **Review changes**, and **Publish to GitHub**. Publishing is available only for repositories cloned by the current dashboard session and still requires a browser confirmation. Remote setup and execution of untrusted code should be run with Docker isolation before deploying this workflow as a hosted service.

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

`src/rebuildpilot/scanner.py` inventories the target once, skips known generated directories, and passes an immutable `ScanContext` to focused detectors under `detectors/`. Typed Pydantic models in `models.py` carry findings, validation checks, and reports. `scoring.py` applies fixed severity deductions. Reporters under `reporters/` serialize reports as Markdown, JSON, or HTML. `validator.py` executes only recognized local commands in a temporary copy, `rebuild.py` performs dependency setup and tests in a disposable copy, `repair.py` applies bounded metadata changes, and `planner.py` produces plan-only recommendations. `cli.py` handles command validation, output, and exit codes.

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

The sample project is intentionally incomplete, so its analysis is expected to report findings and exit with code `1` because it contains a deliberate absolute path. `fix --apply` can repair only its environment template and Python pin; the absolute path and missing dependency lockfile remain intentionally unresolved. The healthy fixture has no critical or high-severity findings and passes local validation; a fixture stored outside Git may still receive the medium Git metadata reminder.

## Limitations

RebuildPilot uses deterministic file names, regular expressions, and lightweight manifest parsing. `rebuild` supports only the recognized setup commands for Python, Node, Go, and Rust; those commands may require a local toolchain, package cache, or network access and are never run during the offline test suite. It does not prove every deployment path or resolve every package-manager format. It does not inspect remote repositories or infer undocumented behavior. A passing scan, validation, or clean rebuild is evidence for the exercised path, not a guarantee that every deployment will succeed.
