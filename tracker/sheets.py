"""Google Sheets access via a service account."""
import re

import gspread

from . import env, models

LIST_SHEET = "Список"
REST_SHEET = "Остальные"
CHEAP_SHEET = "До 20 €"
CHEAP_MAX_PRICE = 20.0
RUNS_SHEET = "Запуски"
SUMMARY_SHEET = "Сводка"
MODELS_SHEET = "Модели"
MANUAL_SHEET = "Ручная разметка"

RUNS_HEADER = [
    "Время", "Полный обход", "Страниц", "Запросов", "МБ", "Секунд", "Новых: список", "Новых: остальные",
    "Поднятых старых", "Проверено страниц товара", "Продано: список", "Продано: остальные", "Удалено",
    "Резерв/скрыт", "Закрыто 3 ч", "Закрыто 30 дн", "Описаний", "Описание → список", "Отложено", "Ошибки",
]
MANUAL_HEADER = ["id (или ссылка)", "Модель", "Комментарий"]
MODELS_HEADER = ["Модель", "Бренд", "Тип", "Формат", "Регион"]


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


class SheetWriter:
    """All sheet writes of a tick. One metadata read, then targeted calls."""

    def __init__(self, spreadsheet):
        self.spreadsheet = spreadsheet
        self._sheets = {ws.title: ws for ws in spreadsheet.worksheets()}

    def _get(self, title, header=None):
        ws = self._sheets.get(title)
        if ws is None:
            ws = self.spreadsheet.add_worksheet(title=title, rows=100, cols=max(len(header or []), 5))
            if header:
                ws.update(range_name="A1", values=[header], value_input_option="RAW")
                ws.freeze(rows=1)
            self._sheets[title] = ws
        return ws

    def replace(self, title, rows):
        """Overwrite a whole sheet with rows (first row is the header)."""
        ws = self._get(title)
        width = max(len(r) for r in rows)
        ws.resize(rows=max(len(rows), 2), cols=width)
        ws.update(range_name="A1", values=rows, value_input_option="RAW")

    def ensure_runs_header(self):
        """'Запуски' may start with the check-setup test row: put the header on top."""
        ws = self._get(RUNS_SHEET, RUNS_HEADER)
        if ws.row_values(1) != RUNS_HEADER:
            ws.insert_row(RUNS_HEADER, 1, value_input_option="RAW")

    def append_run(self, row):
        self._get(RUNS_SHEET, RUNS_HEADER).append_row(row, value_input_option="RAW")

    def ensure_models(self):
        """Fill 'Модели' once; later only append models it lacks (the sheet belongs to the user)."""
        rows = [list(r) for r in models.list_models()]
        if MODELS_SHEET not in self._sheets:
            self._get(MODELS_SHEET, MODELS_HEADER)
            self.replace(MODELS_SHEET, [MODELS_HEADER] + rows)
            return len(rows)
        ws = self._sheets[MODELS_SHEET]
        present = {value.strip() for value in ws.col_values(1)}
        missing = [r for r in rows if r[0] not in present]
        if missing:
            ws.append_rows(missing, value_input_option="RAW")
        return len(missing)

    def manual_labels(self):
        """{item id: model text} from 'Ручная разметка' (created empty if missing)."""
        ws = self._get(MANUAL_SHEET, MANUAL_HEADER)
        labels = {}
        for row in ws.get_all_values()[1:]:
            if len(row) < 2 or not row[1].strip():
                continue
            match = re.search(r"(?:items/)?(\d{5,})", row[0])
            if match:
                labels[int(match.group(1))] = row[1].strip()
        return labels
