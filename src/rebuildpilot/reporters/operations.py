"""Report renderers for validation results and remediation plans."""

from __future__ import annotations

from html import escape

from ..models import RemediationPlan, ValidationReport
from . import html as html_report
from . import markdown as markdown_report


def validation_markdown(report: ValidationReport) -> str:
    lines = [
        "# RebuildPilot validation",
        "",
        f"- **Target:** `{report.target_path}`",
        f"- **Result:** **{'passed' if report.passed else 'failed'}**",
        "",
        f"**Summary:** {report.summary}",
        "",
        "## Checks",
        "",
        "| Check | Status | Command | Details |",
        "| --- | --- | --- | --- |",
    ]
    for check in report.checks:
        details = check.details.replace("|", "\\|").replace("\n", "<br>")
        command = f"`{check.command}`" if check.command else "-"
        lines.append(f"| {check.name} | **{check.status.value}** | {command} | {details} |")
    lines.extend(["", "## Static analysis", "", markdown_report.render(report.analysis)])
    return "\n".join(lines)


def validation_html(report: ValidationReport) -> str:
    checks = "\n".join(
        "<tr>"
        f"<td>{escape(check.name)}</td>"
        f"<td><span class=\"severity {escape(check.status.value)}\">{escape(check.status.value)}</span></td>"
        f"<td><code>{escape(check.command or '')}</code></td>"
        f"<td>{escape(check.details).replace(chr(10), '<br>')}</td>"
        "</tr>"
        for check in report.checks
    )
    analysis_html = html_report.render(report.analysis)
    insertion = f"""
  <h2>Validation checks</h2>
  <p class=\"summary\"><strong>Result:</strong> {escape('passed' if report.passed else 'failed')} &mdash; {escape(report.summary)}</p>
  <table><thead><tr><th>Check</th><th>Status</th><th>Command</th><th>Details</th></tr></thead><tbody>{checks}</tbody></table>
"""
    return analysis_html.replace("<body>\n", f"<body>\n{insertion}", 1).replace(
        "<title>RebuildPilot report</title>", "<title>RebuildPilot validation</title>", 1
    )


def plan_markdown(plan: RemediationPlan) -> str:
    lines = [
        "# RebuildPilot remediation plan",
        "",
        f"- **Target:** `{plan.target_path}`",
        "- **Mode:** plan only; no files were changed",
        "",
        f"**Summary:** {plan.summary}",
        "",
        "## Recommended steps",
        "",
    ]
    if plan.items:
        lines.extend(["| Priority | Rule | Severity | Location | Recommendation |", "| ---: | --- | --- | --- | --- |"])
        for item in plan.items:
            location = f"`{item.file_path}`" if item.file_path else "Project-wide"
            recommendation = item.recommendation.replace("|", "\\|")
            lines.append(
                f"| {item.priority} | `{item.rule_id}` | **{item.severity.value}** | {location} | {recommendation} |"
            )
    else:
        lines.append("No actionable findings.")
    lines.extend(["", "## Analysis score", "", f"**{plan.analysis.score}/100** - {plan.analysis.summary}", ""])
    return "\n".join(lines)


def plan_html(plan: RemediationPlan) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{item.priority}</td>"
        f"<td><code>{escape(item.rule_id)}</code></td>"
        f"<td><span class=\"severity {escape(item.severity.value)}\">{escape(item.severity.value)}</span></td>"
        f"<td>{escape(item.file_path or 'Project-wide')}</td>"
        f"<td>{escape(item.recommendation)}</td>"
        "</tr>"
        for item in plan.items
    ) or '<tr><td colspan="5">No actionable findings.</td></tr>'
    analysis_html = html_report.render(plan.analysis)
    insertion = f"""
  <h2>Plan-only remediation</h2>
  <p class=\"summary\"><strong>No files were changed.</strong> {escape(plan.summary)}</p>
  <table><thead><tr><th>Priority</th><th>Rule</th><th>Severity</th><th>Location</th><th>Recommendation</th></tr></thead><tbody>{rows}</tbody></table>
"""
    return analysis_html.replace("<body>\n", f"<body>\n{insertion}", 1).replace(
        "<title>RebuildPilot report</title>", "<title>RebuildPilot remediation plan</title>", 1
    )
