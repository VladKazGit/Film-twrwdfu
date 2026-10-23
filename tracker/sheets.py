"""Google Sheets access via a service account."""
import re

import gspread

from . import env, models

LIST_SHEET = "Список"
REST_SHEET = "Остальные"
CHEAP_SHEET = "До 20 €"
FAST_SHEET = "Быстрые продажи"
SALES_SHEET = "Продажи"
CHECK_SHEET = "Проверка"
CHEAP_MAX_PRICE = 20.0
RUNS_SHEET = "Запуски"
SUMMARY_SHEET = "Сводка"
TOP_SHEET = "Топ-10"
PHOTO_KEEP_SHEET = "По фото: оставить"   # kept by the photo verdict (and the ones for 'Список'), trial
PHOTO_DROP_SHEET = "По фото: убрать"     # no longer written: removed once to lighten the table
OLD_PHOTO_SHEET = "По фото (проба)"
UNNAMED_SHEET = "По фото: без названия"  # no name after three photos: for 'Ручная разметка'
PROPOSAL_SHEET = "Предложение"  # named cameras outside the list: for the user to pick new list models
SIBLINGS_SHEET = "Братья моделей списка"  # cameras outside the list next to list models, for the user      # the one sheet before the split: removed once
ANALYTICS_SHEET = "Аналитика"
MODELS_SHEET = "Модели"
MANUAL_SHEET = "Ручная разметка"

# The order before v5; rows written then are moved into the current order once.
RUNS_HEADER_V4 = [
    "Время", "Полный обход", "Страниц", "Запросов", "МБ", "Секунд", "Новых: список", "Новых: остальные",
    "Поднятых старых", "Проверено страниц товара", "Продано: список", "Продано: остальные", "Удалено",
    "Резерв/скрыт", "Закрыто 3 ч", "Закрыто 30 дн", "Описаний", "Описание → список", "Отложено", "Ошибки",
    "Комментарий", "Новых в «До 20 €»", "Проверок между тиками",
]
# v5: what changed comes first, right after the time
RUNS_FRONT = ["Новых в «До 20 €»", "Комментарий"]
RUNS_HEADER = RUNS_HEADER_V4[:1] + RUNS_FRONT + [c for c in RUNS_HEADER_V4[1:] if c not in RUNS_FRONT]
_RUNS_FROM_V4 = [RUNS_HEADER_V4.index(c) for c in RUNS_HEADER]
MANUAL_HEADER = ["id (или ссылка)", "Модель", "Комментарий"]
MODELS_HEADER = ["Модель", "Бренд", "Тип", "Формат", "Регион"]
LIGHT_GREEN_3 = {"red": 217 / 255, "green": 234 / 255, "blue": 211 / 255}  # #d9ead3
LIGHT_BLUE_3 = {"red": 207 / 255, "green": 226 / 255, "blue": 243 / 255}  # #cfe2f3
LIGHT_YELLOW_3 = {"red": 255 / 255, "green": 242 / 255, "blue": 204 / 255}  # #fff2cc


def _same_color(a, b):
    """The API leaves zero channels out and rounds floats."""
    return all(abs(a.get(k, 0) - b.get(k, 0)) < 0.01 for k in ("red", "green", "blue"))


def _as_typed(cell):
    """Text stays literal under USER_ENTERED; links become clickable."""
    if not isinstance(cell, str) or not cell or cell.startswith(("http://", "https://")):
        return cell
    if cell.startswith('=IMAGE("https://images'):  # the photo column of 'По фото (проба)' (photos.image_formula)
        return cell
    return "'" + cell


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

    def delete(self, title):
        """Remove a sheet the tracker made and no longer writes (nothing of the user's is on it)."""
        ws = self._sheets.pop(title, None)
        if ws is not None:
            self.spreadsheet.del_worksheet(ws)

    def set_row_height(self, title, pixels):
        """Taller data rows (the header stays), e.g. room for photos."""
        ws = self._get(title)
        if ws.row_count < 2:
            return
        self.spreadsheet.batch_update({"requests": [{"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "ROWS", "startIndex": 1, "endIndex": ws.row_count},
            "properties": {"pixelSize": pixels}, "fields": "pixelSize"}}]})

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

    def recolor_rules(self, titles, old, new):
        """Change the background of existing conditional-format rules from `old` to `new`.
        Returns how many rules changed."""
        meta = self.spreadsheet.fetch_sheet_metadata(
            params={"fields": "sheets(properties(sheetId,title),conditionalFormats)"})
        requests = []
        for sheet in meta.get("sheets", []):
            if sheet["properties"]["title"] not in titles:
                continue
            for index, rule in enumerate(sheet.get("conditionalFormats", [])):
                boolean = rule.get("booleanRule")
                if not boolean or not _same_color(boolean.get("format", {}).get("backgroundColor", {}), old):
                    continue
                requests.append({"updateConditionalFormatRule": {
                    "index": index, "sheetId": sheet["properties"]["sheetId"],
                    "rule": {"ranges": rule["ranges"], "booleanRule": {
                        "condition": boolean["condition"], "format": {"backgroundColor": new}}}}})
        if requests:
            self.spreadsheet.batch_update({"requests": requests})
        return len(requests)

    def replace(self, title, rows, links=False):
        """Overwrite a whole sheet with rows (first row is the header).

        links=True writes 'as typed' so URLs become clickable; every other text
        cell gets a leading apostrophe so it stays literal text (no formulas,
        no dates from '2026-10-16 15:52').
        """
        ws = self._get(title)
        width = max(len(r) for r in rows)
        if len(rows) < 2:  # the sheet keeps 2 rows (frozen header): blank the old data row
            rows = rows + [[""] * width]
        ws.resize(rows=len(rows), cols=width)
        if links:
            rows = [[_as_typed(c) for c in r] for r in rows]
        ws.update(range_name="A1", values=rows, value_input_option="USER_ENTERED" if links else "RAW")

    def ensure_runs_header(self):
        """'Запуски' may start with the check-setup test row (header goes on top) or with
        an older header of the v4 order, maybe shorter: then every row moves into the
        current order (numbers stay numbers)."""
        ws = self._get(RUNS_SHEET, RUNS_HEADER)
        first = ws.row_values(1)
        if first == RUNS_HEADER:
            return
        ws.resize(cols=max(len(RUNS_HEADER), 5))
        if first and first == RUNS_HEADER_V4[:len(first)]:
            rows = ws.get_values(value_render_option="UNFORMATTED_VALUE")
            moved = [[r[i] if i < len(r) else "" for i in _RUNS_FROM_V4] for r in rows]
            moved[0] = list(RUNS_HEADER)
            ws.update(range_name="A1", values=moved, value_input_option="RAW")
            # the comment now sits in column C: give it room
            self.spreadsheet.batch_update({"requests": [{"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                "properties": {"pixelSize": 450}, "fields": "pixelSize"}}]})
        else:
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
