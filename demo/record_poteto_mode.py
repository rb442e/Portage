"""Render an original narrated motion-graphics guide to the installed poteto-mode skill.

Run: uv run --offline --with playwright --with imageio-ffmpeg python demo/record_poteto_mode.py
Uses macOS say and Playwright Chromium. No Portage server or model requests are made.
Outputs the MP4, optional captions, transcript, and source provenance under docs/.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import textwrap
import time
import wave

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WORK = Path('/tmp/poteto-mode-explainer')
SOURCE = Path.home() / '.codex/plugins/cache/cursor-plugins/pstack/0.15.30/skills/poteto-mode/SKILL.md'
SCENES = json.loads((ROOT / 'demo/poteto_mode_scenes.json').read_text())
HTML = ROOT / 'demo/poteto_mode_explainer.html'
STEM = ROOT / 'docs/Poteto_Mode_Explained'
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def run(command):
    subprocess.run(command, check=True)


def timestamp(seconds):
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds, millis = divmod(millis, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'


def main():
    WORK.mkdir(exist_ok=True)
    voices = subprocess.check_output(['say', '-v', '?'], text=True)
    voice = 'Samantha' if any(line.startswith('Samantha ') for line in voices.splitlines()) else None
    audio = []
    for i, scene in enumerate(SCENES):
        aiff, wav = WORK / f'{i:02}.aiff', WORK / f'{i:02}.wav'
        fingerprint = hashlib.sha256((str(voice) + '168' + scene['narration']).encode()).hexdigest()
        signature = WORK / f'{i:02}.sha256'
        if not aiff.exists() or not signature.exists() or signature.read_text() != fingerprint:
            command = ['say', '-r', '168', '-o', str(aiff)]
            if voice:
                command.extend(['-v', voice])
            run([*command, scene['narration']])
            signature.write_text(fingerprint)
        run([FFMPEG, '-y', '-loglevel', 'error', '-i', str(aiff), '-ar', '48000', '-ac', '1', str(wav)])
        with wave.open(str(wav)) as stream:
            duration = stream.getnframes() / stream.getframerate()
        audio.append((wav, duration))
    print(f'Narration ready: {sum(item[1] for item in audio):.1f} seconds; voice={voice or "system default"}', flush=True)
    timings = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080},
            record_video_dir=str(WORK / 'raw'), record_video_size={'width': 1920, 'height': 1080},
            device_scale_factor=1)
        started = time.monotonic()
        page = context.new_page()
        page.goto(HTML.as_uri())
        page.evaluate('document.fonts.ready')
        for i, scene in enumerate(SCENES):
            page.evaluate('([s,i,n])=>window.showScene(s,i,n)', [scene, i, len(SCENES)])
            start = time.monotonic() - started
            timings.append({'start': start, 'duration': audio[i][1], 'scene': scene['id'], 'chapter': scene['chapter']})
            print(f'Scene {i+1}/{len(SCENES)}: {scene["id"]}', flush=True)
            page.wait_for_timeout(900)
            page.screenshot(path=str(WORK / f'scene-{i:02}.png'))
            if i == 0:
                page.screenshot(path=str(STEM.with_suffix('.png')))
            require_no_overflow = page.evaluate("""() => {
                const ids=['header','stage','takeaway'];
                return ids.map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect();
                    return {id,right:r.right,bottom:r.bottom,scroll:e.scrollWidth,client:e.clientWidth};});
            }""")
            for element in require_no_overflow:
                if element['right'] > 1921 or element['bottom'] > 1081 or element['scroll'] > element['client'] + 2:
                    raise RuntimeError('Layout overflow: ' + json.dumps(element))
            page.wait_for_timeout(max(0, (audio[i][1] + 1.4) * 1000 - 900))
        video = page.video
        context.close()
        raw = video.path()
        browser.close()
    transcript = ['# Poteto-mode: From intent to evidence', '',
        'An original narrated visual explanation of Lauren Tan’s installed pstack 0.15.30 instructions. '
        'This is an illustrated explainer, not a recording of an agent implementing OAuth. '
        'Narration uses synthetic speech. Interpretations of author intent are labeled as interpretations.', '']
    subtitles = []
    for scene, timing in zip(SCENES, timings):
        words = scene['narration'].split()
        for offset in range(0, len(words), 14):
            chunk = words[offset:offset+14]
            start = timing['start'] + timing['duration'] * offset / len(words)
            end = timing['start'] + timing['duration'] * (offset + len(chunk)) / len(words)
            subtitles.append(f'{len(subtitles)+1}\n{timestamp(start)} --> {timestamp(end)}\n' +
                '\n'.join(textwrap.wrap(' '.join(chunk), 52)) + '\n')
        start = int(timing['start'])
        transcript.extend([f'## {start//60}:{start%60:02} · {scene["chapter"]}', '', scene['narration'], '',
                           '**On-screen takeaway:** ' + scene['takeaway'], ''])
    transcript.extend(['## Sources and scope', '',
        '- Primary source: the installed `pstack/0.15.30/skills/poteto-mode/SKILL.md`.',
        '- Public upstream: https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/SKILL.md',
        '- Feature playbook: https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/feature.md',
        '- Architecture workflow: https://github.com/cursor/plugins/blob/main/pstack/skills/architect/SKILL.md',
        '- Prompting guidance: https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-help/references/prompting.md',
        '- License: https://github.com/cursor/plugins/blob/main/pstack/LICENSE',
        '- Upstream pstack is MIT licensed, Copyright (c) 2026 Lauren Tan. The visuals and narration are original paraphrase and interpretation.',
        '', 'The explanation illustrates workflow intent; it does not establish exact behavior across all agent hosts. '
        'Cursor-specific agents, models, and persistent modes may not be available in Codex. '
        'The user’s authorization and the host’s actual permissions govern execution. '
        'The OAuth states and alternatives are conceptual, not implemented Portage functionality.', ''])
    subtitle_path = STEM.with_suffix('.srt')
    subtitle_path.write_text('\n'.join(subtitles))
    STEM.with_suffix('.md').write_text('\n'.join(transcript))
    inputs, filters, labels = ['-i', str(raw)], [], []
    for i, (path, _) in enumerate(audio):
        inputs.extend(['-i', str(path)])
        filters.append(f'[{i+1}:a]adelay={int(timings[i]["start"]*1000)}:all=1[a{i}]')
        labels.append(f'[a{i}]')
    filters.append(''.join(labels) + f'amix=inputs={len(labels)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]')
    inputs.extend(['-i', str(subtitle_path)])
    chapter_lines = [';FFMETADATA1', 'title=Poteto-mode: From intent to evidence']
    for i, chapter in enumerate(timings):
        end = timings[i+1]['start'] if i+1 < len(timings) else chapter['start'] + chapter['duration'] + 1.4
        chapter_lines.extend(['[CHAPTER]', 'TIMEBASE=1/1000',
                              f'START={int(chapter["start"]*1000)}', f'END={int(end*1000)}',
                              'title=' + chapter['chapter']])
    chapter_path = WORK / 'chapters.ffmetadata'
    chapter_path.write_text('\n'.join(chapter_lines) + '\n')
    inputs.extend(['-i', str(chapter_path)])
    run([FFMPEG, '-y', '-loglevel', 'error', *inputs, '-filter_complex', ';'.join(filters),
         '-map', '0:v', '-map', '[a]', '-map', f'{len(audio)+1}:0', '-c:v', 'libx264', '-crf', '19',
         '-preset', 'fast', '-r', '30', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-ar', '48000',
         '-c:s', 'mov_text', '-map_metadata', str(len(audio)+2), '-map_chapters', str(len(audio)+2), '-metadata:s:s:0', 'language=eng', '-movflags', '+faststart',
         '-metadata', 'title=Poteto-mode: From intent to evidence', str(STEM.with_suffix('.mp4'))])
    provenance = {'source': str(SOURCE), 'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  'version': '0.15.30', 'voice': voice or 'system default', 'chapters': timings,
                  'video': str(STEM.with_suffix('.mp4')), 'kind': 'illustrated educational explanation'}
    STEM.with_suffix('.json').write_text(json.dumps(provenance, indent=2))
    print('Created ' + str(STEM.with_suffix('.mp4')), flush=True)


if __name__ == '__main__':
    main()
