"""Local browser dashboard for RebuildPilot."""

from __future__ import annotations

import json
import mimetypes
import shutil
import tempfile
import uuid
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .rebuild import rebuild
from .repository import commit_repository, diff_repository, onboard_repository, publish_repository, repository_has_changes
from .repair import repair
from .scanner import analyze
from .validator import validate


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RebuildPilot Dashboard</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#e9e7f5;background:#100e18;--panel:#1b1827;--line:#383148;--muted:#aaa3bf;--lime:#c5ff3d;--red:#ff7777;--amber:#ffc56b}
*{box-sizing:border-box}body{margin:0}.shell{display:grid;grid-template-columns:230px 1fr;min-height:100vh}
aside{border-right:1px solid var(--line);padding:28px 18px;background:#15121f}h1{font-size:20px;margin:0 0 34px}h1 span{color:var(--lime)}
nav button{display:block;width:100%;padding:12px;border:0;background:transparent;color:var(--muted);text-align:left;border-radius:8px;margin:5px 0;font-size:14px;cursor:pointer}
nav button.active,nav button:hover{background:#282238;color:#fff}.brand{color:#fff}.content{padding:32px;max-width:1280px;width:100%;margin:auto}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}.top h2{margin:0;font-size:28px}.muted{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}.card h3{font-size:13px;color:var(--muted);font-weight:500;margin:0 0 12px}.value{font-size:28px;font-weight:700}
.hero{display:grid;grid-template-columns:1.4fr 1fr;gap:18px;margin-bottom:18px}.drop{border:1px dashed #655b7c;border-radius:12px;padding:28px;text-align:center;background:#171421}.drop input{margin:18px 0;color:var(--muted)}
button.action{background:var(--lime);border:0;color:#11151a;border-radius:7px;padding:11px 16px;font-weight:700;cursor:pointer}button.secondary{background:#2a2439;color:#fff;border:1px solid var(--line);border-radius:7px;padding:10px 14px;cursor:pointer}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.score{font-size:58px;color:var(--lime);font-weight:800}.bar{height:9px;background:#302a40;border-radius:20px;overflow:hidden}.bar i{display:block;height:100%;background:var(--lime)}.loaded{display:none;margin-top:16px;border:1px solid #607a2c;background:#202b1c;border-radius:8px;padding:14px}.loaded.ready{display:block}
.finding{border-bottom:1px solid var(--line);padding:15px 0;display:grid;grid-template-columns:100px 1fr auto;gap:14px;align-items:start}.finding:last-child{border:0}.badge{font-size:11px;text-transform:uppercase;font-weight:800;border-radius:5px;padding:5px 7px;display:inline-block}.critical,.high{background:#57272d;color:#ff9999}.medium{background:#55421f;color:#ffd990}.low,.info{background:#263d2d;color:#b7f0a9}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid var(--line);font-size:13px}th{color:var(--muted);font-weight:500}.hidden{display:none}.notice{padding:12px;border-radius:8px;background:#2b243c;color:var(--muted);margin:12px 0}.error{color:var(--red)}pre{white-space:pre-wrap;max-height:350px;overflow:auto;color:#d9d2ed}
@media(max-width:850px){.shell{display:block}aside{border-right:0}.grid,.hero{grid-template-columns:1fr}.content{padding:18px}}
</style></head>
<body><div class="shell"><aside><h1 class="brand">Rebuild<span>Pilot</span></h1><nav>
<button data-view="start" class="active">Start</button><button data-view="guided">Guided Workflow</button><button data-view="workbench">Developer Workbench</button>
</nav><p class="muted" style="margin-top:40px;font-size:12px">Local analysis. Your project stays on this machine.</p></aside>
<main class="content"><section id="start" class="view"><div class="top"><div><h2>Make any project rebuildable.</h2><p class="muted">Analyze, repair, validate, and rebuild from one workspace.</p></div></div>
<div class="hero"><div class="drop"><h3>Choose a project</h3><p class="muted">Clone GitHub, upload a ZIP archive, or open a local folder.</p><input id="repo" placeholder="https://github.com/owner/repository.git" style="width:80%;padding:10px;background:#100e18;border:1px solid var(--line);color:#fff;border-radius:6px"><div class="actions" style="justify-content:center"><button id="cloneButton" class="action" onclick="clone()">Clone and onboard</button></div><hr style="border-color:#383148"><input id="zip" type="file" accept=".zip"><br><input id="path" placeholder="C:\path\to\project" style="width:80%;padding:10px;background:#100e18;border:1px solid var(--line);color:#fff;border-radius:6px"><div class="actions" style="justify-content:center"><button id="openButton" class="secondary" onclick="upload()">Open local project</button></div><p id="uploadStatus" class="muted"></p><div id="loadedProject" class="loaded"><strong>Project loaded.</strong><br><small id="loadedSource"></small><br><small id="loadedPath"></small><div class="actions"><button class="action" onclick="analyzeLoaded()">Analyze project</button><button class="secondary" onclick="show('guided')">Open workflow</button></div></div></div>
<div class="card"><h3>Workflow</h3><div class="finding"><span class="badge info">1</span><div>Scan project<br><small class="muted">Find reproducibility risks</small></div></div><div class="finding"><span class="badge info">2</span><div>Review fixes<br><small class="muted">Preview safe changes</small></div></div><div class="finding"><span class="badge info">3</span><div>Verify rebuild<br><small class="muted">Run tests in a copy</small></div></div></div></div></section>
<section id="guided" class="view hidden"><div class="top"><div><h2>Guided Workflow</h2><p id="projectName" class="muted">No project loaded</p></div><button class="secondary" onclick="show('start')">Open another project</button></div><div class="grid"><div class="card"><h3>REPRODUCIBILITY SCORE</h3><div id="score" class="score">—</div><div class="bar"><i id="scoreBar" style="width:0%"></i></div></div><div class="card"><h3>CRITICAL</h3><div id="critical" class="value">—</div></div><div class="card"><h3>HIGH</h3><div id="high" class="value">—</div></div><div class="card"><h3>PROJECT TYPE</h3><div id="type" class="value" style="font-size:20px">—</div></div></div><div class="card" style="margin-top:18px"><h3>Next actions</h3><p id="summary" class="muted">Load a project to begin.</p><div class="actions"><button class="action" onclick="runAction('analyze')">Analyze project</button><button class="secondary" onclick="runAction('fix-plan')">Preview safe fixes</button><button class="secondary" onclick="runAction('validate')">Validate in sandbox</button><button class="secondary" onclick="runAction('rebuild')">Run clean rebuild</button><button class="secondary" onclick="runAction('diff')">Review changes</button><button class="action" onclick="publish()">Publish to GitHub</button></div><div id="actionStatus" class="notice hidden"></div></div><div class="card" style="margin-top:18px"><h3>Prioritized findings</h3><div id="findings"><p class="muted">No analysis yet.</p></div></div></section>
<section id="workbench" class="view hidden"><div class="top"><div><h2>Developer Workbench</h2><p class="muted">Inspect findings and review generated changes.</p></div></div><div class="card"><h3>RESULT DETAILS</h3><div id="details"><p class="muted">Run an analysis from Guided Workflow.</p></div></div></section>
</main></div>
<script>
let state={root:null,analysis:null,remote:false,busy:false};
const $=id=>document.getElementById(id);
function show(view){document.querySelectorAll('.view').forEach(x=>x.classList.add('hidden'));$(view).classList.remove('hidden');document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===view))}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>show(b.dataset.view));
function beginLoad(message){state.root=null;state.analysis=null;state.remote=false;state.busy=true;$('loadedProject').classList.remove('ready');$('uploadStatus').textContent=message;$('cloneButton').disabled=true;$('openButton').disabled=true}
function endLoad(){state.busy=false;$('cloneButton').disabled=false;$('openButton').disabled=false}
function loaded(source,root){state.root=root;$('loadedSource').textContent='Source: '+source;$('loadedPath').textContent='Workspace: '+root;$('loadedProject').classList.add('ready')}
async function upload(){const file=$('zip').files[0], path=$('path').value.trim();let response;
 if(state.busy){return}if(!file&&!path){$('uploadStatus').textContent='Choose a ZIP or enter a folder path.';return}beginLoad('Opening selected project...');
 if(file){let data=new FormData();data.append('archive',file);response=await fetch('/api/upload',{method:'POST',body:data})}else if(path){response=await fetch('/api/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})})}else{$('uploadStatus').textContent='Choose a ZIP or enter a folder path.';return}
 try{const result=await response.json();if(!response.ok){throw new Error(result.error||'The project could not be opened.')}loaded(file?'ZIP archive':'local folder',result.root);$('uploadStatus').textContent='Project loaded. Choose Analyze project to begin.'}catch(error){$('uploadStatus').textContent=error.message}finally{endLoad()}}
async function analyzeLoaded(){if(!state.root){return}show('guided');await runAction('analyze')}
async function clone(){const url=$('repo').value.trim();if(!url){$('uploadStatus').textContent='Enter a GitHub repository URL.';return}if(state.busy){return}beginLoad('Cloning and preparing the GitHub repository...');try{const r=await fetch('/api/onboard',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});const data=await r.json();if(!r.ok){throw new Error(data.error||'The repository could not be cloned.')}loaded(url,data.root);state.remote=true;$('uploadStatus').textContent='GitHub repository loaded and onboarded on a repair branch.';show('guided');render(data.analysis_after);renderDetails(data)}catch(error){$('uploadStatus').textContent=error.message}finally{endLoad()}}
async function runAction(action){if(!state.root){show('start');return}$('actionStatus').classList.remove('hidden');$('actionStatus').textContent='Running '+action+'...';const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({root:state.root})});const data=await r.json();if(!r.ok){$('actionStatus').innerHTML='<span class="error">'+data.error+'</span>';return}$('actionStatus').textContent=data.summary||'Completed.';if(data.analysis)render(data.analysis);if(data.report)renderDetails(data.report)}
async function publish(){if(!state.remote){$('actionStatus').textContent='Only cloned repositories can be published.';return}if(!confirm('Push the reviewed repair branch to GitHub?'))return;await runAction('publish')}
function render(a){state.analysis=a;$('projectName').textContent=a.target_path;$('score').textContent=a.score+'/100';$('scoreBar').style.width=a.score+'%';$('critical').textContent=a.findings.filter(x=>x.severity==='critical').length;$('high').textContent=a.findings.filter(x=>x.severity==='high').length;$('type').textContent=a.project_type;const ml=a.ml_frameworks&&a.ml_frameworks.length?' ML stack: '+a.ml_frameworks.join(', ')+'.':' ';$('summary').textContent=a.summary+ml;$('findings').innerHTML=a.findings.length?a.findings.map(f=>'<div class="finding"><span class="badge '+f.severity+'">'+f.severity+'</span><div><strong>'+esc(f.title)+'</strong><br><small class="muted">'+esc(f.explanation)+'</small></div><small class="muted">'+esc(f.file_path||'Project-wide')+(f.line_number?':'+f.line_number:'')+'</small></div>').join(''):'<p class="muted">No findings.</p>'}
function renderDetails(r){$('details').innerHTML='<pre>'+esc(JSON.stringify(r,null,2))+'</pre>'}
function esc(x){return String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
</script></body></html>"""


class _DashboardState:
    def __init__(self) -> None:
        self.root: Path | None = None
        self.workspace = Path(tempfile.mkdtemp(prefix="rebuildpilot-dashboard-"))

    def close(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)


def _safe_extract(archive: Path, destination: Path) -> Path:
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        for member in members:
            target = (destination / member.filename).resolve()
            target.relative_to(destination.resolve())
        source.extractall(destination)
    children = [item for item in destination.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return destination


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def _repair_summary(result: dict[str, object]) -> str:
    """Render repair results from current and older installed package versions."""

    summary = result.get("summary")
    if isinstance(summary, str):
        return summary
    changed = result.get("changed_files")
    planned = result.get("planned_changes")
    before = result.get("before_score", "?")
    after = result.get("after_score", before)
    count = len(changed) if isinstance(changed, list) else len(planned) if isinstance(planned, list) else 0
    mode = "applied" if result.get("apply_requested") else "planned"
    return f"Repair {mode}: {count} change(s); score {before}/100 -> {after}/100"


class DashboardHandler(BaseHTTPRequestHandler):
    state: _DashboardState

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: HTTPStatus, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _payload(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/":
            self._send(HTTPStatus.OK, _HTML.encode("utf-8"), "text/html")
        else:
            self._send(HTTPStatus.NOT_FOUND, _json_bytes({"error": "Not found"}))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                self._upload()
            elif path == "/api/open":
                payload = self._payload()
                root = Path(str(payload.get("path", ""))).expanduser().resolve()
                if not root.is_dir():
                    raise ValueError("The selected path is not a directory.")
                self.state.root = root
                self._send(HTTPStatus.OK, _json_bytes({"root": str(root)}))
            elif path == "/api/onboard":
                payload = self._payload()
                result = onboard_repository(str(payload.get("url", "")))
                self.state.root = result.workspace.root
                self._send(HTTPStatus.OK, _json_bytes(result.as_dict()))
            elif path in {"/api/analyze", "/api/validate", "/api/rebuild", "/api/fix-plan", "/api/diff", "/api/publish"}:
                self._action(path[5:])
            else:
                self._send(HTTPStatus.NOT_FOUND, _json_bytes({"error": "Not found"}))
        except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            self._send(HTTPStatus.BAD_REQUEST, _json_bytes({"error": str(error)}))

    def _upload(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        boundary = content_type.split("boundary=", 1)[-1].encode()
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        marker = b"\r\n\r\n"
        start = body.find(marker)
        end = body.rfind(b"--" + boundary)
        if start < 0 or end <= start:
            raise ValueError("No ZIP archive was received.")
        archive = self.state.workspace / f"{uuid.uuid4()}.zip"
        archive.write_bytes(body[start + len(marker):end].rstrip(b"\r\n"))
        root = self.state.workspace / uuid.uuid4().hex
        root.mkdir()
        self.state.root = _safe_extract(archive, root)
        self._send(HTTPStatus.OK, _json_bytes({"root": str(self.state.root)}))

    def _action(self, action: str) -> None:
        payload = self._payload()
        root = Path(str(payload.get("root", ""))).resolve()
        if self.state.root is None or root != self.state.root.resolve():
            raise ValueError("Project is not loaded in this dashboard session.")
        if action == "analyze":
            result = analyze(root)
            self._send(HTTPStatus.OK, _json_bytes({"analysis": result.as_json_dict(), "summary": result.summary}))
        elif action == "validate":
            result = validate(root)
            self._send(HTTPStatus.OK, _json_bytes({"report": result.as_json_dict(), "analysis": result.analysis.as_json_dict(), "summary": result.summary}))
        elif action == "rebuild":
            result = rebuild(root)
            self._send(HTTPStatus.OK, _json_bytes({"report": result.as_json_dict(), "analysis": result.analysis.as_json_dict(), "summary": result.summary}))
        elif action == "diff":
            self._send(HTTPStatus.OK, _json_bytes({"report": diff_repository(root), "summary": "Review the generated diff before publishing."}))
        elif action == "publish":
            if repository_has_changes(root):
                commit_repository(root, "Improve project reproducibility with RebuildPilot")
            self._send(HTTPStatus.OK, _json_bytes({"report": publish_repository(root, create_pr=True), "summary": "Changes pushed and pull request requested."}))
        else:
            result = repair(root, apply=False, backup=False)
            self._send(HTTPStatus.OK, _json_bytes({"report": result, "summary": _repair_summary(result)}))


def serve(*, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    """Start the local dashboard until interrupted."""

    state = _DashboardState()
    DashboardHandler.state = state
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    url = f"http://{host}:{server.server_port}/"
    print(f"RebuildPilot dashboard: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        state.close()
