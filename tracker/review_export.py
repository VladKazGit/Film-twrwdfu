"""Export the user's review of the sheets: the row colours, cell notes and comments of 'По фото: без
названия', 'Предложение' and 'Братья моделей списка', into review/export.json of the private data
repo (run by the 'review export' workflow). Logs show counts only.

    python -m tracker.review_export
"""
import json
import tempfile
from pathlib import Path

from . import datarepo, sheets

SHEETS = (sheets.UNNAMED_SHEET, sheets.PROPOSAL_SHEET, sheets.SIBLINGS_SHEET)
FIELDS = ("sheets(properties(title),data(rowData(values(formattedValue,note,"
          "userEnteredFormat(backgroundColor),effectiveFormat(backgroundColor)))))")


def _color(cell):
    fmt = cell.get("userEnteredFormat") or cell.get("effectiveFormat") or {}
    rgb = fmt.get("backgroundColor") or {}
    return [round(rgb.get(k, 0), 3) for k in ("red", "green", "blue")] if rgb else None


def export(spreadsheet):
    data = spreadsheet.fetch_sheet_metadata(params={"ranges": [f"'{t}'" for t in SHEETS], "includeGridData": "true",
                                                    "fields": FIELDS})
    out = {}
    for sheet in data.get("sheets", []):
        title = sheet["properties"]["title"]
        rows = []
        for n, row in enumerate((sheet.get("data") or [{}])[0].get("rowData") or [], 1):
            cells = row.get("values") or []
            rows.append({"row": n, "values": [c.get("formattedValue", "") for c in cells],
                         "colors": [_color(c) for c in cells],
                         "notes": {str(k): c["note"] for k, c in enumerate(cells) if c.get("note")}})
        out[title] = rows
    comments = []
    try:  # Drive comments on the spreadsheet (the sheet's own notes are above)
        resp = spreadsheet.client.request(  # gspread's HTTP client, with the service account's Drive scope
            "get", f"https://www.googleapis.com/drive/v3/files/{spreadsheet.id}/comments",
            params={"fields": "comments(content,anchor,quotedFileContent,resolved,replies(content)),nextPageToken",
                    "pageSize": 100})
        comments = resp.json().get("comments", [])
    except Exception as exc:
        print(f"review: comments not read: {type(exc).__name__}")
    every = [{"title": ws.title, "rows": ws.row_count, "cols": ws.col_count} for ws in spreadsheet.worksheets()]
    return {"sheets": out, "comments": comments, "all_sheets": every}


def main():
    spreadsheet = sheets.open_spreadsheet()
    review = export(spreadsheet)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = datarepo.clone(Path(tmp) / "data")
        (root / "review").mkdir(exist_ok=True)
        (root / "review" / "export.json").write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        datarepo.commit_and_push(root, "review export")
    rows = {t: len(r) for t, r in review["sheets"].items()}
    notes = sum(len(r["notes"]) for rs in review["sheets"].values() for r in rs)
    print(f"review: rows {rows}, notes {notes}, comments {len(review['comments'])}")


if __name__ == "__main__":
    main()
