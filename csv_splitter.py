#!/usr/bin/env python3
"""Standalone CSV splitter.

Split one CSV file into several part files by row count, repeating the header
(first) row in every output file so each split is independently importable. This
is the same split behavior Portage's exporter uses, extracted as a reusable,
dependency-free (stdlib only) utility that works directly on a file.

    python csv_splitter.py --in data.csv --rows 200
    # -> data_part01.csv, data_part02.csv, ...  (each carries the original header)
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Jira's CSV importer reformats quoting when it re-serializes; allow very large
# single fields (descriptions) so the reader never truncates a row.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def split_csv(
    input_path,
    out_dir=None,
    max_rows: int = 1000,
    base: Optional[str] = None,
    encoding: str = "utf-8-sig",
    has_header: bool = True,
) -> List[Dict[str, object]]:
    """Split ``input_path`` into ``<base>_partNN.csv`` chunks of at most
    ``max_rows`` data rows, writing the header row into every chunk.

    When the file has at most ``max_rows`` data rows a single ``<base>.csv`` is
    written instead (mirrors the exporter's un-split output). Returns one
    ``{"name", "rows", "path"}`` record per file produced.
    """
    if max_rows <= 0:
        raise ValueError("max_rows must be > 0")

    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"input CSV not found: {src}")
    out = Path(out_dir) if out_dir else src.parent
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Split a CSV into part files, keeping the header in each.")
    ap.add_argument("--in", dest="input_path", required=True, help="Path to the source CSV file.")
    ap.add_argument("--out", dest="out_dir", default=None, help="Output directory (default: source file's folder).")
    ap.add_argument("--rows", dest="max_rows", type=int, default=1000, help="Max data rows per part file (default: 1000).")
    ap.add_argument("--prefix", dest="base", default=None, help="Base name for parts (default: source file name).")
    ap.add_argument("--encoding", default="utf-8-sig", help="File encoding (default: utf-8-sig).")
    ap.add_argument("--no-header", dest="has_header", action="store_false", help="Treat the file as having no header row.")
    args = ap.parse_args()

    files = split_csv(
        args.input_path,
        out_dir=args.out_dir,
        max_rows=args.max_rows,
        base=args.base,
        encoding=args.encoding,
        has_header=args.has_header,
    )
    for f in files:
        print(f"{f['name']}\t{f['rows']} rows")
    print(f"Wrote {len(files)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
