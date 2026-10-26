"""Standalone GraphRAG showcase. Records Sora chat calls and a visual of the exact graph_search result.

Run:  uv run --with playwright python demo/record_graphrag.py
Then: SORA_GRAPHRAG_WORK=/tmp/sora-graphrag-demo uv run --with imageio-ffmpeg python demo/post_graphrag.py

Uses a fresh, isolated demo database plus local Ollama models llama3.1:8b and gemma3:4b.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = f"{ROOT}/.venv/bin/python"
WORK = os.environ.get("SORA_GRAPHRAG_WORK", "/tmp/sora-graphrag-demo")
DATA = f"{WORK}/data"
RAW = f"{WORK}/raw"
BASE = "http://127.0.0.1:8131"
W, H = 1600, 900
sys.path.insert(0, HERE)
from record import OVERLAY_JS  # noqa: E402

T0 = time.time()
VIDEO_T0 = 0.0
segments = []
state = {"x": 800.0, "y": 450.0}

GRAPH_CSS = r"""
#graph-scene{position:fixed;inset:0;z-index:2147483639;background:rgba(4,10,24,.94);color:#eaf2ff;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:-apple-system,"Helvetica Neue",Helvetica,Arial,sans-serif;opacity:0;transition:opacity .55s}
#graph-scene.on{opacity:1}
#graph-scene .gs-head{width:min(1320px,92vw);display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
#graph-scene .gs-brand{font-size:14px;text-transform:uppercase;letter-spacing:.14em;color:#7dd3fc;font-weight:800}
#graph-scene .gs-count{font-size:13px;color:#a5b4fc;border:1px solid #394771;border-radius:999px;padding:7px 14px}
#graph-scene .gs-query{width:min(1320px,92vw);font-size:27px;font-weight:650;margin:0 0 18px;color:#fff}
#graph-scene .gs-stage{width:min(1320px,92vw);height:520px;border:1px solid #263755;border-radius:18px;background:radial-gradient(ellipse at 48% 46%,#162746,#0b1224 72%);position:relative;overflow:hidden;box-shadow:0 28px 90px rgba(0,0,0,.45)}
#graph-scene svg{width:100%;height:100%;overflow:visible}
#graph-scene .edge{opacity:0;transition:opacity .55s}
#graph-scene .edge.on{opacity:1}
#graph-scene .edge path{stroke-dasharray:600;stroke-dashoffset:600;transition:stroke-dashoffset .9s ease}
#graph-scene .edge.on path{stroke-dashoffset:0}
#graph-scene .edge text{font:700 13px -apple-system,Helvetica,Arial,sans-serif;fill:#b8c8e4;paint-order:stroke;stroke:#0b1224;stroke-width:5px;stroke-linejoin:round}
#graph-scene .node{opacity:0;transform:scale(.88);transform-box:fill-box;transform-origin:center;transition:opacity .45s,transform .45s}
#graph-scene .node.on{opacity:1;transform:scale(1)}
#graph-scene .node rect{rx:13;stroke-width:1.5}
#graph-scene .node text{font-family:-apple-system,Helvetica,Arial,sans-serif;pointer-events:none}
#graph-scene .node .nt{font-size:11px;font-weight:800;letter-spacing:1.1px;opacity:.82}
#graph-scene .node .nl{font-size:16px;font-weight:700}
#graph-scene .node .ns{font-size:12px;fill:#c1cee2}
#graph-scene .node.rally rect{fill:#17294a;stroke:#60a5fa}
#graph-scene .node.jira rect{fill:#152d4a;stroke:#38bdf8}
#graph-scene .node.mapping rect{fill:#292550;stroke:#a78bfa}
#graph-scene .node.catalog rect{fill:#17382f;stroke:#4ade80}
#graph-scene .node.error rect{fill:#42212b;stroke:#fb7185}
#graph-scene .node.job rect{fill:#392d19;stroke:#fbbf24}
#graph-scene .node.artifact rect{fill:#263044;stroke:#94a3b8}
#graph-scene .edge.feeds path{stroke:#60a5fa;stroke-width:2.8}
#graph-scene .edge.populates path,#graph-scene .edge.supersedes path{stroke:#a78bfa;stroke-width:2.3}
#graph-scene .edge.translates path,#graph-scene .edge.contains path{stroke:#4ade80;stroke-width:2.3}
#graph-scene .edge.mentions path,#graph-scene .edge.hit_error path{stroke:#fb7185;stroke-width:2.4}
#graph-scene .edge.covers path{stroke:#94a3b8;stroke-width:2}
#graph-scene .gs-legend{position:absolute;bottom:14px;left:18px;display:flex;gap:18px;font-size:12px;color:#bac8dc;background:rgba(5,12,25,.78);padding:9px 13px;border-radius:10px}
#graph-scene .lg{display:flex;align-items:center;gap:6px}
#graph-scene .dot{width:9px;height:9px;border-radius:50%}
#graph-scene .gs-facts{width:min(1320px,92vw);display:flex;gap:10px;margin-top:13px;min-height:50px}
#graph-scene .fact{flex:1;border:1px solid #263755;border-left:3px solid #38bdf8;background:#111d32;padding:10px 13px;border-radius:8px;font-size:13px;line-height:1.45;color:#dbeafe;opacity:0;transform:translateY(8px);transition:opacity .4s,transform .4s}
#graph-scene .fact.on{opacity:1;transform:none}
#demo-highlight{position:relative!important;background:rgba(56,189,248,.16)!important;border:1px solid #38bdf8!important;border-radius:7px!important;padding:7px 10px!important;color:#e0f2fe!important;font-weight:800!important;box-shadow:0 0 0 3px rgba(56,189,248,.13),0 0 22px rgba(56,189,248,.3)!important}
#demo-highlight:after{content:'GRAPH SEARCH';position:absolute;left:calc(100% + 10px);top:0;white-space:nowrap;background:#0e7490;color:white;border-radius:999px;padding:4px 9px;font:800 10px -apple-system,Helvetica,Arial,sans-serif;letter-spacing:.1em}
"""


def log(message: str) -> None:
    print(f"[{time.time() - T0:5.1f}s] {message}", flush=True)


def post_json(url: str, data: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def start_backend():
    subprocess.run("pkill -f 'uvicorn app.main:app --port 8131'", shell=True)
    time.sleep(1)
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA)
    env = {**os.environ, "PORTAGE_DATA_DIR": DATA, "PYTHONPATH": f"{ROOT}/backend"}
    subprocess.run([PY, f"{HERE}/seed.py"], cwd=f"{ROOT}/backend", env=env, check=True, stdout=subprocess.DEVNULL)
    server = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--port", "8131"], cwd=f"{ROOT}/backend",
                              env={**env, "PORTAGE_FRONTEND_DIST": f"{ROOT}/frontend/dist"},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{BASE}/api/health", timeout=2)
            return server
        except Exception:
            time.sleep(.5)
    raise RuntimeError("Demo backend did not start")


def warm_models():
    for model in ("llama3.1:8b", "gemma3:4b"):
        post_json("http://localhost:11434/api/generate", {
            "model": model, "prompt": "hi", "stream": False, "options": {"num_predict": 1}}, timeout=180)


def load_graph_data() -> dict:
    env = {**os.environ, "PORTAGE_DATA_DIR": DATA, "PYTHONPATH": f"{ROOT}/backend"}
    code = "import json; from app.copilot.graph import search; print(json.dumps(search('which Rally fields feed the sprint field for User Story')))"
    raw = subprocess.check_output([PY, "-c", code], cwd=f"{ROOT}/backend", env=env, text=True)
    return json.loads(raw)


def parse_graph(result: dict) -> dict:
    """Convert the actual graph_search response strings into displayable nodes/edges."""
    re_type = re.compile(r"^(rally_field|jira_field|mapping|catalog|error|job|artifact|column|catalog_version|entry|valuemap):(.+)$")
    allowed = {"feeds", "populates", "supersedes", "translates", "mentions", "hit_error", "covers"}
    nodes: dict[str, dict] = {}
    edges = []
    for text in result["relationships"]:
        if " --" not in text or "--> " not in text:
            continue
        left, rem = text.split(" --", 1)
        rel, right = rem.split("--> ", 1)
        rel = rel.strip()
        if rel not in allowed:
            continue
        right = right.split(" [", 1)[0]
        sm, dm = re_type.match(left.strip()), re_type.match(right.strip())
        if not sm or not dm:
            continue
        src_type, src_label = sm.groups()
        dst_type, dst_label = dm.groups()
        if rel == "feeds" and "sprint" not in dst_label.lower():
            continue
        if rel == "populates" and "sprint" not in dst_label.lower():
            continue
        if rel == "translates" and "sprint" not in dst_label.lower():
            continue
        if rel == "mentions" and "sprint" not in (src_label + dst_label).lower():
            continue
        if rel == "covers":
            continue
        s_id, d_id = f"{src_type}:{src_label}", f"{dst_type}:{dst_label}"
        nodes[s_id] = {"id": s_id, "type": src_type, "label": src_label}
        nodes[d_id] = {"id": d_id, "type": dst_type, "label": dst_label}
        edge_label = rel
        if rel == "feeds":
            edge_label = "feeds"
        elif rel == "populates":
            edge_label = "populates"
        elif rel == "supersedes":
            edge_label = "supersedes"
        elif rel == "translates":
            edge_label = "translates"
        elif rel == "mentions":
            edge_label = "mentions"
        edges.append({"src": s_id, "dst": d_id, "rel": rel, "label": edge_label})
    return {"nodes": list(nodes.values()), "edges": edges, "facts": result["facts"], "stats": result["stats"]}


def graph_scene_html(data: dict) -> str:
    return f'''<style>{GRAPH_CSS}</style>
    <div id="graph-scene">
    <div class="gs-head"><div class="gs-brand">Sora &nbsp;·&nbsp; GraphRAG</div><div class="gs-count">LIVE RESULT &nbsp;·&nbsp; {data['stats']['returned_nodes']} retrieved nodes &nbsp;·&nbsp; {len(data['nodes'])} shown / {len(data['edges'])} featured relationships</div></div>
      <div class="gs-query">“Which Rally fields feed the sprint field for User Story?”</div>
      <div class="gs-stage"><svg viewBox="0 0 1040 520" role="img" aria-label="Retrieved graph subgraph">
        <defs><marker id="garr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#94a3b8"/></marker></defs>
        <g id="gs-edges"></g><g id="gs-nodes"></g>
      </svg><div class="gs-legend"><span class="lg"><i class="dot" style="background:#60a5fa"></i>Lineage</span><span class="lg"><i class="dot" style="background:#a78bfa"></i>Mappings</span><span class="lg"><i class="dot" style="background:#4ade80"></i>Catalog</span><span class="lg"><i class="dot" style="background:#fb7185"></i>Failure</span></div></div>
      <div class="gs-facts" id="gs-facts"></div>
    </div>
    <script>
    (() => {{
      const data={json.dumps(data)};
      const scene=document.getElementById('graph-scene');
      const svgNS='http://www.w3.org/2000/svg';
      const pos={{rally_field:[36,210],mapping:[368,82],jira_field:[710,210],catalog:[710,396],error:[368,390],job:[36,396],artifact:[36,396],column:[36,396],entry:[710,396],catalog_version:[710,396],valuemap:[368,390]}};
      const nodes=data.nodes;
      const positions={{}};
      const offsets={{}};
      nodes.forEach(n=>{{const slot=offsets[n.type]||0;offsets[n.type]=slot+1;const p=pos[n.type]||[370,200];positions[n.id]=[p[0],p[1]+slot*84]}});
      const edgeGroup=document.getElementById('gs-edges');
      data.edges.forEach((e,i)=>{{
        const a=positions[e.src],b=positions[e.dst];if(!a||!b)return;
        const x1=a[0]+194,y1=a[1]+40,x2=b[0],y2=b[1]+40;
        const mx=(x1+x2)/2,my=(y1+y2)/2+(y1===y2?-13:0);
        const g=document.createElementNS(svgNS,'g');g.setAttribute('class',`edge ${{e.rel}}`);g.dataset.i=i;
        const path=document.createElementNS(svgNS,'path');path.setAttribute('d',`M ${{x1}} ${{y1}} C ${{mx}} ${{y1}}, ${{mx}} ${{y2}}, ${{x2}} ${{y2}}`);path.setAttribute('fill','none');path.setAttribute('marker-end','url(#garr)');g.appendChild(path);
        const t=document.createElementNS(svgNS,'text');t.setAttribute('x',mx);t.setAttribute('y',my);t.setAttribute('text-anchor','middle');t.textContent=e.label;g.appendChild(t);
        edgeGroup.appendChild(g);
      }});
      const nodeGroup=document.getElementById('gs-nodes');
      nodes.forEach((n,i)=>{{
        const [x,y]=positions[n.id],g=document.createElementNS(svgNS,'g');g.setAttribute('class',`node ${{n.type.split('_')[0]}}`);g.dataset.i=i;
        const rect=document.createElementNS(svgNS,'rect');rect.setAttribute('x',x);rect.setAttribute('y',y);rect.setAttribute('width',194);rect.setAttribute('height',80);g.appendChild(rect);
        const ty=document.createElementNS(svgNS,'text');ty.setAttribute('x',x+14);ty.setAttribute('y',y+21);ty.setAttribute('class','nt');ty.textContent=n.type.replace('_',' ').toUpperCase();g.appendChild(ty);
        const label=document.createElementNS(svgNS,'text');label.setAttribute('x',x+14);label.setAttribute('y',y+48);label.setAttribute('class','nl');label.textContent=n.label.length>24?n.label.slice(0,22)+'…':n.label;g.appendChild(label);
        if(n.type==='jira_field'){{const sub=document.createElementNS(svgNS,'text');sub.setAttribute('x',x+14);sub.setAttribute('y',y+67);sub.setAttribute('class','ns');sub.textContent='User Story';g.appendChild(sub)}}
        nodeGroup.appendChild(g);
      }});
      const facts=document.getElementById('gs-facts');
      data.facts.slice(0,3).forEach((f,i)=>{{const d=document.createElement('div');d.className='fact';d.textContent=f;d.dataset.i=i;facts.appendChild(d)}});
    window.__graphShow=()=>{{scene.classList.add('on');let delay=240;nodes.forEach((n,i)=>setTimeout(()=>nodeGroup.querySelector(`[data-i="${{i}}"]`)?.classList.add('on'),delay+i*280));let edgeStart=delay+nodes.length*280+250;data.edges.forEach((e,i)=>setTimeout(()=>edgeGroup.querySelector(`[data-i="${{i}}"]`)?.classList.add('on'),edgeStart+i*260));let factStart=edgeStart+data.edges.length*260+400;facts.querySelectorAll('.fact').forEach((f,i)=>setTimeout(()=>f.classList.add('on'),factStart+i*550))}};
      window.__graphHide=()=>scene.classList.remove('on');
    }})();
    </script>'''


def start_backend():
    subprocess.run("pkill -f 'uvicorn app.main:app --port 8131'", shell=True)
    time.sleep(1)
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA)
    env = {**os.environ, "PORTAGE_DATA_DIR": DATA, "PYTHONPATH": f"{ROOT}/backend"}
    subprocess.run([PY, f"{HERE}/seed.py"], cwd=f"{ROOT}/backend", env=env, check=True, stdout=subprocess.DEVNULL)
    server = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--port", "8131"], cwd=f"{ROOT}/backend",
                              env={**env, "PORTAGE_FRONTEND_DIST": f"{ROOT}/frontend/dist"},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{BASE}/api/health", timeout=2)
            return server
        except Exception:
            time.sleep(.5)
    raise RuntimeError("GraphRAG demo backend did not start")


def model_request(url: str, data: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def warm_models():
    for model in ("llama3.1:8b", "gemma3:4b"):
        model_request("http://localhost:11434/api/generate", {
            "model": model, "prompt": "hi", "stream": False, "options": {"num_predict": 1}}, timeout=180)


def load_actual_graph() -> dict:
    env = {**os.environ, "PORTAGE_DATA_DIR": DATA, "PYTHONPATH": f"{ROOT}/backend"}
    code = "import json; from app.copilot.graph import search; print(json.dumps(search('which Rally fields feed the sprint field for User Story')))"
    raw = subprocess.check_output([PY, "-c", code], cwd=f"{ROOT}/backend", env=env, text=True)
    return parse_graph(json.loads(raw))


def main():
    server = start_backend()
    log("isolated backend ready")
    try:
        warm_models()
        log("local models warm")
        graph_data = load_actual_graph()
        log(f"actual GraphRAG result: {graph_data['stats']['returned_nodes']} nodes; {len(graph_data['edges'])} displayed edges")
        shutil.rmtree(RAW, ignore_errors=True)
        os.makedirs(RAW)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--hide-scrollbars"])
            context = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                          record_video_dir=RAW, record_video_size={"width": W, "height": H})
            context.add_init_script(OVERLAY_JS)
            page = context.new_page()
            global VIDEO_T0
            VIDEO_T0 = time.time()
            record(page, graph_data)
            page.wait_for_timeout(400)
            context.close()
            raw = page.video.path()
            browser.close()
        shutil.copy(raw, f"{WORK}/raw.webm")
        json.dump({"segments": segments, "duration": time.time() - VIDEO_T0}, open(f"{WORK}/segments.json", "w"))
        log(f"raw recording saved; {len(segments)} model wait(s) marked for speed-up")
    finally:
        server.terminate()
        server.wait(timeout=8)


def vt():
    return time.time() - VIDEO_T0


def record(page, graph_data):
    def say(kicker, text):
        page.evaluate("([k, t]) => window.__demo.caption(k, t)", [kicker, text])

    def hush():
        page.evaluate("() => window.__demo.hideCaption()")

    def card(on):
        page.evaluate("([kind, visible, instant]) => window.__demo.card(kind, visible, instant)", ["title", on, True])

    def glide(x, y, secs=.7):
        x0, y0 = state["x"], state["y"]
        n = max(int(secs * 45), 8)
        for i in range(1, n + 1):
            t = i / n
            e = t * t * (3 - 2 * t)
            page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            time.sleep(secs / n)
        state["x"], state["y"] = x, y

    def target(selector):
        element = page.locator(selector).first
        element.wait_for(state="visible", timeout=15000)
        box = element.bounding_box()
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def click(selector, after=.5):
        x, y = target(selector)
        glide(x, y)
        page.mouse.click(x, y)
        time.sleep(after)

    def highlight_graph_call():
        result = page.evaluate("""() => {
          const s=[...document.querySelectorAll('.cp-step')].find(e=>e.textContent.toLowerCase().includes('graph search'));
          if(!s)return false;s.id='demo-highlight';s.scrollIntoView({behavior:'smooth',block:'center'});return true;
        }""")
        if not result:
            raise RuntimeError("Sora did not call graph_search; stop rather than record a misleading demo")

    def wait_reply(label):
        page.wait_for_selector('.cp-send[aria-label="Stop"]', timeout=20000)
        time.sleep(1.1)
        start = vt()
        page.evaluate("() => window.__demo.badge('SPEEDED UP')")
        page.wait_for_selector('.cp-send[aria-label="Send"]', timeout=180000)
        end = vt()
        page.evaluate("() => window.__demo.badge(null)")
        if end - start > 3:
            segments.append((start, end))
        log(f"{label}: reply ready after {end-start:.1f}s")
        time.sleep(1.0)

    def ask_graph(prompt, label):
        """Record only a response that visibly invoked graph_search; retry with a fresh chat otherwise."""
        for attempt in range(3):
            click('button[title="New chat"]', .4)
            click(".cp-input textarea", .3)
            page.keyboard.type(prompt, delay=26)
            time.sleep(.4)
            click(".cp-send", .2)
            wait_reply(label)
            if page.locator(".cp-step").filter(has_text=re.compile("graph search", re.I)).count():
                highlight_graph_call()
                return
            log(f"{label}: no visible graph tool call on attempt {attempt + 1}, retrying")
        raise RuntimeError(f"Sora did not visibly call graph_search for {label}; not recording a text-only answer")

    # Title
    page.goto(BASE + "/")
    card(True)
    page.evaluate("""() => {
      document.querySelector('#demo-card h1').textContent='GraphRAG';
      document.querySelector('#demo-card .sub').textContent='Connected knowledge, grounded answers';
      document.querySelector('#demo-card .tags').innerHTML='<span class="pill">Live workspace data</span><span class="pill">Multi-hop retrieval</span><span class="pill">Traceable relationships</span>';
    }""")
    page.wait_for_selector(".nav-item")
    time.sleep(4.5)
    card(False)
    time.sleep(1.0)

    # Actual Sora call 1: lineage
    click(".cp-ask")
    page.wait_for_selector(".cp-drawer")
    say("GraphRAG · field lineage", "Ask which Rally fields populate a Jira field, with the mapping versions behind the answer.")
    time.sleep(3.0)
    ask_graph("@lineage Use graph_search to trace which Rally fields feed the Jira sprint field for User Story. Include mapping versions.", "lineage question")
    say("Live graph_search call", "Sora retrieves connected mappings, Rally fields, Jira fields and catalog relationships.")
    time.sleep(5.0)
    page.evaluate("() => {const e=document.getElementById('demo-highlight');if(e)e.removeAttribute('id')}")
    hush()

    # Actual Sora call 2: impact of job failures
    say("Impact analysis", "Trace a migration failure through the job to the catalog and Jira field it affects.")
    ask_graph("@lineage Use graph_search to trace which catalogs and Jira fields are connected to the failures in my last migration job.", "failure impact question")
    say("Another live graph call", "The same retrieval follows job → error → catalog and Jira field.")
    time.sleep(4.5)
    page.evaluate("() => {const e=document.getElementById('demo-highlight');if(e)e.removeAttribute('id')}")

    # Animate the exact subgraph returned by graph.search for the lineage question.
    say("Inside the answer", "These are the connected nodes and relationships returned for the lineage question.")
    page.evaluate("""(html) => {
      const d=document.createElement('div');d.id='graph-html';d.innerHTML=html;document.body.appendChild(d);
      const styles=d.querySelector('style');document.head.appendChild(styles.cloneNode(true));
      const script=d.querySelector('script');(new Function(script.textContent))();
      d.remove();
    }""", graph_scene_html(graph_data))
    time.sleep(.5)
    page.evaluate("() => window.__graphShow()")
    time.sleep(13)
    page.evaluate("() => window.__graphHide()")
    time.sleep(.8)
    page.evaluate("() => document.getElementById('graph-scene')?.remove()")
    hush()

    # Outro
    page.keyboard.press("Escape")
    card(False)
    time.sleep(.4)
    page.evaluate("() => window.__demo.card('outro', true)")
    page.evaluate("""() => {
      document.querySelector('#demo-card h1').textContent='GraphRAG in Sora';
      document.querySelector('#demo-card .foot').textContent='Live graph. Connected context. A clear answer.';
    }""")
    time.sleep(5.2)
    page.evaluate("() => window.__demo.card('outro', false)")
    time.sleep(.5)


if __name__ == "__main__":
    main()
