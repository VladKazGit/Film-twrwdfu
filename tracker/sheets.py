"""Google Sheets access via a service account."""
import gspread

from . import env


def open_spreadsheet():
    client = gspread.service_account_from_dict(env.google_sa_info())
    return client.open_by_key(env.sheet_id())


def worksheet(spreadsheet, title, header=None, cols=20):
    """Return the worksheet `title`, creating it (with `header`) if missing."""
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=cols)
        if header:
            ws.append_row(header, value_input_option="RAW")
        return ws
