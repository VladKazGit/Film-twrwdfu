"""Labels 'Остальные' by the listing's first photo (trial mode: the verdict is only recorded).

Free and local: CLIP (an open image-text model, CPU) compares the photo with a gallery of
reference fingerprints from the tracker's own data (list cameras by model, the kinds of junk
by the text rules) and with descriptions of cameras and other things; OCR reads the name
printed on the camera, and the model rules (models.find_models) look for a list model in it.

The gallery lives in the private data repo (photo_gallery.pt). Without the libraries or the
gallery the step is off. Verdicts: ["drop", reason], ["list", model, "надпись" | "вид"],
["keep"], ["gone"] (the photo is no longer online).
"""
import random
import re
import time

from . import clock, models

ARCH, WEIGHTS = "ViT-L-14", "laion2b_s32b_b82k"
GALLERY_FILE = "photo_gallery.pt"
BACKFILL_FILE = "photo_labels_backfill.json"  # archive verdicts labelled outside the tracker
K = 7
LOOK_SHARE = 0.6        # a model by look: its share of the K nearest reference photos
JUNK_MARGIN = 0.02      # junk: the 5 nearest junk photos at least this close as the 5 nearest cameras
NOT_CAMERA = 0.1        # 'is it a camera at all' below this, for titles without a camera word or brand
OCR_SCORE = 0.6
PAUSE = (2.0, 3.0)      # between photo downloads, as for every request to Vinted
PHOTO_URL = re.compile(r"^https://images\d*\.vinted\.net/[^\"'\s]+$")

CAMERA_TEXTS = ["a photo of a camera", "a photo of a vintage film camera",
                "a photo of an old photo camera with a lens", "a photo of several old cameras"]
OTHER_TEXTS = ["a photo of a household item", "a photo of a kitchen tool", "a photo of a knife sharpener",
               "a photo of an electronic gadget", "a photo of a drone or a gimbal", "a photo of an action camera",
               "a photo of a bag or a case", "a photo of clothes", "a photo of a toy", "a photo of a cardboard box",
               "a photo of jewelry", "a photo of a book or a magazine", "a photo of a lamp",
               "a photo of a video camera", "a photo of a camera lens", "a photo of a camera flash",
               "a photo of a smartphone"]


def available(root):
    """The libraries are installed and the gallery is in the data repo."""
    if not (root / GALLERY_FILE).exists():
        return False
    try:
        import open_clip  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


class Labeler:
    def __init__(self, root):
        import open_clip
        import torch
        from rapidocr_onnxruntime import RapidOCR

        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(ARCH, pretrained=WEIGHTS)
        self.model.eval()
        with torch.no_grad():
            texts = self.model.encode_text(open_clip.get_tokenizer(ARCH)(CAMERA_TEXTS + OTHER_TEXTS))
        self.texts = texts / texts.norm(dim=-1, keepdim=True)
        gallery = torch.load(root / GALLERY_FILE, weights_only=True)
        self.matrix = gallery["vectors"].float()
        self.labels = list(gallery["labels"])
        self.camera = torch.tensor([not label.startswith("junk:") for label in self.labels])
        self.junk_index = [i for i, is_cam in enumerate(self.camera.tolist()) if not is_cam]
        self.ocr = RapidOCR()

    def label(self, item, image_path):
        from PIL import Image

        torch = self.torch
        with torch.no_grad():
            vec = self.model.encode_image(self.preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0))[0]
        vec = vec / vec.norm()
        sims = self.matrix @ vec
        top = sims.topk(min(K, len(self.labels)))
        score = {}
        for s, idx in zip(top.values.tolist(), top.indices.tolist()):
            score[self.labels[idx]] = score.get(self.labels[idx], 0.0) + s
        best = max(score, key=score.get)
        share = score[best] / sum(score.values())
        margin = (sims[self.camera].topk(5).values.mean() - sims[~self.camera].topk(5).values.mean()).item()
        junk_label = self.labels[self.junk_index[int(sims[~self.camera].argmax())]]
        is_camera = (100 * self.texts @ vec).softmax(dim=-1)[:len(CAMERA_TEXTS)].sum().item()

        result, _ = self.ocr(str(image_path))
        read = " ".join(t for _, t, s in (result or []) if float(s) > OCR_SCORE)
        brands = models.brands_in(item.get("vinted_brand") or "")[:1] + models.brands_in(item.get("title") or "")[:1]
        hits = models.find_models(read, brands)
        read_model = hits[0][2] if hits else None

        title = models.normalize(item.get("title") or "")
        no_camera_text = not (models._CAMERA_WORDS.search(title) or brands)
        look_model = best[6:] if best.startswith("model:") and share >= LOOK_SHARE else None
        if no_camera_text and is_camera < NOT_CAMERA:
            verdict = ["drop", "не камера"]
        elif margin < JUNK_MARGIN and not read_model:
            verdict = ["drop", junk_label[5:]]
        elif read_model:
            verdict = ["list", read_model, "надпись"]
        elif look_model:
            verdict = ["list", look_model, "вид"]
        else:
            verdict = ["keep"]
        return {"verdict": verdict, "margin": round(margin, 3), "is_camera": round(is_camera, 2),
                "similar": best, "share": round(share, 2), "ocr": read[:80]}


def candidates(items):
    """'Остальные' with a photo and no photo label yet, newest first."""
    return sorted((i for i in items if i.get("group") == "rest" and i.get("photo") and "photo_label" not in i),
                  key=lambda i: i["id"], reverse=True)


def apply_backfill(root, items, state):
    """Verdicts labelled outside the tracker (the archive) go onto the cards once. Returns the cards changed."""
    import json

    path = root / BACKFILL_FILE
    if not path.exists():
        return []
    stamp = str(path.stat().st_size)
    if state.get("photo_backfill_applied") == stamp:
        return []
    labels = json.loads(path.read_text(encoding="utf-8"))
    changed = []
    for item in items:
        found = labels.get(str(item["id"]))
        if found and "photo_label" not in item:
            item["photo_label"] = dict(found, at=found.get("at") or "архив")
            changed.append(item)
    state["photo_backfill_applied"] = stamp
    return changed


def run(root, items, budget_s, session=None):
    """Label new cards of 'Остальные' by photo within budget_s seconds. Returns (changed cards, stats)."""
    import tempfile
    from pathlib import Path

    import requests

    stats = {"labelled": 0, "drop": 0, "list": 0, "keep": 0, "gone": 0, "errors": 0}
    todo = candidates(items)
    if not todo:
        return [], stats
    started = time.monotonic()
    labeler = Labeler(root)
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", "Mozilla/5.0")
    changed = []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "photo.jpg"
        for item in todo:
            if time.monotonic() - started > budget_s:
                break
            if not PHOTO_URL.match(item["photo"]):
                continue
            time.sleep(random.uniform(*PAUSE))
            try:
                resp = session.get(item["photo"], timeout=30)
            except requests.RequestException:
                stats["errors"] += 1
                continue
            if resp.status_code in (403, 429):
                stats["errors"] += 1
                break  # the image server refuses: try again next tick
            if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
                item["photo_label"] = {"verdict": ["gone"], "at": clock.stamp()}
                stats["gone"] += 1
            else:
                path.write_bytes(resp.content)
                try:
                    item["photo_label"] = dict(labeler.label(item, path), at=clock.stamp())
                except OSError:
                    stats["errors"] += 1
                    continue
                stats[item["photo_label"]["verdict"][0]] += 1
            stats["labelled"] += 1
            changed.append(item)
    return changed, stats


VERDICT_RU = {"drop": "убрать", "list": "в «Список»", "keep": "оставить", "gone": "фото нет"}


def verdict_text(label):
    """'в «Список»: Canon AE-1 (по надписи)', 'убрать: compact', 'оставить'."""
    v = label.get("verdict") or []
    if not v:
        return ""
    text = VERDICT_RU.get(v[0], v[0])
    if v[0] == "drop":
        return f"{text}: {v[1]}"
    if v[0] == "list":
        return f"{text}: {v[1]} (по {'надписи' if v[2] == 'надпись' else 'виду'})"
    return text


def image_formula(url):
    """=IMAGE("…") for a Vinted photo URL, or '' (nothing else ever becomes a formula)."""
    return f'=IMAGE("{url}")' if url and PHOTO_URL.match(url) else ""
