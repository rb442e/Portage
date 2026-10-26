"""Create optional closed captions from the MCP recording's narration and scene times."""
import json
import sys
import textwrap
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_mcp import ROOT, WORK, SCENES


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'


def main():
    timings = json.loads((WORK / 'timings.json').read_text())
    captions = []
    transcript = ['# Portage MCP walkthrough — narration', '']
    for i, (start, title) in enumerate(timings):
        narration = SCENES[i][2]
        with wave.open(str(WORK / f'{i}.wav')) as audio:
            duration = audio.getnframes() / audio.getframerate()
        words = narration.split()
        for offset in range(0, len(words), 15):
            chunk = words[offset:offset + 15]
            begin = start + duration * offset / len(words)
            end = start + duration * (offset + len(chunk)) / len(words)
            captions.append(f'{len(captions)+1}\n{timestamp(begin)} --> {timestamp(end)}\n' + '\n'.join(textwrap.wrap(' '.join(chunk), 52)) + '\n')
        transcript.extend([f'## {int(start)//60}:{int(start)%60:02} — {title}', '', narration, ''])
    (ROOT / 'docs/Sora_MCP_Walkthrough.srt').write_text('\n'.join(captions))
    (ROOT / 'docs/Sora_MCP_Transcript.md').write_text('\n'.join(transcript))


if __name__ == '__main__':
    main()
