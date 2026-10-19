"""Human-readable Markdown report rendering."""

from __future__ import annotations

from ..models import AnalysisReport, Finding


def _bullet_values(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "None detected"


def _finding_location(finding: Finding) -> str:
    if not finding.file_path:
        return "Project-wide"
    if finding.line_number:
        return f"`{finding.file_path}:{finding.line_number}`"
    return f"`{finding.file_path}`"


def render(report: AnalysisReport) -> str:
    lines = [
        "# RebuildPilot report",
        "",
        f"- **Target:** `{report.target_path}`",
        f"- **Project type:** {report.project_type}",
        f"- **Languages:** {_bullet_values(report.languages)}",
        f"- **Reproducibility score:** **{report.score}/100**",
        f"- **Git repository:** {'yes' if report.git_repository else 'no'}",
        "",
        f"**Summary:** {report.summary}",
        "",
        "## Detected project signals",
        "",
        f"- Dependency manifests: {_bullet_values(report.dependency_manifests)}",
        f"- Dependency lockfiles: {_bullet_values(report.dependency_lockfiles)}",
        f"- Runtime/version files: {_bullet_values(report.runtime_files)}",
        f"- Environment files: {_bullet_values(report.environment_files)}",
        f"- Runtime definitions: {_bullet_values(report.runtime_definitions)}",
        f"- Test configuration: {_bullet_values(report.test_configuration)}",
        f"- Likely test commands: {_bullet_values(report.likely_test_commands)}",
        f"- Environment variables used: {_bullet_values(report.environment_variables_used)}",
        f"- Environment variables documented: {_bullet_values(report.environment_variables_documented)}",
        "",
        "## Findings",
        "",
    ]
    if report.findings:
        lines.extend(
            [
                "| Rule | Severity | Title | Location | Recommended remediation |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for finding in report.findings:
            remediation = finding.remediation.replace("|", "\\|")
            title = finding.title.replace("|", "\\|")
            lines.append(
                f"| `{finding.rule_id}` | **{finding.severity.value}** | {title} | {_finding_location(finding)} | {remediation} |"
            )
    else:
        lines.append("No findings.")
    lines.extend(["", "## Score rationale", ""])
    if report.score_reasons:
        for reason in report.score_reasons:
            lines.append(f"- **-{reason.points} points** - `{reason.rule_id}`: {reason.explanation}")
    else:
        lines.append("No score deductions were applied.")
    if report.unreadable_files:
        lines.extend(["", "## Unreadable files", ""])
        lines.extend(f"- `{path}`" for path in report.unreadable_files)
    lines.append("")
    return "\n".join(lines)
