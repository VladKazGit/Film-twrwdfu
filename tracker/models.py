"""Camera model recognition for listing titles and descriptions.

The watch list and the rules come from CLAUDE.md. Text is normalized first
(lowercase, Cyrillic transliterated, accents and dash variants unified), and
model names match with optional separators, so 'AE-1', 'AE 1' and 'ae1' are
the same. When matches overlap, the longer model name wins (AE-1 Program over
AE-1, ME Super over ME); otherwise the earliest match in the text wins.

Alias syntax in MODELS (aliases are lowercase; spaces mark where a separator
may or may not be written):
  "fm2"     the brand must appear somewhere (text or Vinted brand field)
  "^f2"     the brand must be written right before it ("Nikon F2")
  "fm3a!"   distinctive enough to match without the brand
  "=kx"     exact spelling, no separators (KX, not the digital K-x)
  "~regex"  raw regex on normalized text
"""
import re
import unicodedata
from dataclasses import dataclass

JAPAN, EUROPE, EAST = "Japan", "Europe", "Eastern Bloc"
MECH, ELEC = "mechanical", "electronic"
S35, MED = "35mm", "medium"

# brand: (region, aliases). List brands first, then others for brand-only hits.
BRANDS = {
    "Nikon": (JAPAN, ["nikon", "nikkormat"]),
    "Canon": (JAPAN, ["canon"]),
    "Pentax": (JAPAN, ["asahi pentax", "pentax", "asahi"]),
    "Olympus": (JAPAN, ["olympus"]),
    "Minolta": (JAPAN, ["minolta"]),
    "Konica": (JAPAN, ["konica"]),
    "Yashica": (JAPAN, ["yashica", "yashicamat"]),
    "Mamiya": (JAPAN, ["mamiya"]),
    "Contax": (JAPAN, ["contax"]),  # listed models are Kyocera-made (Japan)
    "Leica": (EUROPE, ["leica", "leitz"]),
    "Hasselblad": (EUROPE, ["hasselblad"]),
    "Rollei": (EUROPE, ["rolleiflex", "rolleicord", "rollei"]),
    "Praktica": (EAST, ["praktica", "praktika"]),
    "Zenit": (EAST, ["zenit", "zenith"]),
    "FED": (EAST, ["fed"]),
    "Zorki": (EAST, ["zorkiy", "zorkij", "zorki", "zorky"]),
    "Kiev": (EAST, ["kiev", "kiew", "kyiv"]),
    "Fujica": (JAPAN, ["fujica", "fujifilm", "fuji"]),
    "Ricoh": (JAPAN, ["ricoh"]),
    "Chinon": (JAPAN, ["chinon"]),
    "Cosina": (JAPAN, ["cosina"]),
    "Topcon": (JAPAN, ["topcon"]),
    "Miranda": (JAPAN, ["miranda"]),
    "Petri": (JAPAN, ["petri"]),
    "Bronica": (JAPAN, ["zenza bronica", "bronica"]),
    "Voigtländer": (EUROPE, ["voigtlander", "voigtlaender"]),
    "Zeiss Ikon": (EUROPE, ["zeiss ikon"]),
    "Agfa": (EUROPE, ["agfa"]),
    "Exakta": (EAST, ["exakta", "ihagee", "exa"]),
    "Pentacon": (EAST, ["pentacon"]),
    "Lomo": (EAST, ["lomo"]),
    "Smena": (EAST, ["smena"]),
    "Lubitel": (EAST, ["lubitel"]),
    "Moskva": (EAST, ["moskva"]),
    "Kodak": (None, ["kodak"]),
    "Polaroid": (None, ["polaroid"]),
}

# Lens/aperture-looking tails that must not count as "another model number".
_NOT_OTHER_MODEL = r"(?![\d.,:x]|\s*mm)"

# (brand, model, mech_type, format, aliases, not_after regex or None)
MODELS = [
    # --- mechanical
    ("Nikon", "Nikon F", MECH, S35, ["^f"], None),
    ("Nikon", "Nikon F2", MECH, S35, ["^f2", "^f2 a", "^f2 as", "^f2 s", "^f2 sb"], None),
    ("Nikon", "Nikon FM", MECH, S35, ["fm"], None),
    ("Nikon", "Nikon FM2", MECH, S35, ["fm2!"], None),
    ("Nikon", "Nikon FM2n", MECH, S35, ["fm2 n!"], None),
    ("Nikon", "Nikon FM2n/T", MECH, S35, ["fm2 n t!", "fm2 t!"], None),
    ("Nikon", "Nikon FM3A", MECH, S35, ["fm3 a!"], None),
    ("Nikon", "Nikkormat FTn", MECH, S35, ["nikkormat ftn!", "ftn"], None),
    ("Canon", "Canon F-1", MECH, S35, ["^f 1"], None),
    ("Canon", "Canon F-1n", MECH, S35, ["^f 1 n"], None),
    ("Canon", "Canon FTb", MECH, S35, ["ft b", "ft b n", "ft b ql"], None),
    ("Canon", "Canon FT QL", MECH, S35, ["ft ql", "^ft"], None),
    ("Canon", "Canon Pellix", MECH, S35, ["pellix!"], None),
    ("Canon", "Canon P", MECH, S35, ["^p"], None),
    ("Canon", "Canon 7", MECH, S35, ["^7"], r"d(?![a-z])"),
    ("Canon", "Canon FX", MECH, S35, ["^fx"], None),
    ("Canon", "Canon FP", MECH, S35, ["^fp"], None),
    ("Canon", "Canon TL", MECH, S35, ["^tl", "^tl ql"], None),
    ("Canon", "Canon TLb", MECH, S35, ["tl b", "^tl b"], None),
    ("Canon", "Canon TX", MECH, S35, ["^tx"], None),
    ("Pentax", "Pentax Spotmatic", MECH, S35, ["spotmatic!", "^sp"], r"(?:ii|iia|2|500|1000)(?![a-z0-9])"),
    ("Pentax", "Pentax Spotmatic F", MECH, S35, ["spotmatic f!", "^sp f"], None),
    ("Pentax", "Pentax SV", MECH, S35, ["^sv"], None),
    ("Pentax", "Pentax K1000", MECH, S35, ["k 1000!"], None),
    ("Pentax", "Pentax KM", MECH, S35, ["^=km"], None),
    ("Pentax", "Pentax MX", MECH, S35, ["mx"], None),
    ("Pentax", "Pentax KX", MECH, S35, ["^=kx"], None),
    ("Olympus", "Olympus OM-1", MECH, S35, ["om 1!"], None),
    ("Olympus", "Olympus OM-1n", MECH, S35, ["om 1 n!"], None),
    ("Olympus", "Olympus OM-3", MECH, S35, ["om 3!"], None),
    ("Olympus", "Olympus OM-3Ti", MECH, S35, ["om 3 ti!", "om 3 titan!"], None),
    ("Minolta", "Minolta SR-T 101", MECH, S35, ["sr t 101!", "sr t 101 b!"], None),
    ("Minolta", "Minolta SR-T 102", MECH, S35, ["sr t 102!"], None),
    ("Minolta", "Minolta SR-T 201", MECH, S35, ["sr t 201!"], None),
    ("Minolta", "Minolta SR-7", MECH, S35, ["sr 7"], None),
    ("Konica", "Konica Auto-Reflex", MECH, S35, ["auto reflex"], r"(?:t|tc|t2|t3|t4|a|a1|a3|p)(?![a-z0-9])"),
    ("Konica", "Konica Autoreflex T", MECH, S35, ["auto reflex t!"], None),
    ("Konica", "Konica Autoreflex T2", MECH, S35, ["auto reflex t 2!"], None),
    ("Konica", "Konica Autoreflex T3", MECH, S35, ["auto reflex t 3!", "auto reflex t 3 n!"], None),
    ("Konica", "Konica Autoreflex T4", MECH, S35, ["auto reflex t 4!"], None),
    ("Yashica", "Yashica FX-3", MECH, S35, ["fx 3"], r"super"),
    ("Yashica", "Yashica FX-3 Super 2000", MECH, S35, ["fx 3 super 2000!"], None),
    ("Mamiya", "Mamiya C330", MECH, MED, ["c 330!", "c 330 professional!"], None),
    ("Mamiya", "Mamiya C330f", MECH, MED, ["c 330 f!", "c 330 professional f!", "c 330 pro f!"], None),
    ("Mamiya", "Mamiya C330s", MECH, MED, ["c 330 s!", "c 330 professional s!", "c 330 pro s!"], None),
    ("Mamiya", "Mamiya RB67", MECH, MED, ["rb 67!"], None),
    ("Yashica", "Yashica Mat-124", MECH, MED, ["mat 124!", "yashicamat 124!"], None),
    ("Yashica", "Yashica Mat-124G", MECH, MED, ["mat 124 g!", "yashicamat 124 g!", "124 g"], None),
    ("Rollei", "Rolleiflex 2.8F", MECH, MED, ["^2 8 f"], None),
    ("Leica", "Leica M2", MECH, S35, ["m2"], None),
    ("Leica", "Leica M3", MECH, S35, ["m3"], None),
    ("Leica", "Leica M4", MECH, S35, ["m4"], None),
    ("Leica", "Leica M4-2", MECH, S35, [r"~m4\s*-\s*2"], None),
    ("Leica", "Leica M4-P", MECH, S35, ["m4 p"], None),
    ("Leica", "Leica M5", MECH, S35, ["m5"], None),
    ("Leica", "Leica M6", MECH, S35, ["m6"], None),
    ("Leica", "Leicaflex", MECH, S35, ["leicaflex!"], None),
    ("Leica", "Leicaflex SL", MECH, S35, ["leicaflex sl!"], None),
    ("Leica", "Leicaflex SL2", MECH, S35, ["leicaflex sl 2!"], None),
    ("Leica", "Leica R6", MECH, S35, ["r6"], None),
    ("Leica", "Leica R6.2", MECH, S35, ["r6 2"], None),
    ("Hasselblad", "Hasselblad 500C", MECH, MED, ["500 c"], None),
    ("Hasselblad", "Hasselblad 500C/M", MECH, MED, ["500 c m!"], None),
    ("Hasselblad", "Hasselblad 501C", MECH, MED, ["501 c!"], None),
    ("Hasselblad", "Hasselblad 503CX", MECH, MED, ["503 cx!"], None),
    ("Rollei", "Rolleiflex SL35", MECH, S35, ["sl 35"], r"(?:e|me)(?![a-z0-9])"),
    ("Rollei", "Rolleiflex SL350", MECH, S35, ["sl 350"], None),
    ("Rollei", "Rolleiflex SL35M", MECH, S35, ["sl 35 m"], None),
    ("Praktica", "Praktica L", MECH, S35, ["^l"], None),
    ("Praktica", "Praktica LTL", MECH, S35, ["ltl"], None),
    ("Praktica", "Praktica Super TL", MECH, S35, ["super tl"], None),
    ("Praktica", "Praktica MTL 3", MECH, S35, ["mtl 3!"], None),
    ("Praktica", "Praktica MTL 5", MECH, S35, ["mtl 5!"], None),
    ("Praktica", "Praktica MTL 5B", MECH, S35, ["mtl 5 b!"], None),
    ("Zenit", "Zenit 3M", MECH, S35, ["^3 m"], None),
    ("Zenit", "Zenit E", MECH, S35, ["^e"], None),
    ("Zenit", "Zenit B", MECH, S35, ["^b", "^v"], None),
    ("Zenit", "Zenit EM", MECH, S35, ["^em"], None),
    ("Zenit", "Zenit ET", MECH, S35, ["^et"], None),
    ("Zenit", "Zenit TTL", MECH, S35, ["^ttl"], None),
    ("Zenit", "Zenit 10", MECH, S35, ["^10"], None),
    ("Zenit", "Zenit 11", MECH, S35, ["^11"], None),
    ("Zenit", "Zenit 12SD", MECH, S35, ["^12 sd", "^12 cd"], None),
    ("Zenit", "Zenit 12XP", MECH, S35, ["^12 xp"], None),
    ("Zenit", "Zenit 122", MECH, S35, ["^122"], r"k(?![a-z0-9])"),
    ("Zenit", "Zenit 4", MECH, S35, ["^4"], None),
    ("Zenit", "Zenit 5", MECH, S35, ["^5"], None),
    ("Zenit", "Zenit 6", MECH, S35, ["^6"], None),
    ("FED", "FED 2", MECH, S35, ["^2"], None),
    ("FED", "FED 3", MECH, S35, ["^3"], None),
    ("FED", "FED 4", MECH, S35, ["^4"], None),
    ("FED", "FED 5", MECH, S35, ["^5"], None),
    ("FED", "FED 5B", MECH, S35, ["^5 b", "^5 v"], None),
    ("FED", "FED 5C", MECH, S35, ["^5 c", "^5 s"], None),
    ("Zorki", "Zorki 4", MECH, S35, ["^4"], None),
    ("Zorki", "Zorki 4K", MECH, S35, ["^4 k"], None),
    ("Kiev", "Kiev 4", MECH, S35, ["^4"], None),
    ("Kiev", "Kiev 4A", MECH, S35, ["^4 a"], None),
    ("Kiev", "Kiev 4M", MECH, S35, ["^4 m"], None),
    ("Kiev", "Kiev 4AM", MECH, S35, ["^4 am"], None),
    ("Kiev", "Kiev 88", MECH, MED, ["^88"], r"(?:cm|sm)(?![a-z0-9])"),
    ("Kiev", "Kiev 60", MECH, MED, ["^60"], None),
    ("Kiev", "Kiev 6C", MECH, MED, ["^6 c", "^6 s"], None),
    # --- semi-automatic, hybrid, electronic
    ("Canon", "Canon AE-1", ELEC, S35, ["ae 1!"], None),
    ("Canon", "Canon AE-1 Program", ELEC, S35, ["ae 1 program!", "ae 1 prog!", "ae 1 p!"], None),
    ("Canon", "Canon A-1", ELEC, S35, ["^a 1"], None),
    ("Canon", "Canon AV-1", ELEC, S35, ["av 1"], None),
    ("Canon", "Canon AL-1", ELEC, S35, ["al 1"], None),
    ("Canon", "Canon T90", ELEC, S35, ["t 90"], None),
    ("Canon", "Canon EF", ELEC, S35, ["^ef"],
     r"\d|s(?![a-z])|m(?![a-z])|objektiv|obiettiv|objectif|lens|zoom|usm|optik"),
    ("Canon", "Canon New F-1", ELEC, S35, ["new f 1"], None),
    ("Nikon", "Nikon F3", ELEC, S35, ["^f3", "^f3 hp", "^f3 t", "^f3 p"], None),
    ("Nikon", "Nikon F4", ELEC, S35, ["^f4", "^f4 s", "^f4 e"], None),
    ("Nikon", "Nikon FE", ELEC, S35, ["fe"], None),
    ("Nikon", "Nikon FE2", ELEC, S35, ["fe 2"], None),
    ("Nikon", "Nikon FA", ELEC, S35, ["^fa"], None),
    ("Nikon", "Nikon FG", ELEC, S35, ["fg"], None),
    ("Nikon", "Nikon EM", ELEC, S35, ["^em"], None),
    ("Nikon", "Nikon EL2", ELEC, S35, ["el 2"], None),
    ("Pentax", "Pentax LX", ELEC, S35, ["lx"], None),
    ("Pentax", "Pentax K2", ELEC, S35, ["^k 2", "^k 2 dmd"], None),
    ("Pentax", "Pentax ME", ELEC, S35, ["^me"], r"f(?![a-z0-9])"),
    ("Pentax", "Pentax ME Super", ELEC, S35, ["me super", "^me super"], None),
    ("Pentax", "Pentax MV", ELEC, S35, ["^mv"], None),
    ("Pentax", "Pentax Super A", ELEC, S35, ["^super a", "super program"], None),
    ("Pentax", "Pentax 67", ELEC, MED, ["^67", "^6 x 7"], None),
    ("Pentax", "Pentax 67II", ELEC, MED, ["^67 ii"], None),
    ("Olympus", "Olympus OM-2", ELEC, S35, ["om 2!"], None),
    ("Olympus", "Olympus OM-2n", ELEC, S35, ["om 2 n!"], None),
    ("Olympus", "Olympus OM-2S", ELEC, S35, ["om 2 s!", "om 2 sp!", "om 2 spot!", "om 2 spot program!"], None),
    ("Olympus", "Olympus OM-4", ELEC, S35, ["om 4!"], None),
    ("Olympus", "Olympus OM-4Ti", ELEC, S35, ["om 4 ti!", "om 4 t!", "om 4 titan!"], None),
    ("Olympus", "Olympus OM-10", ELEC, S35, ["om 10!"], None),
    ("Olympus", "Olympus OM-40", ELEC, S35, ["om 40!", "om 40 program!"], None),
    ("Minolta", "Minolta X-1", ELEC, S35, ["^x 1", "^xk", "^xm"], None),
    ("Minolta", "Minolta X-700", ELEC, S35, ["x 700!"], None),
    ("Minolta", "Minolta X-500", ELEC, S35, ["x 500", "x 570"], None),
    ("Minolta", "Minolta XG-M", ELEC, S35, ["xg m"], None),
    ("Minolta", "Minolta XD-7", ELEC, S35, ["xd 7!", "xd 11!", "^xd"], None),
    # 'cle' right after the brand only: 'Porte clé minolta' is a keychain ('clé' -> 'cle').
    ("Minolta", "Minolta CLE", ELEC, S35, ["^cle"], None),
    ("Konica", "Konica FS-1", ELEC, S35, ["fs 1"], None),
    ("Konica", "Konica FC-1", ELEC, S35, ["fc 1"], None),
    ("Konica", "Konica Autoreflex TC", ELEC, S35, ["auto reflex tc!"], None),
    ("Contax", "Contax RTS", ELEC, S35, ["rts"], None),
    ("Contax", "Contax RTS II", ELEC, S35, ["rts ii", "rts 2"], None),
    ("Contax", "Contax RTS III", ELEC, S35, ["rts iii", "rts 3"], None),
    ("Contax", "Contax 137 MD", ELEC, S35, ["137 md", "^137"], None),
    ("Contax", "Contax 139 Quartz", ELEC, S35, ["139 quartz", "^139"], None),
    ("Contax", "Contax 159 MT", ELEC, S35, ["159 mt", "^159"], None),
    ("Mamiya", "Mamiya RZ67", ELEC, MED, ["rz 67!"], None),
    ("Mamiya", "Mamiya 645", ELEC, MED, ["m 645!", "645 pro!", "^645"],
     r"(?:1000 ?s?|super|j|af|afd|df|e|tl)(?![a-z0-9])"),
    ("Leica", "Leica R3", ELEC, S35, ["r3"], None),
    ("Leica", "Leica R4", ELEC, S35, ["r4"], None),
    ("Leica", "Leica R5", ELEC, S35, ["r5"], None),
    ("Leica", "Leica R7", ELEC, S35, ["r7"], None),
    ("Leica", "Leica R8", ELEC, S35, ["r8"], None),
    ("Leica", "Leica M7", ELEC, S35, ["m7"], None),
    ("Hasselblad", "Hasselblad 2000FC", ELEC, MED, ["2000 fc!"], None),
    ("Hasselblad", "Hasselblad 2000FC/M", ELEC, MED, ["2000 fc m!"], None),
    ("Hasselblad", "Hasselblad 2000FCW", ELEC, MED, ["2000 fcw!", "2000 fc w!"], None),
    ("Hasselblad", "Hasselblad 2003FCW", ELEC, MED, ["2003 fcw!", "2003 fc w!"], None),
    ("Hasselblad", "Hasselblad 201F", ELEC, MED, ["201 f"], None),
    ("Praktica", "Praktica B200", ELEC, S35, ["b 200"], None),
    ("Praktica", "Praktica BMS", ELEC, S35, ["bms"], None),
    ("Praktica", "Praktica BCA", ELEC, S35, ["bca"], None),
    ("Praktica", "Praktica BC1", ELEC, S35, ["bc 1"], None),
    ("Kiev", "Kiev 10", ELEC, S35, ["^10"], None),
    ("Kiev", "Kiev 15 Tee", ELEC, S35, ["^15", "^15 tee"], None),
    ("Zenit", "Zenit 16", ELEC, S35, ["^16"], None),
    ("Zenit", "Zenit 19", ELEC, S35, ["^19"], None),
    ("Zenit", "Zenit Automat", ELEC, S35, ["^avtomat", "^automat"], None),
    ("Zenit", "Zenit AM", ELEC, S35, ["^am"], None),
    ("Zenit", "Zenit APK", ELEC, S35, ["^apk"], None),
    ("Zenit", "Zenit KM", ELEC, S35, ["^km"], None),
]

# Bump when MODELS changes: active items are re-classified on the next tick.
VERSION = 18

# Models added later: the model search looks for their old listings first (once).
PRIORITY_SEARCH = ("Canon FX", "Canon FP", "Canon TL", "Canon TLb", "Canon TX")

# Models that must not match when the text also contains this pattern.
MODEL_EXCLUDE = {
    "Canon EF": re.compile(r"\beos\b"),  # 'Canon EF' there is the EOS lens mount, not the 1973 camera
}
# A title naming one of these series is a known non-list camera: do not look
# for a list model in its description ('Canon EOS 5000 ... Canon EF Objektiv').
NON_LIST_SERIES = re.compile(
    r"\beos\b|dynax|maxxum|\briva\b|espio|\bprima\b|sure ?shot|autoboy|\bmju\b|superzoom|zoomate|nikonos")

# ---------------------------------------------------------------- normalization

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "і": "i", "ї": "i", "є": "e", "ґ": "g",
    # Latin letters that accent stripping leaves alone ('Œilleton de visée').
    "œ": "oe", "æ": "ae", "ø": "o", "ł": "l", "đ": "d", "ı": "i",
}
_TRANSLIT = str.maketrans(_CYRILLIC)
_DASHES = re.compile(r"[‐-―−]")


def normalize(text):
    """Lowercase, transliterate Cyrillic, strip accents, unify dashes and spaces."""
    text = (text or "").lower().translate(_TRANSLIT).replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _DASHES.sub("-", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- matching

SEP = r"[\s\-.,_/]*"
_START = r"(?<![a-z0-9])"
# End of a model name: no letter/digit, and not an aperture/focal length
# like 'f1.4', 'm 2/50' right after it.
_END = r"(?![a-z0-9]|[.,/:]\d)"


def _flex(alias):
    return SEP.join(re.escape(t) for t in re.findall(r"[a-z]+|\d+", alias))


def _brand_pattern(aliases):
    return "(?:" + "|".join(_flex(a) for a in sorted(aliases, key=len, reverse=True)) + ")"


_BRAND_RX = {brand: re.compile(_START + _brand_pattern(aliases) + _END)
             for brand, (_, aliases) in BRANDS.items()}


@dataclass(frozen=True)
class _Alias:
    model: str
    brand: str
    needs_brand: bool
    core_len: int
    rx: re.Pattern


def _compile_alias(brand, model, alias, not_after):
    adjacent = alias.startswith("^")
    alias = alias.lstrip("^")
    standalone = alias.endswith("!")
    alias = alias.rstrip("!")
    if alias.startswith("~"):
        core = alias[1:]
    elif alias.startswith("="):
        core = re.escape(alias[1:])
    else:
        core = _flex(alias)
    tail = _END
    if not_after:
        tail += f"(?!{SEP}(?:{not_after}))"
    if re.search(r"[a-z]$", alias):
        # 'FG-20', 'F 301', 'FM 10' are other models; '50mm', 'f 1.4' are lenses.
        # 'x' is allowed only after one digit ('2x Objektive'), not after a model number ('F-401x').
        tail += r"(?!\s*-?\s*(?:\d{2,}(?![\d.,:]|\s*mm)|\d" + _NOT_OTHER_MODEL + "))"
    # Mount names: 'Nikon F mount', 'Canon EF Bajonett' are lenses/adapters.
    tail += rf"(?!{SEP}(?:mount|bajonett|bayonet|anschluss|adapter|adaptateur|monture|attacco|innesto|vatting))"
    head = _START + (_brand_pattern(BRANDS[brand][1]) + SEP if adjacent else "")
    return _Alias(model, brand, not (adjacent or standalone), len(re.sub(r"[^a-z0-9]", "", alias)),
                  re.compile(head + core + tail))


_ALIASES = [_compile_alias(b, m, a, na) for b, m, _, _, aliases, na in MODELS for a in aliases]
MODEL_INFO = {m: {"brand": b, "mech_type": mech, "format": fmt, "region": BRANDS[b][0]}
              for b, m, mech, fmt, _, _ in MODELS}


def brands_in(text):
    """Canonical brands mentioned in text, in order of first appearance."""
    norm = normalize(text)
    hits = []
    for brand, rx in _BRAND_RX.items():
        m = rx.search(norm)
        if m:
            hits.append((m.start(), brand))
    return [b for _, b in sorted(hits)]


def find_models(text, extra_brands=()):
    """List models in text as [(start, end, model)], ordered by position.

    Overlapping matches resolve to the longer model name.
    """
    norm = normalize(text)
    present = set(brands_in(norm)) | set(extra_brands)
    excluded = {model for model, rx in MODEL_EXCLUDE.items() if rx.search(norm)}
    found = []
    for alias in _ALIASES:
        if (alias.needs_brand and alias.brand not in present) or alias.model in excluded:
            continue
        found += [(m.start(), m.end(), alias.core_len, alias.model) for m in alias.rx.finditer(norm)]
    kept = []
    for hit in sorted(found, key=lambda h: (-h[2], h[0])):
        if all(hit[1] <= k[0] or hit[0] >= k[1] for k in kept):
            kept.append(hit)
    return [(s, e, model) for s, e, _, model in sorted(kept)]


# ---------------------------------------------------------------- flags and kit

_CAMERA_WORDS = re.compile(
    r"kamera\b|kameras\b|\bcamera|\bcamara|appareil|fotocamer[ae]|macchin[ae]|fotoapparat|fototoestel"
    r"|\btoestel|spiegelreflex|\bslr\b|\breflex\b|\bbody\b|gehause|boitier|\bcorpo\b|messsucher"
    r"|rangefinder|telemetr|sucherkamera|compatta|\bcompact|kompakt|point (?:and|&) shoot")
_ACCESSORY_WORDS = re.compile(
    r"tasche|\bbag\b|\bcase\b|\betui|\bsac\b|\bborsa|hulle|gurt\b|\bstrap|sangle|tracolla"
    r"|objektiv|\blens(?:es)?\b|obiettiv|objectif|\blente\b|blitz|\bflash|speedlite"
    r"|winder|motor ?drive|anleitung|(?<!fully )(?<!full )\bmanual\b(?!\s*(?:focus|fokus|camera|kamera|slr|exposure|mode))"
    r"|handbuch|mode d.emploi|istruzioni|handleiding"
    r"|zubehor|accessoire|accessori|toebehoren|\bfilter|deckel|\bprism|mattscheibe|focusing screen"
    r"|\badapter|batterie|\bbattery|\bgriff\b|\bgrip\b|stativ|tripod|treppiede|belichtungsmesser"
    r"|light ?meter|posemetre|esposimetro|ruckteil|\bfilm ?back|magazin\b|gegenlichtblende"
    r"|lens hood|ausloser|\bfilm(?:e|s)?\b(?!\s*(?:kamera|camera))|pellicol|pellicule|\bfilmrolle"
    r"|\bback\b|data ?back|(?<!range)finder|(?<!mess)sucher\b|\bviseur|\bmirino|waist ?level|lichtschacht"
    r"|zubehor\b|acc?es+oires?\b|accessori[oe]?\b|accessor(?:y|ies)\b|toebehoren\b"
    r"|katalog|catalog|cataloghi|catalogue|depliant|prospekt|brochure|broschure|\bguide\b|\bguida\b|ratgeber|leitfaden|\bbuch\b|\bbook\b|\blibro\b|\blivre\b|\bposter\b|zeitschrift|rivista|\bflyer")
# Lens makers and zoom: 'Zoom Vivitar 70/210 per Nikon F' is a lens.
_LENS_WORDS = re.compile(r"\bzoom\b|vivitar|tamron|\bsigma\b|tokina|soligor|hanimex")
# A title without a model or camera words that names a lens maker or a zoom range may be a lens
# ('Vivitar Series 1 70-210mm Makro-Zoom') or a compact ('Canon Prima Zoom 76'): no list model
# from its description.
_LENS_TITLE = re.compile(_LENS_WORDS.pattern + r"|\b\d{2,3}\s?-\s?\d{2,3}\s?mm\b")
# 'passt direkt auf Canon AE-1, A-1, FTb' in a description: compatible cameras, not the item.
_COMPATIBLE_BEFORE = re.compile(
    r"\b(?:passt|passend|fits?|compatible|kompatibel|compatibile|adatt[oa]|geeignet)\b[^.!?\n()]*$")
# Manuals. 'manual' next to camera words means a manual camera ('fully manual SLR').
_MANUAL = re.compile(
    r"(?:bedienungs|betriebs)?anleitung|gebrauchsanweisung|handbuch|\bnotice\b|mode d.emploi|istruzioni|\blibretto"
    r"|handleiding|gebruiksaanwijzing|instruction manual|manuale d.uso|(?<!fotocamere )(?<!macchine )\bmanuali\b"
    # 'manuale' alone also means a manual camera: only as a document ('manuale originale in russo')
    r"|^manuale\b|\bmanuale\b(?=\s+(?:originale|di istruzioni|istruzioni|utente|tecnico|in\s|italiano|inglese"
    r"|tedesco|russo|francese))"
    r"|(?<!fully )(?<!full )\bmanual\b(?!\s*(?:focus|fokus|camera|kamera|slr|exposure|mode))")
# Spare parts. Preceded by "for/per/für..." it is a camera sold for parts instead.
_PARTS = re.compile(
    r"ricambi[oa]?\b|ersatzteil|spare parts?\b|pieces? detachees?|onderde(?:el|len)\b|calotta|top cover"
    r"|bottom plate|bodenplatte|shutter curtain|verschlussvorhang"
    # it: front plate, frame counter, winding, lever, dial, knob, cover, bottom plate
    r"|mascherina|contapose|avvolgimento|\bleva\b|\bghiera|manopola|coperchio|fondello"
    # de: front plate, top cover, advance lever, frame counter, leatherette
    r"|frontplatte|deckkappe|aufzugshebel|zahlwerk|belederung"
    # en / fr / nl
    r"|front plate|advance lever|rewind crank|frame counter|leatherette|light seals?\b"
    r"|\bcapot\b|levier d.armement|\bcompteur\b|\bgainage|\bmousses?\b|bovenkap|onderplaat"
    # badge, battery cap / compartment, eyecup and cap
    r"|etichetta|\btappo\b|\bvano\b|oeilleton|\bcache\b|eyecup|augenmuschel|oculaire"
    # body / lens / rear caps
    r"|body ?caps?\b|gehausedeckel|ruckdeckel|lens caps?\b|objektivdeckel"
    # focusing screen; keychains
    r"|depoli|matglas|porte ?-?cles?\b|keychain|key ?ring|schlusselanhanger|portachiavi|sleutelhanger")
_FOR_BEFORE = re.compile(r"\b(?:per|for|pour|fur|als|voor|para)\s+(?:\w+\s+)?$")
# Words that say the listing is a camera body or kit, not just its manual.
_KIT_WORDS = re.compile(r"\bbody\b|gehause|boitier|\bcorpo\b|objektiv|\blens|obiettiv|objectif|\bkit\b|\bset\b|\bnur\b")
# A description that starts with one of these (and names no camera) is about an accessory.
_LEAD_FILLER = re.compile(
    r"^(?:\W|(?:vendo|verkaufe|verkauf|je vends|vends|selling|sell|for sale|zu verkaufen|original[e]?|neu|new|nuov[oa]"
    r"|top|sehr|gut|guter|ottim[oa]|bon|bonne|tres|very|good|perfekt|perfetto|parfait)\b)+")
_LEAD_ACCESSORY = re.compile(
    r"(?:brochure|broschure|prospekt|depliant|catalog|katalog|cataloghi|catalogue|manual|manuale|manuel|notice"
    r"|libretto|(?:bedienungs)?anleitung|istruzioni|handbuch|objektiv|obiettivo|objectif|lens|zoom|tasche|borsa"
    r"|etui|blitz|flash|winder|sucher|viseur|mirino)")
# Words that make a listing an accessory unless a "with" word comes before them.
# Printed matter (catalogues, brochures, books) counts too.
_STRONG_ACCESSORY = re.compile(
    r"zubehor\b|acc?es+oires?\b|accessori[oe]?\b|accessor(?:y|ies)\b|toebehoren\b"
    r"|katalog|catalog|cataloghi|catalogue|depliant|prospekt|brochure|broschure|\bguide\b|\bguida\b|ratgeber|leitfaden|\bbuch\b|\bbook\b|\blibro\b|\blivre\b|\bposter\b|zeitschrift|rivista|\bflyer"
    r"|camera (?:strap|bag|case|accessor)|kamera(?:tasche|gurt)")
_LEADING_FILLER = re.compile(
    r"^(?:\W|(?:vintage|rare|ancien(?:ne)?|alt(?:e|er)?|old|lot|lotto|set|kit|neu|new|nuovo)\b)+")
_MODEL_NUMBER = re.compile(r"[a-z]*\d+[a-z0-9]*")
_WITH_WORDS = re.compile(r"\b(?:mit|with|avec|con|met|inkl|incl|inklusive|including|plus|und|and|et|e)\b|[+&]")
_FOR_WORDS = re.compile(r"\b(?:fur|for|pour|per|voor|passend|passt|compatible|kompatibel|compatibile)\b")
# Point-and-shoot signs. No camera of the list has a built-in flash or is a compact, so a
# 'Pentax K2 Macro' with 'flash intégré' and a '35-70 tele-macro' zoom is a compact.
_COMPACT = re.compile(
    r"flash (?:integre|incorpore|integrato|incorporato|intégré)|(?:integrated|built[- ]?in) flash"
    r"|(?:eingebaute[rnm]?|integrierte[rnm]?) blitz|ingebouwde flitser|point ?(?:and|&|n) ?shoot"
    # the camera type only: 'kompakt' alone also praises small SLRs ('OM-1 kompakt und leicht')
    r"|kompaktkamera|compact camera|appareil (?:photo )?(?:argentique )?compact|fotocamera compatta")
_DIGITAL = re.compile(
    r"digital|numerique|megapixel|\bmpx?\b|\d\s?mp\b|\bdslr|\bdslm|mirrorless|spiegellos"
    r"|coolpix|powershot|lumix|cyber ?shot|dimage|finepix|\bsd ?-?karte|\bsd ?card|\d+ ?gb\b|\bz ?fc\b"
    r"|\beos \d{2,4}d\b|\beos \d{1,2}d\b|\bd\d{3,4}\b|\bk-(?:x|m|r|\d{1,2})\b|\*ist"
    # Minox digital miniatures of classic cameras ('Leica M3 Minox Miniaturizzata')
    r"|\bminox\b|miniatur")

_LENS = re.compile(
    r"objektiv|obiettiv|objectif|\blens(?:es)?\b|\blente\b|lentille|zoom|\bf\s?/\s?\d|\bf\d[.,]\d"
    r"|\b1\s?:\s?\d|\d[.,]\d\s?/\s?\d{2,3}|(?<!\d)(?!35\s?mm)\d{2,3}\s?mm|\d[.,]\d\s?-\s?\d[.,]\d"
    r"|\blinsen?\b|ottic[ah]e?|optique|\boptik\b|weitwinkel|grandangol|grand angle|tele ?objektiv|teleobiettiv"
    r"|\bmacro\b|tamron|sigma|tokina|vivitar series"
    r"|nikkor|takumar|rokkor|zuiko|summicron|summilux|summitar|elmar|planar|sonnar|tessar|helios"
    r"|industar|jupiter|pancolar|hexanon|yashinon|sekor|biotar|flektogon|ultron|serenar|xenar|skopar")
_NO_LENS = re.compile(
    r"ohne objektiv|kein objektiv|objektiv nicht|without lens|no lens|lens not included|body only"
    r"|sans objectif|objectif non|senza obiettivo|obiettivo non|zonder lens|nur (?:das )?gehause"
    r"|solo corpo|boitier nu|body ohne")
_BODY = re.compile(r"\bbody\b|gehause|boitier|\bcorpo\b|\bbehuizing")
_EXTRAS = {
    "flash": r"blitz|\bflash|speedlite",
    "bag": r"tasche|\bbag\b|\bcase\b|\betui|\bsac\b|\bborsa|hulle",
    "strap": r"gurt\b|\bstrap|sangle|tracolla|trageriemen",
    "film": r"(?:mit|inkl\.?|inklusive|with|incl\.?|including|avec|con|met|\+)\s+(?:\S+\s+)?(?:film|pellicola|pellicule)",
    "manual": r"anleitung|\bmanual|handbuch|mode d.emploi|istruzioni|handleiding",
    "winder": r"winder|motor ?drive",
    "filter": r"\bfilter|\bfiltre|\bfiltro",
    "box": r"\bovp\b|originalverpackung|originalkarton|\bbox\b|\bscatola|\bboite\b",
    "accessories": r"zubehor|accessoir|accessori|toebehoren",
}
_EXTRAS = {name: re.compile(rx) for name, rx in _EXTRAS.items()}


def kit_of(text):
    """Kit type (body / with_lens / extras / unklar) and the extras found."""
    norm = normalize(text)
    details = [name for name, rx in _EXTRAS.items() if rx.search(norm)]
    no_lens = bool(_NO_LENS.search(norm))
    if not no_lens and _LENS.search(_NO_LENS.sub(" ", norm)):
        return "with_lens", ["lens"] + details
    if details:
        return "extras", details
    if no_lens or _BODY.search(norm):
        return "body", []
    return "unklar", []


def _is_accessory(norm, model_span):
    strong = _STRONG_ACCESSORY.search(norm)
    if strong and not _WITH_WORDS.search(norm[:strong.start()]):
        return True  # "Nikon F3 accessoires", "Film Back - Camera Accessory"
    part = _PARTS.search(norm)
    if part and not _WITH_WORDS.search(norm[:part.start()]) and not _FOR_BEFORE.search(norm[:part.start()]):
        return True  # "Calotta superiore Pentax ME Super ricambio originale"
    manual = _MANUAL.search(norm)
    if manual and not _WITH_WORDS.search(norm[:manual.start()]) and not _KIT_WORDS.search(norm):
        return True  # "Notice appareil photo Nikon FE2", "Mamiya M645 ... multi language manual"
    if model_span is not None:
        head = norm[:model_span[0]]
        if (_LENS_WORDS.search(head) or _FOR_WORDS.search(head)) and not _CAMERA_WORDS.search(head):
            return True  # "Zoom Vivitar 70/210 per Nikon F"
    acc = _ACCESSORY_WORDS.search(norm)
    if not acc:
        return False
    if model_span is None:
        head = norm[:acc.start()]
        if _FOR_WORDS.search(norm[acc.end():]) and not (_CAMERA_WORDS.search(head) or _WITH_WORDS.search(head)):
            return True  # "Flash externe ... pour appareil photo"
        if (len(_LEADING_FILLER.sub("", head).split()) <= 2 and not _WITH_WORDS.search(head)
                and not _CAMERA_WORDS.search(norm)):
            return True  # "Flash Agfa", "Fototasche", "Viseur de poitrine Mamiya"
        # "Konica Auto S2 con borsa", "Ricoh FF-700 (no flash)" are cameras.
        return not (_CAMERA_WORDS.search(norm) or _WITH_WORDS.search(head) or _MODEL_NUMBER.search(head))
    start, end = model_span
    head = norm[:start]
    if _ACCESSORY_WORDS.search(head) or _FOR_WORDS.search(head):
        return True  # "Winder für Canon AE-1", "Leica data back R4"
    tail = norm[end:]
    acc = _ACCESSORY_WORDS.search(tail)
    # "Nikon F Waist Level Finder ... Case": accessory words, no camera, no "with".
    return bool(acc) and not _WITH_WORDS.search(tail[:acc.start()]) and not _CAMERA_WORDS.search(norm)


def accessory_words(title):
    """Accessory/part/manual words *before* the model in a title (for review): words after it
    describe the kit ('Canon T90 Kamera Objektiv Speedlite'), words before it the object
    ('Winder für Canon AE-1'). Nothing if the title names no model."""
    norm = normalize(title)
    hits = find_models(norm)
    if not hits:
        return []
    head = norm[:hits[0][0]]
    words = []
    for rx in (_PARTS, _MANUAL, _ACCESSORY_WORDS, _LENS_WORDS):
        for m in rx.finditer(head):
            if not _WITH_WORDS.search(head[:m.start()]) and m.group(0).strip() not in words:
                words.append(m.group(0).strip())
    return words


def lead_word(description):
    """The accessory/part/manual word a description starts with, or None."""
    lead = _LEAD_FILLER.sub("", normalize(description or "")[:160])
    m = _PARTS.match(lead) or _MANUAL.match(lead) or _LEAD_ACCESSORY.match(lead)
    return m.group(0).strip() if m else None


def lead_is_accessory(description):
    """The description starts with a part or manual word ('coperchio superiore fotocamera ...':
    the camera is what the part is for), or with an accessory word (brochure, lens...) and names
    no camera."""
    norm = normalize(description)[:160]
    lead = _LEAD_FILLER.sub("", norm)
    first = _PARTS.match(lead) or _MANUAL.match(lead)
    return bool(first) or (bool(_LEAD_ACCESSORY.match(lead)) and not _CAMERA_WORDS.search(norm[:80]))


def flags_of(title, model_span=None):
    """'accessory?' / 'digital?' flags from the title.

    model_span is the (start, end) of the first model match in the
    normalized title, if any.
    """
    norm = normalize(title)
    flags = []
    if _DIGITAL.search(norm):
        flags.append("digital?")
    if _is_accessory(norm, model_span):
        flags.append("accessory?")
    return flags


# ---------------------------------------------------------------- classification

_GENERIC_BRANDS = {"ohne marke", "andere", "other", "autre", "altro", "unbranded", "no brand", "sans marque"}


def classify(title, description=None, vinted_brand=None):
    """Card fields from title, description and Vinted's brand field.

    Order: title -> description -> brand from text -> Vinted brand.
    """
    vinted_known = brands_in(vinted_brand or "")
    extra = vinted_known[:1]
    model, source, span = None, None, None
    hits = find_models(title, extra)
    if hits:
        span, model = hits[0][:2], hits[0][2]
        source = "title"
    title_flags = flags_of(title, span)
    if _COMPACT.search(normalize(f"{title} {description or ''}")):
        title_flags = title_flags + ["compact?"]
    # 'Yashica Mat-124g' at 3 EUR whose description starts 'brochure originale ...'.
    if (description and "accessory?" not in title_flags and not _CAMERA_WORDS.search(normalize(title))
            and lead_is_accessory(description)):
        title_flags = title_flags + ["accessory?"]
    # An accessory/digital title does not get a camera model from its description
    # ('Lotto depliant e cataloghi Leica' -> description mentions an M3).
    norm_title = normalize(title)
    lens_title = _LENS_TITLE.search(norm_title) and not _CAMERA_WORDS.search(norm_title)
    if model is None and description and not NON_LIST_SERIES.search(norm_title) and not lens_title \
            and not {"accessory?", "digital?", "compact?"} & set(title_flags):
        norm_desc = normalize(description)
        hits = [h for h in find_models(description, extra + brands_in(title)[:1])
                if not _COMPATIBLE_BEFORE.search(norm_desc[:h[0]])]
        if hits:
            model, source = hits[0][2], "description"

    if model:
        info = MODEL_INFO[model]
        brand = info["brand"]
    else:
        text_brands = brands_in(title) or brands_in(description or "")
        brand = (text_brands or vinted_known or [None])[0]
        if brand is None and vinted_brand and normalize(vinted_brand) not in _GENERIC_BRANDS:
            brand = vinted_brand.strip()
        source = "brand_only" if brand else None
        info = {"mech_type": None, "format": _format_hint(title, description),
                "region": BRANDS[brand][0] if brand in BRANDS else None}

    kit, kit_details = kit_of(" ".join(filter(None, [title, description])))
    return {
        "brand": brand,
        "model": model,
        "model_source": source,
        "in_list": model is not None,
        "mech_type": info["mech_type"],
        "region": info["region"],
        "format": info["format"],
        "kit": kit,
        "kit_details": kit_details,
        "flags": title_flags,
    }


_MEDIUM_HINT = re.compile(r"mittelformat|medium format|moyen format|medio formato|middenformaat|\b6 ?x ?[4679]\b|\b120(?:er)? film")


def _format_hint(title, description):
    return MED if _MEDIUM_HINT.search(normalize(" ".join(filter(None, [title, description])))) else None


_CANONICAL = {re.sub(r"[^a-z0-9]", "", normalize(m)): m for m in MODEL_INFO}


def canonical_model(text):
    """Watch-list model name for user-typed text ('canon ae1' -> 'Canon AE-1'), or None."""
    exact = _CANONICAL.get(re.sub(r"[^a-z0-9]", "", normalize(text)))
    if exact:
        return exact
    hits = find_models(text)
    return hits[0][2] if hits else None


def list_models():
    """Rows for the 'Модели' sheet: model, brand, mech_type, format, region."""
    return [(m, i["brand"], i["mech_type"], i["format"], i["region"]) for m, i in MODEL_INFO.items()]
