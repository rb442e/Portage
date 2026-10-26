"""Records the Sora walkthrough (title card, captions, visible cursor) against a seeded demo workspace.

Run from anywhere:   uv run --with playwright python demo/record.py
Then:                uv run --with imageio-ffmpeg python demo/post.py     (writes docs/Sora_Demo.mp4)

Needs Playwright's headless Chromium (uv run --with playwright python -m playwright install chromium-headless-shell)
and a running Ollama with llama3.1:8b and gemma3:4b. Uses its own throwaway data directory
(SORA_DEMO_WORK, default /tmp/sora-demo) and port 8130, so your real Portage data is never touched.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = f"{ROOT}/.venv/bin/python"
WORK = os.environ.get("SORA_DEMO_WORK", "/tmp/sora-demo")
DATA = f"{WORK}/data"
BASE = "http://127.0.0.1:8130"
RAW = f"{WORK}/raw"
W, H = 1600, 900

OVERLAY_JS = r"""
(() => {
  if (window.__demo) return;
  const LOGO = (i) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="104" height="104"><defs><linearGradient id="g${i}" x1="6" y1="2" x2="58" y2="62" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#6366F1"/><stop offset=".55" stop-color="#3B82F6"/><stop offset="1" stop-color="#06B6D4"/></linearGradient><linearGradient id="h${i}" x1="32" y1="0" x2="32" y2="36" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#fff" stop-opacity=".3"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs><rect width="64" height="64" rx="16" fill="url(#g${i})"/><rect width="64" height="64" rx="16" fill="url(#h${i})"/><path d="M43 22C40 16.5 31 14.5 25.5 18.5C20 22.5 22.5 29 32 31.5C41.5 34 44 40.5 38.5 45.5C33 50 24 48.5 21 42" fill="none" stroke="#fff" stroke-width="5.2" stroke-linecap="round" stroke-linejoin="round"/><path transform="translate(2 -1.5)" d="M49 9c.7 3.4 2.5 5.2 6 6-3.5.7-5.3 2.5-6 6-.7-3.5-2.5-5.3-6-6 3.5-.8 5.3-2.6 6-6z" fill="#CFFAFE"/></svg>`;
  const css = `
  #demo-cursor{position:fixed;left:-50px;top:-50px;width:30px;height:30px;z-index:2147483647;pointer-events:none;filter:drop-shadow(0 2px 3px rgba(0,0,0,.4))}
  .demo-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:3px solid rgba(37,99,235,.95);animation:demo-rip .55s ease-out forwards}
  @keyframes demo-rip{from{transform:scale(.4);opacity:1}to{transform:scale(3.4);opacity:0}}
  #demo-cap{position:fixed;left:276px;bottom:34px;max-width:700px;z-index:2147483645;pointer-events:none;background:rgba(15,23,42,.95);color:#fff;border-radius:14px;padding:14px 24px 16px 20px;box-shadow:0 14px 44px rgba(2,6,23,.4);border-left:5px solid #38bdf8;opacity:0;transform:translateY(14px);transition:opacity .4s,transform .4s;font-family:-apple-system,"Helvetica Neue",Helvetica,Arial,sans-serif}
  #demo-cap.on{opacity:1;transform:none}
  #demo-cap small{display:block;font-size:12.5px;letter-spacing:.15em;text-transform:uppercase;color:#7dd3fc;font-weight:700;margin-bottom:5px}
  #demo-cap span{font-size:23px;line-height:1.3;font-weight:600}
  #demo-badge{position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:2147483644;pointer-events:none;background:rgba(15,23,42,.92);color:#e0f2fe;font:700 14px -apple-system,Helvetica,Arial,sans-serif;letter-spacing:.06em;padding:7px 16px;border-radius:999px;opacity:0;transition:opacity .25s}
  #demo-badge.on{opacity:1}
  #demo-card{position:fixed;inset:0;z-index:2147483640;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:#fff;background:linear-gradient(160deg,#0b1224 0%,#1e1b4b 55%,#0e7490 100%);font-family:-apple-system,"Helvetica Neue",Helvetica,Arial,sans-serif;opacity:0;transition:opacity .8s;pointer-events:none}
  #demo-card.on{opacity:1}
  #demo-card.instant{transition:none !important}
  #demo-card h1{font-size:72px;letter-spacing:-1.5px;margin:22px 0 8px;font-weight:800}
  #demo-card p.sub{font-size:27px;color:#bae6fd;margin:0 0 30px}
  #demo-card .tags{display:flex;gap:12px;flex-wrap:wrap;justify-content:center}
  #demo-card .pill{border:1px solid rgba(255,255,255,.35);border-radius:999px;padding:8px 18px;font-size:18px;color:#e0f2fe}
  #demo-card .vals{display:grid;grid-template-columns:repeat(4,250px);gap:20px;margin:34px 0 40px}
  #demo-card .val{border:1px solid rgba(255,255,255,.22);background:rgba(255,255,255,.07);border-radius:16px;padding:22px 18px}
  #demo-card .val b{display:block;font-size:30px;color:#7dd3fc;margin-bottom:8px}
  #demo-card .val span{font-size:17px;color:#cbd5e1;line-height:1.4}
  #demo-card .foot{font-size:20px;color:#94a3b8}
  `;
  function boot() {
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    const mk = (id, html) => { const d = document.createElement('div'); d.id = id; if (html) d.innerHTML = html; document.body.appendChild(d); return d; };
    const cur = mk('demo-cursor', '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M4 2l16 9-7 2-3 7z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>');
    const cap = mk('demo-cap'); const badge = mk('demo-badge'); const card = mk('demo-card');
    document.addEventListener('mousemove', (e) => { cur.style.left = e.clientX - 5 + 'px'; cur.style.top = e.clientY - 3 + 'px'; }, true);
    document.addEventListener('mousedown', (e) => { const r = document.createElement('div'); r.className = 'demo-ripple'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px'; document.body.appendChild(r); setTimeout(() => r.remove(), 650); }, true);
    window.__demo = {
      caption(kicker, text) { cap.innerHTML = `<small>${kicker}</small><span>${text}</span>`; cap.classList.add('on'); },
      hideCaption() { cap.classList.remove('on'); },
      badge(text) { if (text) { badge.textContent = text; badge.classList.add('on'); } else badge.classList.remove('on'); },
      card(kind, on, instant) {
        card.classList.toggle('instant', !!instant);
        if (kind === 'title') card.innerHTML = LOGO(1) + '<h1>Sora</h1><p class="sub">The AI assistant built into Portage</p><div class="tags"><span class="pill">Runs on a local model</span><span class="pill">Propose, then approve</span><span class="pill">Grounded in your data</span></div>';
        if (kind === 'outro') card.innerHTML = LOGO(2) + '<h1>Sora in Portage</h1><div class="vals"><div class="val"><b>Local</b><span>Runs on Ollama on your machine. No data leaves it.</span></div><div class="val"><b>Approved</b><span>Every change is a proposal you apply.</span></div><div class="val"><b>Reversible</b><span>Versioned catalogs and immutable mappings.</span></div><div class="val"><b>Traceable</b><span>Every chat, tool call and apply is audited.</span></div></div><div class="foot">Portage: carry your work across, intact.</div>';
        card.classList.toggle('on', !!on);
        cur.style.display = on ? 'none' : 'block';
      },
    };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
"""


def log(msg):
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def http(url, data=None, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def start_backend():
    subprocess.run("pkill -f 'uvicorn app.main:app --port 8130'", shell=True)
    time.sleep(1.2)
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA)
    if not os.path.exists(f"{WORK}/new_users.png"):
        subprocess.run(["uv", "run", "--quiet", "--with", "pillow", "python", f"{HERE}/make_image.py", f"{WORK}/new_users.png"], check=True)
    env = {**os.environ, "PORTAGE_DATA_DIR": DATA, "PYTHONPATH": f"{ROOT}/backend"}
    subprocess.run([PY, f"{HERE}/seed.py"], cwd=f"{ROOT}/backend", env=env, check=True, stdout=subprocess.DEVNULL)
    server = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--port", "8130"], cwd=f"{ROOT}/backend",
                              env={**env, "PORTAGE_FRONTEND_DIST": f"{ROOT}/frontend/dist"},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            http(f"{BASE}/api/health", timeout=2)
            return server
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("backend did not start")


def warm_models():
    """Load both Ollama models so no scene waits on a cold start."""
    for body in ({"model": "llama3.1:8b", "prompt": "hi", "stream": False, "options": {"num_predict": 1}},
                 {"model": "gemma3:4b", "prompt": "hi", "stream": False, "options": {"num_predict": 1}}):
        http("http://localhost:11434/api/generate", body, timeout=180)


T0 = time.time()
segments = []          # (start, end) video-time intervals that are sped up in post
state = {"x": 800.0, "y": 450.0}


def main():
    server = start_backend()
    log("backend up")
    warm_models()
    log("models warm")
    shutil.rmtree(RAW, ignore_errors=True)
    os.makedirs(RAW)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--hide-scrollbars"])   # headless shell: records the full viewport
            ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                      record_video_dir=RAW, record_video_size={"width": W, "height": H})
            ctx.add_init_script(OVERLAY_JS)
            page = ctx.new_page()
            global VIDEO_T0
            VIDEO_T0 = time.time()
            record(page)
            page.wait_for_timeout(500)
            ctx.close()
            video = page.video.path()
            browser.close()
        shutil.copy(video, f"{WORK}/raw.webm")
        json.dump({"segments": segments, "duration": time.time() - VIDEO_T0}, open(f"{WORK}/segments.json", "w"))
        log(f"saved video, {len(segments)} sped-up segments")
    finally:
        server.terminate()


def vt():
    return time.time() - VIDEO_T0


def record(page):
    def say(kicker, text):
        page.evaluate("([k, t]) => window.__demo.caption(k, t)", [kicker, text])

    def hush():
        page.evaluate("() => window.__demo.hideCaption()")

    def card(kind, on, instant=False):
        page.evaluate("([k, o, i]) => window.__demo.card(k, o, i)", [kind, on, instant])

    def glide(x, y, secs=0.8):
        x0, y0 = state["x"], state["y"]
        n = max(int(secs * 50), 8)
        for i in range(1, n + 1):
            t = i / n
            e = t * t * (3 - 2 * t)                       # ease in-out
            page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            time.sleep(secs / n)
        state["x"], state["y"] = x, y

    def target(sel):
        loc = page.locator(sel).first
        loc.wait_for(state="visible", timeout=15000)
        b = loc.bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    def click(sel, secs=0.8, after=0.5):
        x, y = target(sel)
        glide(x, y, secs)
        time.sleep(0.2)
        page.mouse.click(x, y)
        time.sleep(after)

    def type_text(text, delay=38):
        page.keyboard.type(text, delay=delay)

    def wait_reply(label):
        """Wait for Sora to finish; the waiting stretch is sped up in post and labelled on screen."""
        page.wait_for_selector('.cp-send[aria-label="Stop"]', timeout=15000)
        time.sleep(1.6)
        start = vt()
        page.evaluate("() => window.__demo.badge('SPEEDED UP')")
        page.wait_for_selector('.cp-send[aria-label="Send"]', timeout=180000)
        end = vt()
        page.evaluate("() => window.__demo.badge(null)")
        if end - start > 3:
            segments.append((start, end))
        log(f"{label}: waited {end - start:.1f}s")
        time.sleep(0.9)

    # --- title -------------------------------------------------------------------
    page.goto(BASE + "/")
    card("title", True, True)
    page.wait_for_selector(".nav-item")
    time.sleep(4.6)
    card("title", False)
    time.sleep(1.2)

    # --- 1. meet Sora ------------------------------------------------------------
    say("Meet Sora", "Portage&rsquo;s built-in AI assistant, available on every page.")
    time.sleep(2.2)
    click(".cp-ask")
    page.wait_for_selector(".cp-drawer")
    say("Private by design", "Sora runs on a local model. Your migration data never leaves your machine.")
    time.sleep(4.0)

    # --- 2. context-aware: catalog gaps ------------------------------------------
    click('a[href="/lookups"]')
    page.wait_for_selector(".cp-chip.page")
    say("Context-aware", "Sora knows you are on the Jira Catalog, and which catalog is open.")
    time.sleep(3.0)
    click(".cp-input textarea", 0.8, 0.3)
    say("Ask in plain English", "It checks your uploaded Rally export against the catalog.")
    type_text("Which sprints in my latest upload are missing from the sprint catalog?")
    time.sleep(0.6)
    click(".cp-send", 0.6, 0.2)
    wait_reply("catalog gaps")
    say("Grounded answers", "Exactly which sprints are missing, and how many items they affect.")
    time.sleep(5.0)

    # --- 3. explain a failed migration -------------------------------------------
    click('a[href="/reports"]')
    page.wait_for_function("() => document.querySelector('.cp-chip.page')?.textContent.includes('Reports')")
    say("Explain failures", "Switch to Reports and ask why the last migration failed.")
    click(".cp-input textarea", 0.8, 0.3)
    type_text("Why did my last migration fail?")
    time.sleep(0.5)
    click(".cp-send", 0.6, 0.2)
    wait_reply("failure analysis")
    say("Root cause, not raw logs", "Failures are grouped by cause, with the affected items listed.")
    time.sleep(5.5)

    # --- 4. screenshot -> proposal -> approve ------------------------------------
    click('a[href="/lookups"]')
    click('.content nav button:has-text("User")', 0.7, 0.8)
    click('button[title="New chat"]', 0.7, 0.5)
    say("Attach context", "Drop in a file or a screenshot. Here: a spreadsheet of new users.")
    time.sleep(2.0)
    x, y = target('button[aria-label="Attach a file or screenshot"]')
    glide(x, y, 0.8)
    time.sleep(0.2)
    with page.expect_file_chooser() as fc:
        page.mouse.click(x, y)
    fc.value.set_files(f"{WORK}/new_users.png")
    page.wait_for_selector(".cp-ctx .cp-chip.ready, .cp-ctx .cp-chip:not(.page):not(.uploading):not(.error)", timeout=15000)
    time.sleep(1.6)
    click(".cp-input textarea", 0.7, 0.3)
    type_text("Add these new users to the user catalog")
    time.sleep(0.6)
    say("Screenshots, understood", "A local vision model reads the image. Sora then prepares the change.")
    click(".cp-send", 0.6, 0.2)
    wait_reply("screenshot proposal")
    page.wait_for_selector(".cp-proposal.pending", timeout=10000)
    say("Propose, then approve", "Nothing changes until you review the diff and click Apply.")
    time.sleep(4.5)
    click('.cp-proposal button:has-text("Apply")', 0.9, 0.8)
    page.wait_for_selector(".cp-proposal.applied", timeout=15000)
    say("You stay in control", "Applied. The catalog behind the panel has updated.")
    time.sleep(3.6)

    # --- 5. history ---------------------------------------------------------------
    click('button[title="Close (Esc)"]', 0.7, 0.9)
    say("Reversible", "Every change is versioned and attributed. Compare or restore any version.")
    click('button:has-text("History")', 0.9, 1.0)
    page.wait_for_selector(".jc-modal")
    time.sleep(2.2)
    cmp_btn = page.locator('.jc-modal button:has-text("Compare to current")').first
    if cmp_btn.count():
        click('.jc-modal button:has-text("Compare to current")', 0.8, 2.6)
    time.sleep(1.6)
    click(".jc-modal-x", 0.8, 0.8)
    hush()

    # --- 6. GraphRAG ----------------------------------------------------------------
    say("Shortcut", "Open Sora from anywhere with &#8984;K.")
    time.sleep(1.2)
    page.keyboard.press("Meta+k")
    page.wait_for_selector(".cp-drawer")
    time.sleep(0.6)
    click('button[title="New chat"]', 0.7, 0.5)
    say("GraphRAG", "Ask how fields, mappings, catalogs and jobs relate, answered from a live knowledge graph.")
    click(".cp-input textarea", 0.8, 0.3)
    type_text("@lineage Which Rally fields feed the sprint field for User Story?")
    time.sleep(0.6)
    click(".cp-send", 0.6, 0.2)
    wait_reply("lineage")
    say("Lineage in one answer", "Rally field to Jira field, with the mapping versions that define it.")
    time.sleep(5.5)

    # --- 7. settings and MCP --------------------------------------------------------
    click('button[title="Close (Esc)"]', 0.7, 0.7)
    click('a[href="/settings"]', 0.9, 0.9)
    page.wait_for_selector(".st-tabs")
    say("Settings", "Models, privacy and agent access are all configurable in one place.")
    time.sleep(3.0)
    click('.st-tabs button:has-text("MCP server")', 0.8, 1.0)
    say("MCP server", "Let other AI agents use Portage: read-only or propose-only, and fully audited.")
    time.sleep(4.0)
    page.evaluate("""([root, data]) => {
        // Show generic paths on screen so no local username or temp directory appears in the video.
        document.querySelectorAll('.st-code pre').forEach((p) => {
            p.textContent = p.textContent.split(data).join('/path/to/portage/backend/data').split(root).join('/path/to/portage');
        });
        const t = [...document.querySelectorAll('.card-title')].find(e => e.textContent.includes('Connect an MCP client'));
        t.closest('.card').scrollIntoView({behavior: 'smooth', block: 'start'});
    }""", [ROOT, DATA])
    time.sleep(3.4)
    hush()
    time.sleep(3.0)
    hush()

    # --- outro ----------------------------------------------------------------------
    card("outro", True)
    time.sleep(6.0)


if __name__ == "__main__":
    main()
