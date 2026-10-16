"""Private data repo layout (the source of truth).

items/active/<id>.json            tracked items
items/closed/<YYYY-MM>/<id>.json  closed items (by closing month)
state.json                        tracker state between ticks
runs.jsonl                        one aggregate line per tick
listings.csv, price_history.csv, summary.json, README.md   daily exports
"""
import csv
import json
from pathlib import Path

CSV_FIELDS = [
    "id", "url", "title", "condition", "brand", "model", "model_source", "in_list", "group",
    "mech_type", "region", "format", "kit", "kit_details", "price_start", "price_final", "favourites",
    "listed_after", "first_seen", "last_seen_active", "sold_detected_at", "closed_at", "status",
    "time_to_sell_min", "time_to_sell_max", "days_to_sell", "vinted_listed_est", "flags", "seller_id",
]


class DataStore:
    def __init__(self, root):
        self.root = Path(root)
        self.active_dir = self.root / "items" / "active"
        self.closed_dir = self.root / "items" / "closed"

    # ---- state and runs

    def load_state(self):
        path = self.root / "state.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def save_state(self, state):
        self._write_json(self.root / "state.json", state)

    def append_run(self, run):
        with (self.root / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(run, ensure_ascii=False) + "\n")

    # ---- items

    def load_active(self):
        return {item["id"]: item for item in self._read_all(self.active_dir)}

    def load_closed(self):
        return {item["id"]: item for item in self._read_all(self.closed_dir)}

    def save(self, item):
        """Write an item; a closed one moves from active/ to closed/<month>/, a reopened one back."""
        name = f"{item['id']}.json"
        if item.get("closed_at"):
            self._write_json(self.closed_dir / item["closed_at"][:7] / name, item)
            (self.active_dir / name).unlink(missing_ok=True)
        else:
            self._write_json(self.active_dir / name, item)
            for old in self.closed_dir.glob(f"*/{name}"):
                old.unlink()

    # ---- daily exports

    def write_exports(self, items, summary, readme):
        items = sorted(items, key=lambda i: i["id"])
        with (self.root / "listings.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for item in items:
                row = dict(item)
                row["kit_details"] = "; ".join(item.get("kit_details") or [])
                row["flags"] = "; ".join(item.get("flags") or [])
                writer.writerow(row)
        with (self.root / "price_history.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "at", "price"])
            for item in items:
                for point in item.get("price_history") or []:
                    writer.writerow([item["id"], point["at"], point["price"]])
        self._write_json(self.root / "summary.json", summary)
        (self.root / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    # ---- helpers

    @staticmethod
    def _read_all(directory):
        for path in sorted(directory.rglob("*.json")):
            yield json.loads(path.read_text("utf-8"))

    @staticmethod
    def _write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
