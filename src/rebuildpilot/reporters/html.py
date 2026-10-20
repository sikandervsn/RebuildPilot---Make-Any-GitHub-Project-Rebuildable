"""Standalone HTML report rendering using only the Python standard library."""

from __future__ import annotations

from html import escape

from ..models import AnalysisReport, Finding


def _value_list(values: list[str]) -> str:
    if not values:
        return "<span class=\"muted\">None detected</span>"
    return ", ".join(f"<code>{escape(value)}</code>" for value in values)


def _location(finding: Finding) -> str:
    if not finding.file_path:
        return "Project-wide"
    suffix = f":{finding.line_number}" if finding.line_number else ""
    return f"{escape(finding.file_path)}{suffix}"


def render(report: AnalysisReport) -> str:
    """Render a self-contained report that can be opened without a server."""

    finding_rows = "\n".join(
        "<tr>"
        f"<td><code>{escape(finding.rule_id)}</code></td>"
        f"<td><span class=\"severity {escape(finding.severity.value)}\">{escape(finding.severity.value)}</span></td>"
        f"<td>{escape(finding.title)}<br><small>{escape(finding.explanation)}</small></td>"
        f"<td>{_location(finding)}</td>"
        f"<td>{escape(finding.remediation)}</td>"
        "</tr>"
        for finding in report.findings
    )
    if not finding_rows:
        finding_rows = '<tr><td colspan="5">No findings.</td></tr>'

    rationale = "\n".join(
        f"<li><strong>-{reason.points} points</strong> &mdash; "
        f"<code>{escape(reason.rule_id)}</code>: {escape(reason.explanation)}</li>"
        for reason in report.score_reasons
    ) or "<li>No score deductions were applied.</li>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RebuildPilot report</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
    body {{ margin: 0 auto; max-width: 1180px; padding: 2rem; line-height: 1.45; }}
    h1, h2 {{ line-height: 1.2; }}
    .summary, .score {{ border-radius: .5rem; padding: 1rem; background: #eef5ff; color: #123; }}
    .score {{ font-size: 1.25rem; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #bbc5d1; padding: .6rem; text-align: left; vertical-align: top; }}
    th {{ background: #e8edf3; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    .severity {{ border-radius: .25rem; padding: .15rem .35rem; font-weight: 700; }}
    .critical {{ background: #ffd6d6; color: #8b0000; }}
    .high {{ background: #ffe5c2; color: #713900; }}
    .medium {{ background: #fff5bf; color: #5b4a00; }}
    .low {{ background: #dff3df; color: #174d17; }}
    .info {{ background: #e2e8f0; color: #243447; }}
    .passed {{ background: #dff3df; color: #174d17; }}
    .failed {{ background: #ffd6d6; color: #8b0000; }}
    .skipped {{ background: #e2e8f0; color: #243447; }}
    .muted {{ opacity: .7; }}
    small {{ opacity: .8; }}
    @media (prefers-color-scheme: dark) {{
      .summary, .score {{ background: #1d334d; color: #eef5ff; }}
      th {{ background: #27384a; }}
    }}
  </style>
</head>
<body>
  <h1>RebuildPilot report</h1>
  <p class="score">Reproducibility score: {report.score}/100</p>
  <div class="summary"><strong>Summary:</strong> {escape(report.summary)}</div>
  <ul>
    <li><strong>Target:</strong> <code>{escape(report.target_path)}</code></li>
    <li><strong>Project type:</strong> {escape(report.project_type)}</li>
    <li><strong>Languages:</strong> {_value_list(report.languages)}</li>
    <li><strong>Git repository:</strong> {'yes' if report.git_repository else 'no'}</li>
  </ul>

  <h2>Detected project signals</h2>
  <ul>
    <li>Dependency manifests: {_value_list(report.dependency_manifests)}</li>
    <li>Dependency lockfiles: {_value_list(report.dependency_lockfiles)}</li>
    <li>Runtime/version files: {_value_list(report.runtime_files)}</li>
    <li>Environment files: {_value_list(report.environment_files)}</li>
    <li>Runtime definitions: {_value_list(report.runtime_definitions)}</li>
    <li>Test configuration: {_value_list(report.test_configuration)}</li>
    <li>Likely test commands: {_value_list(report.likely_test_commands)}</li>
    <li>Environment variables used: {_value_list(report.environment_variables_used)}</li>
    <li>Environment variables documented: {_value_list(report.environment_variables_documented)}</li>
    <li>ML frameworks: {_value_list(report.ml_frameworks)}</li>
    <li>Model artifacts: {_value_list(report.model_artifacts)}</li>
    <li>Dataset artifacts: {_value_list(report.dataset_artifacts)}</li>
    <li>ML entry points: {_value_list(report.ml_entrypoints)}</li>
  </ul>

  <h2>Findings</h2>
  <table>
    <thead><tr><th>Rule</th><th>Severity</th><th>Finding</th><th>Location</th><th>Recommended remediation</th></tr></thead>
    <tbody>{finding_rows}</tbody>
  </table>

  <h2>Score rationale</h2>
  <ul>{rationale}</ul>
</body>
</html>
"""
