"""PySide6 desktop application for the RebuildPilot repair workflow."""

from __future__ import annotations

import difflib
import shutil
import tempfile
from pathlib import Path

from .ai import PROVIDERS, build_advice_prompt, request_advice
from .repair import repair
from .repository import clone_repository
from .scanner import analyze
from .validator import validate
from .workspace import ProjectCandidate, discover_projects


def _load_qt():
    try:
        from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QPushButton,
            QProgressBar,
            QSplitter,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as error:
        raise RuntimeError(
            "PySide6 is not installed. Install the desktop extra with: "
            "python -m pip install 'rebuildpilot[desktop]'"
        ) from error
    return locals()


def _copy_tree(source: Path) -> Path:
    parent = Path(tempfile.mkdtemp(prefix="rebuildpilot-repair-"))
    destination = parent / source.name
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", ".venv", "venv", "node_modules"))
    return destination


def _tree_diffs(before: Path, after: Path) -> dict[str, str]:
    paths = sorted(
        {path.relative_to(before).as_posix() for path in before.rglob("*") if path.is_file()}
        | {path.relative_to(after).as_posix() for path in after.rglob("*") if path.is_file()}
    )
    diffs: dict[str, str] = {}
    for relative in paths:
        old_path, new_path = before / relative, after / relative
        old = old_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if old_path.exists() else []
        new = new_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if new_path.exists() else []
        if old != new:
            diffs[relative] = "".join(
                difflib.unified_diff(old, new, fromfile=f"a/{relative}", tofile=f"b/{relative}")
            )
    return diffs


def _tree_diff(before: Path, after: Path) -> str:
    diffs = _tree_diffs(before, after)
    return "\n".join(diffs.values()) or "No file changes were proposed."


def run() -> int:
    qt = _load_qt()
    QApplication = qt["QApplication"]
    app = QApplication.instance() or QApplication([])
    window = _MainWindow(qt)
    window.show()
    return app.exec()


class _MainWindow:
    def __init__(self, qt: dict[str, object]) -> None:
        self.qt = qt
        QMainWindow = qt["QMainWindow"]
        self.window = QMainWindow()
        self.window.setWindowTitle("RebuildPilot Desktop")
        self.window.resize(1120, 760)
        self.root: Path | None = None
        self.repair_copy: Path | None = None
        self._repair_diffs: dict[str, str] = {}
        self.last_report = None
        self._thread = None
        self._worker = None
        self._activity_timer = None
        self._activity_messages: tuple[str, ...] = ()
        self._activity_index = 0
        self._attempt_number = 0
        self._build()

    def show(self) -> None:
        self.window.show()

    def _build(self) -> None:
        QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QProgressBar, QSplitter, QTabWidget, QVBoxLayout, QWidget = (
            self.qt[name]
            for name in ("QCheckBox", "QComboBox", "QFileDialog", "QHBoxLayout", "QLabel", "QLineEdit", "QListWidget", "QMessageBox", "QPlainTextEdit", "QPushButton", "QProgressBar", "QSplitter", "QTabWidget", "QVBoxLayout", "QWidget")
        )
        container = QWidget()
        layout = QVBoxLayout(container)
        title = QLabel("RebuildPilot")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Deterministic diagnosis first. AI advice is opt-in and never runs automatically."))

        source_row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("Local project folder")
        open_button = QPushButton("Open local project")
        open_button.clicked.connect(self._open_local)
        source_row.addWidget(self.path)
        source_row.addWidget(open_button)
        layout.addLayout(source_row)

        github_row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://github.com/owner/repository")
        clone_button = QPushButton("Clone GitHub repository")
        clone_button.clicked.connect(self._clone)
        github_row.addWidget(self.url)
        github_row.addWidget(clone_button)
        layout.addLayout(github_row)

        self.projects = QListWidget()
        self.projects.setVisible(False)
        self.projects.itemDoubleClicked.connect(self._select_project)
        layout.addWidget(self.projects)

        self.status = QLabel("Choose a local folder or clone a GitHub repository.")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        action_row = QHBoxLayout()
        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.clicked.connect(self._analyze)
        self.repair_button = QPushButton("Repair in isolated workspace")
        self.repair_button.clicked.connect(self._repair)
        self.apply_button = QPushButton("Apply approved diff")
        self.apply_button.clicked.connect(self._apply_repair)
        self.rollback_button = QPushButton("Discard repair")
        self.rollback_button.clicked.connect(self._discard_repair)
        self.verify_button = QPushButton("Verify")
        self.verify_button.clicked.connect(self._verify)
        self.ai_button = QPushButton("Ask AI for advice")
        self.ai_button.clicked.connect(self._ask_ai)
        for button in (
            self.analyze_button,
            self.repair_button,
            self.apply_button,
            self.rollback_button,
            self.verify_button,
            self.ai_button,
        ):
            button.setEnabled(False)
            action_row.addWidget(button)
        layout.addLayout(action_row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Optional AI advisor:"))
        self.provider = QComboBox()
        self.provider.addItem("Disabled", "")
        for provider in PROVIDERS:
            self.provider.addItem(f"{provider.name} (free-tier limits apply)", provider.key)
        self.provider.currentIndexChanged.connect(self._refresh_action_state)
        settings_row.addWidget(self.provider)
        layout.addLayout(settings_row)
        self.full_project_review = QCheckBox("Send the whole readable project for cross-file AI review")
        self.full_project_review.setToolTip(
            "Includes readable source/configuration files after secret redaction. "
            "Ignored directories, environment files, binaries, and files beyond the context limit are excluded."
        )
        layout.addWidget(self.full_project_review)
        self.ai_context_status = QLabel("AI review is disabled until a provider and API key are configured.")
        layout.addWidget(self.ai_context_status)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.ai_output = QPlainTextEdit()
        self.ai_output.setReadOnly(True)
        self.history = QListWidget()
        self.history.setMaximumHeight(100)
        self.changed_files = QListWidget()
        self.changed_files.itemClicked.connect(self._show_selected_diff)
        self.diff_preview = QPlainTextEdit()
        self.diff_preview.setReadOnly(True)

        tabs = QTabWidget()
        tabs.addTab(self.output, "Analysis")
        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)
        ai_layout.addWidget(QLabel("AI review output (advisory only; no files are changed automatically)"))
        ai_layout.addWidget(self.ai_output)
        tabs.addTab(ai_tab, "AI Review")

        repair_tab = QWidget()
        repair_layout = QVBoxLayout(repair_tab)
        repair_layout.addWidget(QLabel("Repair history"))
        repair_layout.addWidget(self.history)
        repair_layout.addWidget(QLabel("Review changed files"))
        review = QSplitter()
        review.addWidget(self.changed_files)
        review.addWidget(self.diff_preview)
        review.setSizes([260, 760])
        repair_layout.addWidget(review)
        tabs.addTab(repair_tab, "Repair Review")
        layout.addWidget(tabs)
        self.window.setCentralWidget(container)

    def _set_busy(self, message: str, busy: bool) -> None:
        self.status.setText(message)
        self.progress.setVisible(busy)
        for button in (
            self.analyze_button,
            self.repair_button,
            self.apply_button,
            self.rollback_button,
            self.verify_button,
            self.ai_button,
        ):
            button.setEnabled(not busy and self.root is not None)
        if not busy:
            self.apply_button.setEnabled(self.repair_copy is not None)
            self.rollback_button.setEnabled(self.repair_copy is not None)
            self.ai_button.setEnabled(self.last_report is not None and bool(self.provider.currentData()))

    def _refresh_action_state(self) -> None:
        if self._thread is None:
            self.ai_button.setEnabled(self.last_report is not None and bool(self.provider.currentData()))

    def _start_task(
        self,
        label: str,
        messages: tuple[str, ...],
        operation: object,
        on_success: object,
    ) -> None:
        """Run a blocking engine operation away from the Qt GUI thread."""

        QObject, QThread, QTimer, Signal, Slot = (
            self.qt[name] for name in ("QObject", "QThread", "QTimer", "Signal", "Slot")
        )

        class Worker(QObject):
            finished = Signal(object)
            failed = Signal(str)

            def __init__(self) -> None:
                super().__init__()

            @Slot()
            def run(self) -> None:
                try:
                    self.finished.emit(operation())
                except Exception as error:
                    self.failed.emit(str(error))

        class CompletionProxy(QObject):
            finished = Signal(object)
            failed = Signal(str)

            def __init__(self) -> None:
                super().__init__(self_window)

            @Slot(object)
            def complete(self, result: object) -> None:
                self.finished.emit(result)

            @Slot(str)
            def fail(self, error: str) -> None:
                self.failed.emit(error)

        self_window = self.window
        self._set_busy(label, True)
        self._activity_messages = messages or (label,)
        self._activity_index = 0
        self._activity_timer = QTimer(self.window)
        self._activity_timer.timeout.connect(self._next_activity)
        self._activity_timer.start(700)
        thread = QThread(self.window)
        worker = Worker()
        proxy = CompletionProxy()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(proxy.complete)
        worker.failed.connect(proxy.fail)
        proxy.finished.connect(on_success)
        proxy.failed.connect(lambda error: self._task_failed(label, error))
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._task_finished)
        self._thread = thread
        self._worker = worker
        self._completion_proxy = proxy
        thread.start()

    def _next_activity(self) -> None:
        if not self._activity_messages:
            return
        message = self._activity_messages[self._activity_index % len(self._activity_messages)]
        self._activity_index += 1
        self.status.setText(f"{message}...")

    def _task_failed(self, label: str, error: str) -> None:
        self._set_busy(f"{label} failed: {error}", False)

    def _task_finished(self) -> None:
        if self._activity_timer is not None:
            self._activity_timer.stop()
            self._activity_timer.deleteLater()
            self._activity_timer = None
        self._thread = None
        self._worker = None
        self._completion_proxy = None

    def _open_local(self) -> None:
        selected = self.qt["QFileDialog"].getExistingDirectory(self.window, "Open project folder")
        if selected:
            self._load_workspace(Path(selected))

    def _load_workspace(self, workspace: Path) -> None:
        if self.repair_copy is not None:
            shutil.rmtree(self.repair_copy.parent, ignore_errors=True)
        self.root = None
        self.last_report = None
        self.repair_copy = None
        self._repair_diffs = {}
        self.changed_files.clear()
        self.diff_preview.clear()
        self.history.clear()
        self.changed_files.clear()
        self.diff_preview.clear()
        candidates = discover_projects(workspace)
        self.projects.clear()
        if not candidates:
            self.root = None
            self._set_busy("No project found in this folder.", False)
            self.qt["QMessageBox"].warning(self.window, "No project found", "Choose a folder containing a project manifest or source code.")
            return
        self._candidates = candidates
        self.projects.addItems([candidate.label for candidate in candidates])
        self.projects.setVisible(len(candidates) > 1)
        if len(candidates) == 1:
            self._choose_candidate(candidates[0])
        else:
            self.status.setText(f"Found {len(candidates)} projects. Double-click the project to analyze.")

    def _select_project(self, item: object) -> None:
        index = self.projects.row(item)
        self._choose_candidate(self._candidates[index])

    def _choose_candidate(self, candidate: ProjectCandidate) -> None:
        self.root = candidate.path
        self.path.setText(str(candidate.path))
        self._set_busy(f"Selected project: {candidate.path}", False)
        self.output.setPlainText("Project selected. Run Analyze to inspect it.")

    def _clone(self) -> None:
        source = self.url.text().strip()
        if not source:
            self.status.setText("Enter a GitHub repository URL.")
            return
        self._start_task(
            "Cloning repository",
            (
                "Connecting to GitHub",
                "Downloading repository objects",
                "Checking out the project",
            ),
            lambda: clone_repository(source),
            self._clone_finished,
        )

    def _clone_finished(self, workspace: object) -> None:
        self._load_workspace(workspace.root)
        self.status.setText(f"Cloned repository to {workspace.root}")

    def _analyze(self) -> None:
        if self.root is None:
            return
        root = self.root
        self._start_task(
            "Analyzing project",
            (
                "Reading project files",
                "Detecting project languages",
                "Checking dependency manifests",
                "Reviewing runtime and environment setup",
                "Prioritizing findings",
            ),
            lambda: analyze(root),
            self._analysis_finished,
        )

    def _analysis_finished(self, report: object) -> None:
        self.last_report = report
        self.output.setPlainText(report.summary + "\n\n" + "\n".join(
                f"[{finding.severity.value.upper()}] {finding.title}: {finding.remediation}"
                for finding in report.findings
            ))
        self._set_busy(f"Analysis complete: {report.score}/100", False)
        self._record_attempt(f"Analysis completed with score {report.score}/100")
        self.ai_context_status.setText(
            "Analysis ready. Select a provider and choose focused or whole-project AI review."
        )

    def _ask_ai(self) -> None:
        if self.root is None or self.last_report is None:
            self.status.setText("Analyze the project before requesting AI advice.")
            return
        provider_key = self.provider.currentData()
        provider = next((item for item in PROVIDERS if item.key == provider_key), None)
        if provider is None:
            self.status.setText("Select an AI provider first.")
            return
        include_all = self.full_project_review.isChecked()
        prompt, selected_files = build_advice_prompt(
            self.root,
            self.last_report,
            include_all_files=include_all,
        )
        preview = "\n".join(f"- {path}" for path in selected_files) or "- Finding summaries only"
        answer = self.qt["QMessageBox"].question(
            self.window,
            "Send selected context to AI?",
            f"RebuildPilot will send redacted findings and these files to {provider.name}:\n\n"
            f"{preview}\n\n"
            f"Review scope: {'whole readable project' if include_all else 'finding-related files'}.\n"
            f"{provider.free_tier_note}\n"
            "Do you approve this cloud request?",
        )
        if answer != self.qt["QMessageBox"].StandardButton.Yes:
            return
        self._start_task(
            f"Requesting advice from {provider.name}",
            ("Preparing redacted context", "Sending repair context", "Waiting for provider response"),
            lambda: request_advice(provider.key, prompt),
            self._ai_finished,
        )

    def _ai_finished(self, advice: str) -> None:
        self.ai_output.setPlainText(advice)
        self.ai_context_status.setText("AI review received. Treat recommendations as advisory and verify every change.")
        self._set_busy("AI advice received. No files were changed.", False)

    def _repair(self) -> None:
        if self.root is None:
            return
        root = self.root

        def prepare_repair() -> tuple[Path, dict[str, object], dict[str, str]]:
            repair_copy = _copy_tree(root)
            result = repair(repair_copy, apply=True, backup=True)
            return repair_copy, result, _tree_diffs(root, repair_copy)

        self._start_task(
            "Preparing isolated repair workspace",
            (
                "Copying the project into a disposable workspace",
                "Reviewing safe repair candidates",
                "Applying deterministic metadata repairs",
                "Preparing a reviewable diff",
            ),
            prepare_repair,
            self._repair_finished,
        )

    def _repair_finished(self, result: object) -> None:
        self.repair_copy, repair_result, diffs = result
        self._repair_diffs = diffs
        self.changed_files.clear()
        self.changed_files.addItems(list(diffs))
        self.diff_preview.setPlainText(next(iter(diffs.values()), "No file changes were proposed."))
        self.output.setPlainText(repair_result["summary"])
        self._attempt_number += 1
        self._record_attempt(
            f"Repair attempt {self._attempt_number}: {len(diffs)} changed file(s) proposed"
        )
        self._set_busy("Repair proposal ready. Review the diff before applying it.", False)

    def _show_selected_diff(self, item: object) -> None:
        self.diff_preview.setPlainText(self._repair_diffs.get(item.text(), "No diff available."))

    def _record_attempt(self, message: str) -> None:
        self.history.addItem(message)
        self.history.scrollToBottom()

    def _apply_repair(self) -> None:
        if self.root is None or self.repair_copy is None:
            return
        answer = self.qt["QMessageBox"].question(
            self.window,
            "Apply repair",
            "Apply the reviewed repair diff to the original project? Backups will be created for changed files.",
        )
        if answer != self.qt["QMessageBox"].StandardButton.Yes:
            return
        self._set_busy("Applying approved repair...", True)
        try:
            changed = 0
            backup_root = self.root / ".rebuildpilot-backups"
            for source in self.repair_copy.rglob("*"):
                if not source.is_file() or ".rebuildpilot-backups" in source.parts:
                    continue
                relative = source.relative_to(self.repair_copy)
                destination = self.root / relative
                if destination.exists() and destination.read_bytes() == source.read_bytes():
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    backup = backup_root / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup)
                shutil.copy2(source, destination)
                changed += 1
            self._set_busy(f"Applied {changed} approved file change(s).", False)
            self._record_attempt(f"Applied {changed} approved file change(s)")
            self._discard_repair(remove_copy=True)
        except OSError as error:
            self._set_busy(f"Could not apply repair: {error}", False)

    def _discard_repair(self, remove_copy: bool = True) -> None:
        if remove_copy and self.repair_copy is not None:
            shutil.rmtree(self.repair_copy.parent, ignore_errors=True)
        self.repair_copy = None
        if self.root is not None:
            self._set_busy("Repair workspace discarded. The original project was not changed.", False)

    def _verify(self) -> None:
        if self.repair_copy is None:
            self.status.setText("Run a repair proposal first.")
            return
        repair_copy = self.repair_copy
        self._start_task(
            "Verifying repair workspace",
            (
                "Running static checks",
                "Preparing the validation sandbox",
                "Running detected test commands",
                "Collecting verification results",
            ),
            lambda: validate(repair_copy),
            self._verification_finished,
        )

    def _verification_finished(self, result: object) -> None:
        self.output.appendPlainText("\n\n" + result.summary)
        self._record_attempt(f"Verification: {result.summary}")
        self._set_busy("Verification complete. The original project was not changed.", False)


__all__ = ["run"]
