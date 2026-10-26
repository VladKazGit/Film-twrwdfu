"""Lens models from the user's lens sheet ('Лист1') and their recognition in Vinted titles.

A model is a family word plus the focal length and aperture read from the title ('Super-Takumar
1:1.4/50', 'Helios 44-2 58mm f/2', 'Zuiko 1.8/50'); the Helios series is read by its number
('Гелиос-44М-4', 'MC Helios 44M-6'). A camera with the lens is a camera listing, not a lens (the
camera tracker counts it); caps, hoods, adapters, boxes and manuals for a lens are not lenses.
"""
import re
from dataclasses import dataclass

from . import markers, models

LENS_CATEGORY_ID = 3061  # Vinted 'Objektive'


@dataclass(frozen=True)
class Lens:
    name: str
    mount: str
    family: str            # regex on the normalized title
    focal: float = None    # None: the family says it (or 'SMC Takumar': any, named by the title)
    aperture: float = None
    queries: tuple = ()    # Vinted search texts
    not_rx: str = None     # titles of another lens of the family ('M.Zuiko', 'AF Nikkor')

    def __post_init__(self):
        object.__setattr__(self, "_family", re.compile(self.family))
        object.__setattr__(self, "_not", re.compile(self.not_rx) if self.not_rx else None)


M42, M39 = "M42", "M39 (L39)"
LENSES = [
    Lens("Super-Takumar 50mm f/1.4", M42, r"super[\s\-]*takumar", 50, 1.4, ("super takumar 50 1.4",)),
    Lens("SMC Takumar", M42, r"\bsmc[\s\-]*takumar|super[\s\-]*multi[\s\-]*coated[\s\-]*takumar", None, None,
         ("smc takumar", "super multi coated takumar")),
    Lens("Industar-61 L/Z MC 50mm f/2.8", M42, r"industar[\s\-]*61[\s\-]*l\s*/?\s*z", None, None,
         ("industar 61 l/z", "индустар 61")),
    Lens("Industar-61 53mm f/2.8", M39, r"industar[\s\-]*61(?![\s\-]*l)", None, None, ("industar 61",)),
    Lens("Pentacon 29mm f/2.8", M42, r"pentacon(?![\s\-]*(?:six|prakticar))", 29, 2.8, ("pentacon 29mm",)),
    Lens("Pentacon 50mm f/1.8", M42, r"pentacon(?![\s\-]*(?:six|prakticar))", 50, 1.8, ("pentacon 50mm 1.8",)),
    Lens("Pentacon 200mm f/4", M42, r"pentacon(?![\s\-]*(?:six|prakticar))", 200, 4, ("pentacon 200mm",)),
    Lens("Pancolar 50mm f/1.8", M42, r"pancolar", 50, 1.8, ("pancolar 50 1.8",)),
    Lens("Orestor", M42, r"orestor", None, None, ("orestor",)),
    Lens("Vivitar 200mm f/3.5", M42, r"vivitar", 200, 3.5, ("vivitar 200mm 3.5",)),
    Lens("Soligor Tele-Auto 135mm f/2.8", M42, r"soligor", 135, 2.8, ("soligor 135mm 2.8",)),
    Lens("Auto Hanimar 135mm f/3.5", M42, r"hanimar", 135, 3.5, ("hanimar 135",)),
    Lens("Tomioka Auto Yashinon 55mm f/1.2", M42, r"yashinon|tomioka", 55, 1.2, ("yashinon 55 1.2", "tomioka 55mm")),
    Lens("Jupiter-8 50mm f/2", M39, r"(?:j|y|i)u?piter[\s\-]*8(?![\s\-]*m\b|\d)", None, None,
         ("jupiter 8", "юпитер 8")),
    Lens("Canon FD 50mm f/1.4 (SSC / nFD)", "Canon FD", r"\bn?fd\b|new fd", 50, 1.4, ("canon fd 50mm 1.4",)),
    Lens("Canon FL 58mm f/1.2", "Canon FL", r"\bfl\b", 58, 1.2, ("canon fl 58mm 1.2",)),
    Lens("Nikkor 50mm f/1.4 (Pre-AI / AI / AI-S)", "Nikon F", r"nikkor", 50, 1.4, ("nikkor 50mm 1.4",),
         r"\baf\b|af[\s\-]*[sd]\b|\b1[.,]4\s?[dg]\b|\bg\b|\bd\b"),
    Lens("Zuiko 50mm f/1.8", "Olympus OM", r"zuiko", 50, 1.8, ("zuiko 50mm 1.8",), r"\bm\.?\s?zuiko|digital"),
    Lens("Zuiko 24mm f/2", "Olympus OM", r"zuiko", 24, 2, ("zuiko 24mm 2",), r"\bm\.?\s?zuiko|digital"),
    Lens("Zuiko 28mm f/2", "Olympus OM", r"zuiko", 28, 2, ("zuiko 28mm 2",), r"\bm\.?\s?zuiko|digital"),
    Lens("Carl Zeiss Planar 50mm f/1.4 T* (C/Y)", "C/Y", r"planar", 50, 1.4, ("planar 50 1.4",),
         r"\bz[fe]\b|zf\.?2|ze\b|rollei|hft"),
    Lens("Carl Zeiss Planar 50mm f/1.7 T* (C/Y)", "C/Y", r"planar", 50, 1.7, ("planar 50 1.7",),
         r"\bz[fe]\b|zf\.?2|rollei|hft"),
    Lens("Carl Zeiss Distagon 28mm f/2.8 T*", "C/Y", r"distagon", 28, 2.8, ("distagon 28 2.8",), r"\bz[fe]\b|zf\.?2"),
    Lens("Yashica ML 50mm f/1.4", "C/Y", r"\bml\b", 50, 1.4, ("yashica ml 50mm 1.4",)),
    Lens("Yashica ML 28mm f/2.8", "C/Y", r"\bml\b", 28, 2.8, ("yashica ml 28mm",)),
    Lens("Tamron 28mm f/2.5 Adaptall", "Adaptall", r"tamron", 28, 2.5, ("tamron 28mm 2.5",)),
    Lens("Tokina EL 28mm f/2.8", "C/Y", r"tokina", 28, 2.8, ("tokina 28mm 2.8",)),
    Lens("Super Albinar SC Auto 28mm f/2.8", "C/Y", r"albinar", 28, 2.8, ("albinar 28mm",)),
    Lens("Minolta MC Rokkor 58mm f/1.2", "Minolta SR", r"rokkor|minolta", 58, 1.2, ("rokkor 58mm 1.2",)),
    Lens("Minolta W.Rokkor-SI 28mm f/2.5", "Minolta SR", r"rokkor", 28, 2.5, ("rokkor 28mm 2.5",)),
    Lens("Minolta MD 50mm f/1.7", "Minolta SR", r"\bmd\b|minolta|rokkor", 50, 1.7, ("minolta md 50mm 1.7",)),
    Lens("Konica Hexanon AR 40mm f/1.8", "Konica AR", r"hexanon", 40, 1.8, ("hexanon 40mm 1.8",)),
    Lens("Konica Hexanon AR 50mm f/1.7", "Konica AR", r"hexanon", 50, 1.7, ("hexanon 50mm 1.7",)),
    Lens("Konica Hexanon AR 135mm f/3.5", "Konica AR", r"hexanon", 135, 3.5, ("hexanon 135mm 3.5",)),
    Lens("Rollei-HFT Planar 50mm f/1.8", "Rollei QBM", r"planar", 50, 1.8, ("rollei planar 50 1.8",)),
    Lens("Rolleinar 50mm f/2", "Rollei QBM", r"rolleinar", 50, 2, ("rolleinar 50mm",)),
    Lens("Voigtländer Color Ultron 50mm f/1.8", "Rollei QBM", r"ultron", 50, 1.8, ("color ultron 50 1.8",)),
    Lens("SMC Pentax-M 50mm f/1.7", "Pentax K", r"pentax[\s\-]*m\b|\bsmc[\s\-]*m\b", 50, 1.7, ("pentax-m 50mm 1.7",)),
    Lens("Pentax-A 50mm f/1.4", "Pentax K", r"pentax[\s\-]*a\b|\bsmc[\s\-]*a\b", 50, 1.4, ("pentax-a 50mm 1.4",)),
    Lens("Pentacon Prakticar 50mm f/1.8", "Praktica PB", r"prakticar", 50, 1.8, ("prakticar 50mm 1.8",)),
    Lens("Voigtländer Nokton 50mm f/1.5", "Leica M", r"nokton", 50, 1.5, ("nokton 50mm 1.5",)),
    Lens("Voigtländer Nokton 40mm f/1.4", "Leica M", r"nokton", 40, 1.4, ("nokton 40mm 1.4",)),
    Lens("Leica Summicron-R 50mm f/2", "Leica R", r"summicron[\s\-]*r\b|summicron.*\br\b|\bleica r\b.*summicron",
         50, 2, ("summicron-r 50mm",)),
    Lens("Leica Elmarit-R 28mm f/2.8", "Leica R", r"elmarit[\s\-]*r\b|elmarit.*\br\b", 28, 2.8, ("elmarit-r 28mm",)),
    Lens("Volna-3 80mm f/2.8", "Pentacon Six / Kiev 88", r"volna", 80, 2.8, ("volna 3 80mm", "волна 3")),
    Lens("Zodiak-8 30mm f/3.5 Fisheye", "Pentacon Six / Kiev 88", r"zodiak|zodiac", 30, 3.5, ("zodiak 30mm",)),
    Lens("Carl Zeiss Biometar 120mm f/2.8", "Pentacon Six / Kiev 88", r"biometar", 120, 2.8, ("biometar 120",)),
    Lens("Jupiter-8M 50mm f/2", "Contax RF", r"(?:j|y|i)u?piter[\s\-]*8[\s\-]*m\b", None, None, ("jupiter 8m",)),
    Lens("Arsat 50mm f/2 (MC Helios-81N)", "Nikon F", r"arsat", 50, 2, ("arsat 50mm 2",)),
    Lens("Arsat 50mm f/1.4 (Helios-123N)", "Nikon F", r"arsat", 50, 1.4, ("arsat 50mm 1.4",)),
    Lens("Menopta 53mm f/1.8 (Helios-103)", "Contax-Kiev", r"menopta", 53, 1.8, ("menopta",)),
]

# Lenses whose aperture says the focal length in their family, for titles without it
# ('Super takumar 1.4 (8 elementi)' is the 50mm).
FOCAL_FROM_APERTURE = {"Super-Takumar 50mm f/1.4", "Pancolar 50mm f/1.8", "Tomioka Auto Yashinon 55mm f/1.2",
                       "Canon FL 58mm f/1.2", "Minolta MC Rokkor 58mm f/1.2", "Voigtländer Nokton 50mm f/1.5"}

# The Helios series by number (the user's list): (number, letter, variant, multicoated) -> (name, mount)
_KIEV = "Kiev-10 / 15"
HELIOS = {
    ("44", "", "", False): ("Helios-44", "M39 / M42"),
    ("44", "", "2", False): ("Helios-44-2", M42), ("44", "", "3", False): ("Helios-44-3", M42),
    ("44", "", "7", False): ("Helios-44-7", M42),
    ("44", "m", "", False): ("Helios-44M", M42),
    ("44", "m", "4", False): ("Helios-44M-4", M42), ("44", "m", "4", True): ("MC Helios-44M-4", M42),
    ("44", "m", "5", False): ("Helios-44M-5", M42), ("44", "m", "5", True): ("MC Helios-44M-5", M42),
    ("44", "m", "6", False): ("Helios-44M-6", M42), ("44", "m", "6", True): ("MC Helios-44M-6", M42),
    ("44", "m", "7", False): ("Helios-44M-7", M42), ("44", "m", "7", True): ("MC Helios-44M-7", M42),
    ("44", "k", "4", False): ("Helios-44K-4", "Pentax K"), ("44", "k", "4", True): ("Helios-44K-4", "Pentax K"),
    ("40", "", "", False): ("Helios-40", M39), ("40", "", "2", False): ("Helios-40-2", M42),
    ("81", "a", "", False): ("Helios-81 Avtomat", _KIEV),
    ("81", "m", "", False): ("Helios-81M", M42), ("81", "m", "", True): ("Helios-81M", M42),
    ("81", "n", "", False): ("Helios-81N", "Nikon F"), ("81", "n", "", True): ("MC Helios-81N", "Nikon F"),
    ("103", "", "", False): ("Helios-103", "Contax-Kiev"),
    ("33", "", "", False): ("Helios-33", "—"), ("65", "", "", False): ("Helios-65", "Start"),
    ("79", "", "", False): ("Helios-79", "—"), ("89", "", "", False): ("Helios-89", "—"),
    ("123", "n", "", False): ("Helios-123N", "Nikon F"), ("123", "n", "", True): ("Helios-123N", "Nikon F"),
}
HELIOS_QUERIES = ("helios 44", "гелиос 44", "helios 44m", "helios 40", "helios 81", "helios 103", "helios")
_HELIOS = re.compile(r"(?<![a-z])(?:helios|gelios)[\s\-.]*(\d{2,3})(?![\d.,])"
                     r"(?:[\s\-.]*(m|k|n|avtomat|automat|auto)(?![a-z]))?"
                     r"(?:[\s\-.]*(\d)(?![\d]|\s*[/.,:]\s*\d|\s?mm))?")
_MC = re.compile(r"(?<![a-z])(?:mc|ms)(?![a-z])")

# Numbers in a title: focal lengths ('50mm', 'f=50mm', '1.4/50', '1:1.4/50') and apertures ('f/1.4', 'F2',
# '1:1.4', '1.4/50', a bare '1.4').
_FOCAL = re.compile(r"(?<![\d.,])(\d{2,3})(?:[.,]\d)?\s?mm\b|\bf\s?=\s?(\d{2,3})\b"
                    r"|(?<=[/:])\s?(\d{2,3})(?![\d.,]|\s?[.,]\d)")
_APERTURE = re.compile(r"\bf\s?/?\s?(\d{1,2}(?:[.,]\d{1,2})?)(?![\d])|\b1\s?:\s?(\d{1,2}(?:[.,]\d{1,2})?)(?![\d])"
                       r"|(?<![\d.,:])(\d{1,2}(?:[.,]\d{1,2})?)\s?/\s?\d{2,3}\b")
_BARE_APERTURE = re.compile(r"(?<![\d.,:/])(0[.,]95|1[.,]\d{1,2}|2[.,][0-8]|3[.,][35]|4[.,][05]|5[.,]6)(?![\d.,]|\s?mm)")


def _num(text):
    return float(text.replace(",", "."))


def focals(norm):
    return {_num(next(g for g in m.groups() if g)) for m in _FOCAL.finditer(norm)}


def apertures(norm):
    found = {_num(next(g for g in m.groups() if g)) for m in _APERTURE.finditer(norm)}
    return found or {_num(m.group(1)) for m in _BARE_APERTURE.finditer(norm)}


# Things for a lens, not the lens: before the lens name, without a 'with' word between.
_FOR_LENS = re.compile(
    r"adapter|adaptor|adattatore|adaptateur|bague d.adaptation|\bdeckel|\bkappe|\bcaps?\b|bouchon|\btappo"
    r"|gegenlichtblende|streulichtblende|sonnenblende|lens hood|\bhood\b|paraluce|pare[\s\-]?soleil|zonnekap"
    r"|\bfilter|\bfiltre|\bfiltro|\btasche|\bcase\b|\betui|custodia|\bkocher|\bbeutel|\bpouch"
    r"|" + models._marker_words(markers.BOX)[2:-2] + "|" + models._marker_words(markers.MANUAL)[2:-2]
    + "|" + models._marker_words(markers.PRINT)[2:-2])
# 'With' for lenses: not the one-letter 'e' / 'et' of the camera rules ('Adapter M42 Sony E für Helios 44-2').
_WITH = re.compile(r"\b(?:mit|with|avec|con|met|inkl|incl|inklusive|including|plus|com|med|und|and)\b|[+&]")
_PARTS_ONLY = re.compile(r"fur teile|for parts|pour pieces|per ricambi|als ersatzteil|defekt|defect|kaputt|not working")


def _model_span(norm):
    """(start, name, mount) of the first lens of the list in a normalized title, or None."""
    m = _HELIOS.search(norm)
    if m:
        number, letter, variant = m.group(1), (m.group(2) or "")[:1], m.group(3) or ""
        if letter == "a" and number != "81":
            letter = ""
        key = (number, letter, variant, bool(_MC.search(norm)))
        hit = HELIOS.get(key) or HELIOS.get(key[:3] + (False,))
        if hit:
            return m.start(), hit[0], hit[1]
    fs, aps = focals(norm), apertures(norm)
    for lens in LENSES:
        fam = lens._family.search(norm)
        if not fam or (lens._not and lens._not.search(norm)):
            continue
        if lens.focal is not None:
            if fs and lens.focal not in fs or aps and lens.aperture not in aps:
                continue
            if not fs and not (aps and lens.name in FOCAL_FROM_APERTURE):
                continue
        if lens.name == "SMC Takumar":  # every focal length, named by the title
            if not fs:
                continue
            f = min(fs)
            a = min(aps) if aps else None
            return fam.start(), f"SMC Takumar {f:g}mm" + (f" f/{a:g}" if a else ""), lens.mount
        if lens.name == "Orestor":
            if not fs:
                continue
            return fam.start(), f"Orestor {min(fs):g}mm", lens.mount
        return fam.start(), lens.name, lens.mount
    return None


def classify(title):
    """{'model', 'mount', 'kind'}: kind 'lens', 'kit' (a camera with the lens: the camera tracker's),
    'accessory' (a cap, hood, adapter, box or manual for it) or None (no lens of the list); flags
    'parts?' for a lens sold for parts."""
    norm = models.normalize(title)
    hit = _model_span(norm)
    if not hit:
        return {"model": None, "mount": None, "kind": None, "flags": []}
    start, name, mount = hit
    head = norm[:start]
    flags = ["parts?"] if _PARTS_ONLY.search(norm) else []
    acc = _FOR_LENS.search(head)
    if acc and not _WITH.search(head[acc.end():]):
        return {"model": name, "mount": mount, "kind": "accessory", "flags": flags}
    cam = models.classify(title)
    if cam["model"] and not {"accessory?", "digital?", "compact?"} & set(cam["flags"]):
        spans = models.find_models(title)
        camera_first = spans and spans[0][0] < start
        joined = spans and _WITH.search(norm[start:spans[-1][0]])
        if camera_first or joined:
            return {"model": name, "mount": mount, "kind": "kit", "flags": flags}
    return {"model": name, "mount": mount, "kind": "lens", "flags": flags}


def search_queries():
    """Every Vinted search text of the list (Helios series first)."""
    out = list(HELIOS_QUERIES)
    for lens in LENSES:
        out += [q for q in lens.queries if q not in out]
    return out


def model_names():
    """All model names of the list (SMC Takumar and Orestor by family)."""
    return sorted({n for n, _ in HELIOS.values()} | {lens.name for lens in LENSES})
