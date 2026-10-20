"""Markdown and HTML reports for repairs and clean rebuild attempts."""

from __future__ import annotations

from html import escape
from typing import Any

from ..rebuild import RebuildResult


def _status(value: object) -> str:
    return getattr(value, "value", str(value))


def _step_rows(result: RebuildResult) -> list[tuple[str, str, str, str]]:
    return [
        (
            step.name,
            _status(step.status),
            step.command or "-",
            step.details,
        )
        for step in result.checks
    ]


def _markdown_details(details: str) -> str:
    return details.replace("|", "\\|").replace("\n", "<br>")


def rebuild_markdown(result: RebuildResult) -> str:
    lines = [
        "# RebuildPilot clean rebuild",
        "",
        f"- **Target:** `{result.target_path}`",
        f"- **Result:** **{'passed' if result.passed else 'failed'}**",
        "",
        f"**Summary:** {result.summary}",
        "",
        "## Checks",
        "",
        "| Check | Status | Command | Details |",
        "| --- | --- | --- | --- |",
    ]
    for name, status, command, details in _step_rows(result):
        lines.append(f"| {name} | **{status}** | `{command}` | {_markdown_details(details)} |")
    lines.extend(
        [
            "",
            "## Setup plan",
            "",
        ]
    )
    if result.setup_plan:
        lines.extend(["| Setup | Command |", "| --- | --- |"])
        lines.extend(f"| {plan.name} | `{plan.command}` |" for plan in result.setup_plan)
    else:
        lines.append("No supported dependency setup command was detected.")
    lines.extend(["", "## Static analysis", "", result.analysis.summary, ""])
    return "\n".join(lines)


def rebuild_html(result: RebuildResult) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(name)}</td>"
        f"<td><span class=\"status {_status(status)}\">{escape(status)}</span></td>"
        f"<td><code>{escape(command)}</code></td>"
        f"<td>{escape(details).replace(chr(10), '<br>')}</td>"
        "</tr>"
        for name, status, command, details in _step_rows(result)
    )
    setup = "\n".join(
        f"<li><strong>{escape(plan.name)}</strong>: <code>{escape(plan.command)}</code></li>"
        for plan in result.setup_plan
    ) or "<li>No supported dependency setup command was detected.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RebuildPilot clean rebuild</title>
  <style>
    :root {{ font-family: system-ui, sans-serif; color-scheme: light dark; }}
    body {{ max-width: 1180px; margin: 0 auto; padding: 2rem; line-height: 1.45; }}
    .summary {{ padding: 1rem; border-radius: .5rem; background: #eef5ff; color: #123; }}
    table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
    th, td {{ border: 1px solid #bbc5d1; padding: .6rem; text-align: left; vertical-align: top; }}
    th {{ background: #e8edf3; }}
    code {{ font-family: ui-monospace, Consolas, monospace; }}
    .status {{ font-weight: 700; padding: .15rem .35rem; border-radius: .25rem; }}
    .passed {{ background: #dff3df; color: #174d17; }}
    .failed {{ background: #ffd6d6; color: #8b0000; }}
    .skipped {{ background: #e2e8f0; color: #243447; }}
  </style>
</head>
<body>
  <h1>RebuildPilot clean rebuild</h1>
  <p class="summary"><strong>Result:</strong> {'passed' if result.passed else 'failed'} - {escape(result.summary)}</p>
  <p><strong>Target:</strong> <code>{escape(result.target_path)}</code></p>
  <h2>Checks</h2>
  <table><thead><tr><th>Check</th><th>Status</th><th>Command</th><th>Details</th></tr></thead>
  <tbody>{rows}</tbody></table>
  <h2>Setup plan</h2>
  <ul>{setup}</ul>
  <h2>Static analysis</h2>
  <p>{escape(result.analysis.summary)}</p>
</body>
</html>
"""


def repair_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# RebuildPilot repair",
        "",
        f"- **Target:** `{payload['target_path']}`",
        f"- **Mode:** **{'apply' if payload['apply_requested'] else 'plan'}**",
        f"- **Score:** **{payload['before_score']}/100** -> **{payload['after_score']}/100**",
        "",
    ]
    changed = payload["changed_files"]
    planned = payload["planned_changes"]
    if changed:
        lines.extend(["## Changed files", "", *[f"- `{path}`" for path in changed], ""])
    elif planned:
        lines.extend(["## Safe changes available", "", *[f"- `{item['path']}` - {item['description']}" for item in planned], ""])
    else:
        lines.extend(["## Safe changes", "", "No bounded metadata repairs were available.", ""])
    lines.extend(["## Remaining findings", ""])
    skipped = payload["skipped_findings"]
    if skipped:
        lines.extend(["| Rule | Severity | Location | Reason |", "| --- | --- | --- | --- |"])
        for item in skipped:
            reason = str(item["reason"]).replace("|", "\\|")
            lines.append(f"| `{item['rule_id']}` | **{item['severity']}** | `{item.get('file_path') or 'Project-wide'}` | {reason} |")
    else:
        lines.append("No findings were left in the bounded repair result.")
    lines.append("")
    return "\n".join(lines)


def repair_html(payload: dict[str, Any]) -> str:
    changed = "".join(f"<li><code>{escape(path)}</code></li>" for path in payload["changed_files"])
    planned_changes = payload["planned_changes"]
    planned = "".join(
        f"<li><code>{escape(str(item['path']))}</code> - {escape(str(item['description']))}</li>"
        for item in planned_changes
    )
    remaining = "".join(
        "<tr>"
        f"<td><code>{escape(str(item['rule_id']))}</code></td>"
        f"<td><span class=\"status {_status(item['severity'])}\">{escape(str(item['severity']))}</span></td>"
        f"<td>{escape(str(item.get('file_path') or 'Project-wide'))}</td>"
        f"<td>{escape(str(item['reason']))}</td>"
        "</tr>"
        for item in payload["skipped_findings"]
    ) or '<tr><td colspan="4">No findings were left.</td></tr>'
    if changed:
        safe_section = "".join(f"<li><code>{escape(path)}</code></li>" for path in changed)
    elif planned_changes:
        safe_section = "".join(
            f"<li><code>{escape(str(item['path']))}</code> - {escape(str(item['description']))}</li>"
            for item in planned_changes
        )
    else:
        safe_section = "<li>No bounded metadata repairs were available.</li>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RebuildPilot repair</title>
<style>
body {{ max-width: 1100px; margin: 0 auto; padding: 2rem; font-family: system-ui, sans-serif; line-height: 1.45; }}
.summary {{ padding: 1rem; background: #eef5ff; color: #123; border-radius: .5rem; }}
table {{ width: 100%; border-collapse: collapse; }} th, td {{ border: 1px solid #bbc5d1; padding: .6rem; text-align: left; vertical-align: top; }}
code {{ font-family: ui-monospace, Consolas, monospace; }} .status {{ padding: .15rem .35rem; border-radius: .25rem; font-weight: 700; }}
.critical {{ background: #ffd6d6; color: #8b0000; }} .high {{ background: #ffe5c2; color: #713900; }} .medium {{ background: #fff5bf; color: #5b4a00; }} .info {{ background: #e2e8f0; color: #243447; }}
</style></head><body>
<h1>RebuildPilot repair</h1>
<p class="summary"><strong>Mode:</strong> {'apply' if payload['apply_requested'] else 'plan'} - score {payload['before_score']}/100 -> {payload['after_score']}/100</p>
<p><strong>Target:</strong> <code>{escape(str(payload['target_path']))}</code></p>
<h2>Safe changes</h2><ul>{safe_section}</ul>
<h2>Remaining findings</h2><table><thead><tr><th>Rule</th><th>Severity</th><th>Location</th><th>Reason</th></tr></thead><tbody>{remaining}</tbody></table>
</body></html>
"""


__all__ = ["rebuild_html", "rebuild_markdown", "repair_html", "repair_markdown"]
