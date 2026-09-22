import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
import pandas as pd
from app.engine.parent_map import parse_parent_map, apply_parent_map
from app.engine.exporter import build_dataframe
from app.schemas import NormalizedIssue

ROOT = Path(__file__).resolve().parent
_, _, us_map = parse_parent_map(pd.read_csv(ROOT / "parent.csv", dtype=str, keep_default_na=False))

# Case A: real features from MIG (Epic parents) + an EPIC parent.csv
epic_map = {"E25855": "16510001", "E27489": "16510002"}
feats = [
    NormalizedIssue(row_id="F190763", external_id="F190763", issue_type="Feature",
                    summary="feat1", extra={"parent": "Epic E25855: 2024 Data...", "epic_id": ""}),
    NormalizedIssue(row_id="F226885", external_id="F226885", issue_type="Feature",
                    summary="feat2", extra={"parent": "Epic E27489: Data Platform...", "epic_id": ""}),
]
n = apply_parent_map(feats, epic_map)
print(f"[A] features + epic map: resolved {n}/2")
print(build_dataframe(feats, {})[["Issue Id", "Rally ID", "Parent Id"]].to_string(index=False))

# Case B: same features but with the USER-STORY parent.csv (should NOT match)
feats2 = [NormalizedIssue(row_id="F190763", external_id="F190763", issue_type="Feature",
                          summary="feat1", extra={"parent": "Epic E25855: ..."})]
print(f"\n[B] features + US map: resolved {apply_parent_map(feats2, us_map)}/1 (expect 0) -> Parent Id:",
      build_dataframe(feats2, {})['Parent Id'].tolist())

# Case C: defect whose parent is a user story in parent.csv (existing behavior)
defs = [NormalizedIssue(row_id="DE1", external_id="DE1", issue_type="Defect",
                        summary="d", parent_row_id="US2209512")]
print(f"\n[C] defect + US map: resolved {apply_parent_map(defs, us_map)}/1 -> Parent Id:",
      build_dataframe(defs, {})['Parent Id'].tolist())
