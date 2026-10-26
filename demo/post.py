"""Post-production for the Sora demo: trim the start, speed up the model-wait stretches, encode a 1600x900 MP4.

Run after record.py:   uv run --with imageio-ffmpeg python demo/post.py
"""
import json
import os
import subprocess

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.environ.get("SORA_DEMO_WORK", "/tmp/sora-demo")
OUT = os.environ.get("SORA_DEMO_OUT", f"{ROOT}/docs/Sora_Demo.mp4")
TRIM_START = 1.0            # drops the blank page before the title card appears
MAX_SPEED, MIN_FAST_SECONDS = 6.0, 2.5

meta = json.load(open(f"{WORK}/segments.json"))
segments = [(max(s, TRIM_START), e) for s, e in meta["segments"]]

pieces, cursor, idx = [], TRIM_START, 0
parts = []
for start, end in segments:
    if start > cursor:
        parts.append(f"[0:v]trim=start={cursor:.3f}:end={start:.3f},setpts=PTS-STARTPTS[v{idx}]")
        pieces.append(f"[v{idx}]")
        idx += 1
    speed = min(MAX_SPEED, max(1.0, (end - start) / MIN_FAST_SECONDS))
    parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=(PTS-STARTPTS)/{speed:.3f}[v{idx}]")
    pieces.append(f"[v{idx}]")
    idx += 1
    cursor = end
parts.append(f"[0:v]trim=start={cursor:.3f},setpts=PTS-STARTPTS[v{idx}]")
pieces.append(f"[v{idx}]")
graph = ";".join(parts) + f";{''.join(pieces)}concat=n={len(pieces)}:v=1:a=0,fps=30,format=yuv420p[out]"

os.makedirs(os.path.dirname(OUT), exist_ok=True)
cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", f"{WORK}/raw.webm",
       "-filter_complex", graph, "-map", "[out]", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
       "-movflags", "+faststart", OUT]
subprocess.run(cmd, check=True)
print(f"wrote {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)")
