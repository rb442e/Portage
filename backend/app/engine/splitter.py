"""CSV row-splitter for the standalone Split File tool.

Splits one CSV into part files of at most ``max_rows`` data rows, repeating the
header row in every part so each file is independently importable. This mirrors
the exporter's per-type split, exposed as a general-purpose utility that lives
outside the migration workflow. Streams via the stdlib ``csv`` module so large
files and quoted fields (multi-line descriptions) are handled without loading
the whole file into memory.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Allow very large single fields (e.g. long descriptions) so a row is never truncated.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def split_csv_file(
    src,
    out_dir,
    max_rows: int = 1000,
    base: Optional[str] = None,
    encoding: str = "utf-8-sig",
    has_header: bool = True,
) -> List[Dict[str, object]]:
    """Split ``src`` into ``<base>_partNN.csv`` chunks of at most ``max_rows``
    data rows, writing the header row into every chunk.

    When the file holds at most ``max_rows`` data rows a single ``<base>.csv`` is
    written instead. Returns one ``{"name", "rows", "path"}`` record per file.
    """
    if max_rows <= 0:
        raise ValueError("max_rows must be > 0")

    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"input CSV not found: {src}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = base or src.stem

    files: List[Dict[str, object]] = []

    def _write_part(part_no: int, header, rows) -> None:
        fname = f"{stem}_part{part_no:02d}.csv"
        path = out / fname
        with path.open("w", newline="", encoding=encoding) as out_fh:
            writer = csv.writer(out_fh)
            if header is not None:
                writer.writerow(header)
            writer.writerows(rows)
        files.append({"name": fname, "rows": len(rows), "path": str(path)})

    with src.open("r", newline="", encoding=encoding) as fh:
        reader = csv.reader(fh)
        header = next(reader, None) if has_header else None
        part_no = 0
        buffer: List[List[str]] = []
        for row in reader:
            buffer.append(row)
            if len(buffer) >= max_rows:
                part_no += 1
                _write_part(part_no, header, buffer)
                buffer = []
        if buffer or part_no == 0:
            part_no += 1
            _write_part(part_no, header, buffer)

    # A file that fit in a single chunk keeps its plain <base>.csv name.
    if len(files) == 1:
        only = files[0]
        plain = out / f"{stem}.csv"
        Path(only["path"]).replace(plain)
        only["name"] = plain.name
        only["path"] = str(plain)

    return files
