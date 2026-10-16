"""Google Sheets access via a service account."""
import re

import gspread

from . import env, models

LIST_SHEET = "Список"
REST_SHEET = "Остальные"
CHEAP_SHEET = "До 20 €"
FAST_SHEET = "Быстрые продажи"
SALES_SHEET = "Продажи"
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
LIGHT_GREEN_3 = {"red": 217 / 255, "green": 234 / 255, "blue": 211 / 255}  # #d9ead3
LIGHT_BLUE_3 = {"red": 207 / 255, "green": 226 / 255, "blue": 243 / 255}  # #cfe2f3
LIGHT_YELLOW_3 = {"red": 255 / 255, "green": 242 / 255, "blue": 204 / 255}  # #fff2cc


def column_letter(index):
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def model_key(name):
    """Comparable model name: 'Zenit-E', 'zenit e' and 'Зенит Е' are the same."""
    return re.sub(r"[^a-z0-9]", "", models.normalize(name or ""))


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

    def has(self, title):
        return title in self._sheets

    def color_active_status(self, titles, column):
        """Light green 3 background for 'активен' in the status column (conditional format,
        survives the per-tick rewrites)."""
        requests = [{"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [{"sheetId": self._sheets[t].id, "startRowIndex": 1,
                        "startColumnIndex": column, "endColumnIndex": column + 1}],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "активен"}]},
                            "format": {"backgroundColor": LIGHT_GREEN_3}}}}} for t in titles]
        self.spreadsheet.batch_update({"requests": requests})

    def color_new_rows(self, title, flag_column, width, index, color=LIGHT_BLUE_3):
        """Colour rows where the flag column says 'да'. Inserted below the status rule
        (index 1) so an active status cell stays green; a rule inserted later at the
        same index sits above the earlier ones."""
        letter = column_letter(flag_column)
        self.spreadsheet.batch_update({"requests": [{"addConditionalFormatRule": {"index": index, "rule": {
            "ranges": [{"sheetId": self._sheets[title].id, "startRowIndex": 1,
                        "startColumnIndex": 0, "endColumnIndex": width}],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                          "values": [{"userEnteredValue": f'=${letter}2="да"'}]},
                            "format": {"backgroundColor": color}}}}}]})

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

    def sync_models(self, offered):
        """'Модели' belongs to the user and filters 'До 20 €'.

        Creates it if missing; otherwise appends only dictionary models never
        offered before, so models the user deleted stay deleted.
        Returns (dictionary models now offered, keys of the models in the sheet).
        """
        rows = [list(r) for r in models.list_models()]
        names = [r[0] for r in rows]
        if MODELS_SHEET not in self._sheets:
            self._get(MODELS_SHEET, MODELS_HEADER)
            self.replace(MODELS_SHEET, [MODELS_HEADER] + rows)
            return names, {model_key(n) for n in names}
        ws = self._sheets[MODELS_SHEET]
        keys = {model_key(v) for v in ws.col_values(1)[1:] if v.strip()}
        new = [r for r in rows if r[0] not in offered and model_key(r[0]) not in keys]
        if new:
            ws.append_rows(new, value_input_option="RAW")
            keys |= {model_key(r[0]) for r in new}
        return names, keys

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
