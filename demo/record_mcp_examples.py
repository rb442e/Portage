"""Record real Sora Web Search and Web Fetch examples using the isolated :8132 demo.

Run with: uv run --offline --with playwright --with imageio-ffmpeg python demo/record_mcp_examples.py
Requires local Ollama, a configured Parallel server in the isolated workspace,
Playwright Chromium, imageio-ffmpeg, and macOS say. No tool results are mocked.
"""
import json
import subprocess
import textwrap
import time
import wave
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright
from record import OVERLAY_JS

ROOT = Path(__file__).resolve().parent.parent
WORK = Path('/tmp/portage-mcp-examples')
BASE = 'http://127.0.0.1:8132'
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SEARCH_PROMPT = ('Search the web using Parallel for the official Model Context Protocol documentation. '
                 'Return just the official URL and a one-sentence description.')
FETCH_PROMPT = ('Use Parallel Web Fetch (web_fetch) to fetch '
                'https://modelcontextprotocol.org/docs/getting-started/intro . '
                'Summarize the page in two sentences based on the fetched content.')
SCENES = [
    ('Sora / Live examples', 'Web Search + Web Fetch',
     'Here are two real examples of Sora using Parallel MCP tools. Web Search finds information across the internet. Web Fetch reads the content at a specific URL. We will verify the tool used for each request.'),
    ('01 / Prerequisites', 'Enable both tools',
     'In MCP settings, Parallel must be connected and available to Sora. Web Search and Web Fetch must both be enabled. Each switch controls one tool, and changes take effect on the next message.'),
    ('02 / Search by topic', 'Find the official MCP documentation',
     'First, ask Sora to search the web for the official Model Context Protocol documentation. This request supplies a topic. Parallel Web Search finds relevant pages and returns results that Sora can use in its answer.'),
    ('03 / Search verified', 'Look for the Web Search check mark',
     'The completed activity names Parallel search MCP and Web Search. This confirms that Sora called the external search tool. The answer provides the official website and a short explanation.'),
    ('04 / Fetch a page', 'Read a specific URL',
     'Next, start a new conversation and give Sora a specific page URL. Ask it to use Parallel Web Fetch and summarize the retrieved content. This request reads the selected page rather than searching for pages.'),
    ('05 / Fetch verified', 'Look for the Web Fetch check mark',
     'The completed activity now names Web Fetch. Sora has retrieved the page through Parallel and used the returned content to write its summary. Both examples were executed live through Portage.'),
    ('Sora / Parallel MCP', 'Search to discover. Fetch to read.',
     'Use Web Search when you have a question or topic. Use Web Fetch when you already have a URL. In both cases, check the completed tool activity, and control access using the individual tool switches in MCP settings.'),
]


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'


def main():
    WORK.mkdir(exist_ok=True)
    audio = []
    for index, (_, _, narration) in enumerate(SCENES):
        source, target = WORK / f'{index}.aiff', WORK / f'{index}.wav'
        subprocess.run(['say', '-r', '165', '-o', str(source), narration], check=True)
        subprocess.run([FFMPEG, '-y', '-loglevel', 'error', '-i', str(source),
                        '-ar', '48000', '-ac', '1', str(target)], check=True)
        with wave.open(str(target)) as stream:
            duration = stream.getnframes() / stream.getframerate()
        audio.append((target, duration))

    timings, evidence = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1600, 'height': 900},
            record_video_dir=str(WORK / 'raw'),
            record_video_size={'width': 1600, 'height': 900},
        )
        context.add_init_script(OVERLAY_JS)
        recording_start = time.monotonic()
        page = context.new_page()
        page.set_default_timeout(240000)
        page.goto(BASE)
        page.get_by_role('link', name='Settings', exact=True).click()
        page.wait_for_load_state('networkidle')
        page.add_style_tag(content='.cp-drawer{width:680px!important;max-width:90vw!important}')
        page.evaluate("""() => {
            document.querySelector('#demo-cap').style.cssText += ';left:280px;bottom:18px;max-width:590px';
            window.exampleCard = (title, subtitle, detail) => {
                const card = document.querySelector('#demo-card');
                card.innerHTML = '<div style="font-size:18px;letter-spacing:.2em;color:#7dd3fc">PORTAGE / LIVE MCP EXAMPLES</div><h1>' + title + '</h1><p class="sub">' + subtitle + '</p><div style="font-size:27px;line-height:1.8;color:#dbeafe">' + detail + '</div>';
                card.classList.add('on');
            };
        }""")

        def scene(index):
            kicker, title, _ = SCENES[index]
            page.evaluate('([k,t])=>window.__demo.caption(k,t)', [kicker, title])
            timings.append((time.monotonic() - recording_start, index))
            print(f'SCENE {index}: {title}', flush=True)

        def finish_scene(index):
            elapsed = time.monotonic() - recording_start - timings[-1][0]
            page.wait_for_timeout(max(0, audio[index][1] + 1 - elapsed) * 1000)

        def click(locator):
            locator.scroll_into_view_if_needed()
            bounds = locator.bounding_box()
            page.mouse.move(bounds['x'] + bounds['width'] / 2,
                            bounds['y'] + bounds['height'] / 2, steps=20)
            locator.click()
            page.wait_for_timeout(500)

        def ask(prompt, expected_tool, index):
            scene(index)
            page.locator('textarea[placeholder^="Message Sora"]').fill(prompt)
            with page.expect_response('**/api/copilot/chat') as response:
                click(page.get_by_role('button', name='Send', exact=True))
            events = [json.loads(line[6:]) for line in response.value.text().splitlines()
                      if line.startswith('data: ')]
            expected = 'ext_parallel_search_mcp__' + expected_tool
            successful = any(event['type'] == 'tool_result' and event.get('name') == expected
                             and event.get('ok') is True for event in events)
            record = {'prompt': prompt, 'expected_tool': expected, 'success': successful,
                      'events': [event for event in events if event['type'] != 'token'],
                      'answer': ''.join(event['text'] for event in events if event['type'] == 'token')}
            evidence.append(record)
            (WORK / 'evidence.json').write_text(json.dumps(evidence, indent=2))
            assert successful, record
            page.get_by_role('button', name='Stop', exact=True).wait_for(state='hidden', timeout=240000)
            page.locator('.cp-msg.assistant').last.screenshot(path=str(WORK / f'{expected_tool}.png'))
            finish_scene(index)
            print(f'VALIDATED {expected}', flush=True)

        page.evaluate("exampleCard('Web Search + Web Fetch','Two tools. Two real examples.','Search: discover pages about a topic<br>Fetch: retrieve content from a specific URL')")
        scene(0)
        finish_scene(0)
        page.evaluate("document.querySelector('#demo-card').classList.remove('on')")
        click(page.get_by_role('button', name='MCP server', exact=True))
        server = page.locator('.mcp-card').filter(has_text='parallel_search_mcp')
        server.get_by_text('Connected', exact=True).wait_for(timeout=60000)
        assert server.get_by_role('checkbox', name='Disable Web Search for Sora').is_checked()
        assert server.get_by_role('checkbox', name='Disable Web Fetch for Sora').is_checked()
        server.evaluate("e=>e.scrollIntoView({block:'center'})")
        scene(1)
        finish_scene(1)
        page.keyboard.press('Control+k')
        page.locator('textarea[placeholder^="Message Sora"]').wait_for()
        ask(SEARCH_PROMPT, 'web_search', 2)
        scene(3)
        finish_scene(3)
        click(page.get_by_title('New chat', exact=True))
        ask(FETCH_PROMPT, 'web_fetch', 4)
        scene(5)
        finish_scene(5)
        page.evaluate("exampleCard('Search to discover. Fetch to read.','Both tools validated through Sora','✓ Parallel Web Search<br>✓ Parallel Web Fetch<br>Explicit access controls in MCP settings')")
        scene(6)
        finish_scene(6)
        video = page.video
        context.close()
        raw = video.path()
        browser.close()

    captions, transcript = [], ['# Sora: Web Search and Web Fetch examples', '']
    for start, index in timings:
        narration = SCENES[index][2]
        words = narration.split()
        for offset in range(0, len(words), 15):
            chunk = words[offset:offset + 15]
            begin = start + audio[index][1] * offset / len(words)
            end = start + audio[index][1] * (offset + len(chunk)) / len(words)
            captions.append(f'{len(captions)+1}\n{timestamp(begin)} --> {timestamp(end)}\n'
                            + '\n'.join(textwrap.wrap(' '.join(chunk), 52)) + '\n')
        transcript.extend([f'## {int(start)//60}:{int(start)%60:02} — {SCENES[index][1]}', '', narration, ''])
    transcript.extend(['## Copy these example prompts', '', '**Web Search**', '', SEARCH_PROMPT, '',
                       '**Web Fetch**', '', FETCH_PROMPT, '',
                       'Both expected external tools returned successful tool results in the recorded Sora sessions.', ''])
    stem = ROOT / 'docs/Sora_MCP_Search_and_Fetch'
    subtitle = stem.with_suffix('.srt')
    subtitle.write_text('\n'.join(captions))
    stem.with_suffix('.md').write_text('\n'.join(transcript))
    inputs = ['-i', str(raw)]
    filters, labels = [], []
    for index, (start, _) in enumerate(timings):
        inputs.extend(['-i', str(audio[index][0])])
        filters.append(f'[{index+1}:a]adelay={int(start*1000)}:all=1[a{index}]')
        labels.append(f'[a{index}]')
    filters.append(''.join(labels) + f'amix=inputs={len(labels)}:normalize=0[a]')
    inputs.extend(['-i', str(subtitle)])
    output = stem.with_suffix('.mp4')
    subprocess.run([FFMPEG, '-y', '-loglevel', 'error', *inputs,
                    '-filter_complex', ';'.join(filters), '-map', '0:v', '-map', '[a]',
                    '-map', f'{len(audio)+1}:0', '-c:v', 'libx264', '-crf', '20',
                    '-preset', 'fast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-c:s', 'mov_text',
                    '-metadata:s:s:0', 'language=eng', '-movflags', '+faststart', str(output)], check=True)
    (WORK / 'timings.json').write_text(json.dumps(timings, indent=2))
    print(f'Created {output}', flush=True)


if __name__ == '__main__':
    main()
