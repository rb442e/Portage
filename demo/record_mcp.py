"""Record a narrated MCP walkthrough against an isolated, running Portage at :8132.
Run: uv run --offline --with playwright --with imageio-ffmpeg python demo/record_mcp.py
Requires macOS say, a running Ollama, and live Parallel MCP connectivity.
No UI responses or tool results are mocked. Outputs docs/Sora_MCP_Walkthrough.mp4.
"""
import json, os, subprocess, time, wave
from pathlib import Path
import imageio_ffmpeg
from playwright.sync_api import sync_playwright
from record import OVERLAY_JS

ROOT = Path(__file__).resolve().parent.parent
WORK = Path('/tmp/portage-mcp-recording')
BASE = 'http://127.0.0.1:8132'
FF = imageio_ffmpeg.get_ffmpeg_exe()
SCENES = [
('Portage + MCP', 'Connect. Discover. Control.', 'This walkthrough shows how Portage uses the Model Context Protocol. We will connect Sora to Parallel web search, inspect a real tool call, and control which external tools Sora can use.'),
('01 / Two MCP roles', 'One protocol. Two directions.', 'Portage has two MCP roles. As a client, it calls external MCP servers for Sora. As a server, it exposes Portage tools to external assistants, using standard input and output. These are separate connections.'),
('02 / External servers', 'Parallel Search MCP', 'In Settings, select MCP server. The external server named parallel search MCP connects to search dot parallel dot A I, over Streamable HTTP. Connected means Portage successfully discovered its tools.'),
('03 / Tool discovery', 'Inspect Web Search', 'Click Web Search to inspect its description. Parallel provides Web Search for internet queries and Web Fetch for retrieving pages. Portage exposes tools that pass its read only policy. A connection test discovers tools; it does not run a search.'),
('04 / Live web search', 'Sora → Portage → Parallel', 'Now ask Sora to search the web. Portage selects the available search tool, sends the arguments to Parallel, and passes the returned results back to the model. The tool activity in the conversation identifies the server and tool used.'),
('05 / Results and trace', 'Verify the tool that ran', 'The check mark records the completed external tool call. The response below is generated from the live search results. Use this activity trace to distinguish an actual search from a model answering from memory.'),
('06 / Disable a tool', 'Web Search off', 'Turn off Web Search to remove it from Sora on its next message. The setting is saved immediately. Web Fetch stays enabled, so you can control each tool independently without deleting the server.'),
('07 / Restore access', 'Web Search on', 'Turn Web Search back on to make it available again. The server level Available to Sora switch controls every tool from this server. The individual tool switches give you finer control.'),
('08 / Connect an MCP client', 'External assistant → Portage', 'The Connect an MCP client section shows configuration for Visual Studio Code and other clients. The client starts the Portage MCP server as a local process. Portage tools support your migration workflow, and proposed changes still require approval in Portage.'),
('Portage + Sora', 'Connected tools. Explicit control.', 'You have seen live Parallel tool discovery, a real web search through Sora, individual tool controls, and configuration for connecting external MCP clients to Portage. Choose your servers, inspect their tools, and enable only what your team needs.')]

def main():
    WORK.mkdir(exist_ok=True)
    audio=[]
    for i,(_,_,narration) in enumerate(SCENES):
        a=WORK/f'{i}.aiff'; w=WORK/f'{i}.wav'
        if not a.exists(): subprocess.run(['say','-r','165','-o',str(a),narration],check=True)
        subprocess.run([FF,'-y','-loglevel','error','-i',str(a),'-ar','48000','-ac','1',str(w)],check=True)
        with wave.open(str(w)) as f: duration=f.getnframes()/f.getframerate()
        audio.append((w,duration))
    timings=[]; events=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1600,'height':900},record_video_dir=str(WORK/'raw'),record_video_size={'width':1600,'height':900})
        context.add_init_script(OVERLAY_JS)
        page=context.new_page()
        page.on('response',lambda r: events.append(r) if '/api/copilot/chat' in r.url else None)
        page.goto(BASE); page.get_by_role('link',name='Settings',exact=True).click(); page.wait_for_load_state('networkidle')
        page.add_style_tag(content='.cp-drawer{width:640px!important;max-width:90vw!important}')
        page.evaluate("""() => {document.querySelector('#demo-cap').style.cssText += ';left:280px;bottom:18px;max-width:650px'; window.mcpCard=(title,sub,body)=>{const c=document.querySelector('#demo-card');c.innerHTML='<div style="font-size:18px;letter-spacing:.2em;color:#7dd3fc">PORTAGE / MCP WALKTHROUGH</div><h1>'+title+'</h1><p class="sub">'+sub+'</p><div style="font-size:25px;line-height:1.8;color:#dbeafe;max-width:1100px">'+body+'</div>';c.classList.add('on')};} """)
        t0=time.monotonic()
        def scene(i):
            k,t,_=SCENES[i]; page.evaluate('([k,t])=>window.__demo.caption(k,t)',[k,t]); timings.append((time.monotonic()-t0,audio[i][0])); print('SCENE',i,flush=True)
        def hold(i): page.wait_for_timeout((audio[i][1]+1)*1000)
        def click(loc):
            loc.scroll_into_view_if_needed(); b=loc.bounding_box();page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2,steps=20);loc.click();page.wait_for_timeout(500)
        page.evaluate("mcpCard('Portage + MCP','Connect. Discover. Control.','A narrated product walkthrough<br>Parallel Web Search · Tool access · MCP clients')")
        scene(0); hold(0)
        page.evaluate("mcpCard('Two MCP roles','Follow the direction of the request','Sora → Portage MCP client → Parallel MCP server → Internet<br><br>External assistant → Portage MCP server → Portage tools')")
        scene(1); hold(1)
        page.evaluate("document.querySelector('#demo-card').classList.remove('on')")
        click(page.get_by_role('button',name='MCP server',exact=True))
        card=page.locator('.mcp-card').filter(has_text='parallel_search_mcp')
        card.get_by_text('Connected',exact=True).wait_for(timeout=60000)
        card.evaluate("e=>e.scrollIntoView({block:'center'})");page.wait_for_timeout(500)
        scene(2);hold(2)
        click(card.get_by_role('button',name='Web Search',exact=False));scene(3);hold(3)
        click(card.get_by_role('button',name='Web Search',exact=False))
        page.keyboard.press('Control+k');page.locator('textarea[placeholder^="Message Sora"]').wait_for()
        scene(4)
        page.locator('textarea[placeholder^="Message Sora"]').fill('Search the web using Parallel for the official Model Context Protocol documentation. Briefly explain MCP and include source links.')
        page.get_by_role('button',name='Send',exact=True).click()
        page.get_by_role('button',name='Stop',exact=True).wait_for(state='hidden',timeout=240000)
        steps=page.locator('.cp-step').all_text_contents()
        (WORK/'tool-trace.json').write_text(json.dumps({'steps':steps,'answer':page.locator('.cp-msg.assistant').last.inner_text()},indent=2))
        assert any('parallel' in s.lower() and 'web search' in s.lower() and '✓' in s for s in steps),steps
        page.locator('.cp-msg.assistant').last.screenshot(path=str(WORK/'search-result.png'))
        scene(5);hold(5)
        page.get_by_title('Close (Esc)').click()
        card.scroll_into_view_if_needed()
        click(card.get_by_role('checkbox',name='Disable Web Search for Sora'))
        page.get_by_text('web_search disabled for Sora.',exact=True).wait_for()
        scene(6);hold(6)
        assert 'ext_parallel_search_mcp__web_search' in page.request.get(BASE+'/api/settings/mcp/servers').json()['disabled_tools']
        click(card.get_by_role('checkbox',name='Enable Web Search for Sora'))
        scene(7);hold(7)
        assert page.request.get(BASE+'/api/settings/mcp/servers').json()['disabled_tools']==[]
        page.get_by_text('Connect an MCP client',exact=True).locator('..').evaluate("e=>e.scrollIntoView({block:'center'})");page.wait_for_timeout(500)
        scene(8);hold(8)
        page.evaluate("mcpCard('Connected tools. Explicit control.','Portage + Sora','Discover external tools · Run Parallel Web Search<br>Control access per tool or server · Connect external MCP clients')")
        scene(9);hold(9)
        page.screenshot(path=str(WORK/'outro.png'))
        video=page.video;context.close();raw=video.path();browser.close()
    inputs=['-i',str(raw)];filters=[];labels=[]
    for i,(start,path) in enumerate(timings):
        inputs+=['-i',str(path)];filters.append(f'[{i+1}:a]adelay={int(start*1000)}:all=1[a{i}]');labels.append(f'[a{i}]')
    filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0[a]')
    out=ROOT/'docs/Sora_MCP_Walkthrough.mp4'
    subprocess.run([FF,'-y','-loglevel','error',*inputs,'-filter_complex',';'.join(filters),'-map','0:v','-map','[a]','-c:v','libx264','-crf','20','-preset','fast','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(out)],check=True)
    (WORK/'timings.json').write_text(json.dumps([(round(t,1),SCENES[i][0]) for i,(t,_) in enumerate(timings)],indent=2))
    print(out,flush=True)
if __name__=='__main__':main()
