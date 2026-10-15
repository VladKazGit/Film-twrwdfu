"""Manual access check: Google Sheet (sheet 'Запуски') and the private data repo.

Run: python -m tracker.check_setup
Logs only say OK/FAIL per target, never ids, names or keys.
"""
import os
import sys
import tempfile
from pathlib import Path

from . import env

RUNS_SHEET = "Запуски"

HINTS = {
    "SpreadsheetNotFound": "check SHEET_ID and that the service account has Editor access",
    "APIError": "check that Google Sheets API is enabled for the service account's project",
    "DataRepoError": "check DATA_REPO (owner/name) and that DATA_TOKEN has Contents: read & write",
}


def check_sheet(stamp, run_ref):
    from . import sheets

    ws = sheets.worksheet(sheets.open_spreadsheet(), RUNS_SHEET)
    ws.append_row([stamp, "check-setup", "test row", run_ref], value_input_option="RAW")


def check_data_repo(stamp, run_ref):
    from . import datarepo

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        repo = datarepo.clone(Path(tmp) / "data")
        path = repo / "checks" / "setup-check.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} check-setup run {run_ref}\n")
        datarepo.commit_and_push(repo, f"check-setup {stamp}")


def main():
    stamp = env.now_berlin().strftime("%Y-%m-%d %H:%M")
    run_ref = os.environ.get("GITHUB_RUN_ID", "local")
    failed = 0
    for name, check in (("Google Sheet", check_sheet), ("Data repo", check_data_repo)):
        try:
            check(stamp, run_ref)
            print(f"{name}: OK")
        except Exception as exc:
            failed += 1
            kind = type(exc).__name__
            hint = HINTS.get(kind, "")
            print(f"{name}: FAIL ({kind}: {env.redact(exc)})" + (f" -> {hint}" if hint else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
