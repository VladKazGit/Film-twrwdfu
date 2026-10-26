"""Export the lens spreadsheet (secret LENS_SHEET_ID) - the titles of its sheets and the values of the
first one, the user's list of lenses - into lenses/sheet_export.json of the private data repo (run by
the 'lens sheet export' workflow). Logs show counts only.

    python -m tracker.lens_sheet
"""
import json
import tempfile
from pathlib import Path

import gspread

from . import datarepo, env


def export(spreadsheet):
    worksheets = spreadsheet.worksheets()
    return {"sheets": [{"title": ws.title, "rows": ws.row_count, "cols": ws.col_count} for ws in worksheets],
            "first": worksheets[0].get_all_values() if worksheets else []}


def main():
    client = gspread.service_account_from_dict(env.google_sa_info())
    data = export(client.open_by_key(env.sheet_id("LENS_SHEET_ID")))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = datarepo.clone(Path(tmp) / "data")
        (root / "lenses").mkdir(exist_ok=True)
        (root / "lenses" / "sheet_export.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        datarepo.commit_and_push(root, "lens sheet export")
    print(f"lens sheet: {len(data['sheets'])} sheets, first has {len(data['first'])} rows")


if __name__ == "__main__":
    main()
