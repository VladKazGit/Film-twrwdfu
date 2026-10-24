"""What kind of camera an exact name outside the list is: mechanical, semi-automatic / electronic,
autofocus, compact or a movie camera - for 'Предложение' and 'Братья моделей списка', where the
user picks models for the list (which is split mechanical / electronic). By brand and model
series, from the cameras' history; '?' rather than a guess.
"""
import re

MECH, ELEC, AF, COMPACT, MOVIE, UNKNOWN = "механика", "полуавтомат / электроника", "автофокус", "мыльница", "кино", "?"

# (brand, model pattern on the lower-case model with spaces and dashes removed, kind); first match wins
_RULES = [
    # Nikon
    ("Nikon", r"f(?:401|501|601|801|800|60|70|80|90|100|50|55|65|75)\w*|f[56]|f3af|n\d{4}\w*", AF),
    ("Nikon", r"f301|em|el\w*|fg\w*|fe\w*|fa", ELEC),
    ("Nikon", r"fm10|ft\w*|nikkorex\w*|nikonos\w*|s[234]\w*|sp|f2?", MECH),
    ("Nikon", r"lite\w*|l35\w*|af\w*|zoom\w*|one\w*|rf\d*|tw\w*", COMPACT),
    # Minolta
    ("Minolta", r"x(?:300|370|500|570|600|700)\w*|xg\w*|xd\w*|xe\w*|xk|xm|x1|al\w*|hi-?matic\w*|himatic\w*", ELEC),
    ("Minolta", r"srt\w*|sr\d\w*|sr\w*", MECH),
    ("Minolta", r"\d{4}\w*|dynax\w*|maxxum\w*|\d{3}si\w*|\dxi|af\w*|riva\w*|f\d+\w*|weathermatic\w*|wheathermatic\w*", AF),
    # Pentax
    ("Pentax", r"spotmatic\w*|sp\d*\w*|s[123]\w*|sv|k1000|kx|km|mx|lx", MECH),
    ("Pentax", r"es\w*|p30\w*|p50|a3|program\w*|mg|mv\w*|me\w*|superprogram|supera|645\w*", ELEC),
    ("Pentax", r"sf\w*|z\d+\w*|mz\w*|\*ist", AF),
    ("Pentax", r"pc\w*|espio\w*|epsio\w*|pino\w*|zoom\w*|af\w*|iqzoom\w*|mue\w*|17", COMPACT),
    # Canon
    ("Canon", r"7s?|vt\w*|p", MECH),
    ("Canon", r"canonet\w*|demi\w*|ee17", ELEC),
    ("Canon", r"eos\w*", AF),
    ("Canon", r"prima\w*|epoca\w*|ixus\w*|snappy\w*|af\d*\w*|bf\w*|sureshot\w*|autoboy\w*|zoom\w*|\d{3}ed", COMPACT),
    # Yashica
    ("Yashica", r"fx(?:2|3)\w*|j\w*|penta\w*|44\w*|mat\w*|d|lm|a|635|minister\w*|tl(?!electro)\w*", MECH),
    ("Yashica", r"mg\w*|electro\w*|gs\w*|gt\w*|gsn|10[789]\w*|multiprogram\w*|fx(?:1|7|70|103|d)\w*|fr\w*|tlelectro\w*|atoron\w*", ELEC),
    ("Yashica", r"mf\w*|35mf|ez\w*|zoomate\w*|zoomtec\w*|t\d\w*|af\w*|cs\w*|partner\w*|auto|patio", COMPACT),
    # Fujica / Fuji
    ("Fujica", r"stx\w*|st60\w*|st701", MECH),
    ("Fujica", r"ax\w*|az\w*|st901", ELEC),
    ("Fujica", r"single\w*", MOVIE),
    ("Fujica", r"dl\w*|flash\w*|zoom\w*|tiara\w*|mf\w*|ge|sivi|fz\w*|\d{4}\w*|alt", COMPACT),
    # Ricoh
    ("Ricoh", r"kr5\w*|xr1|xr2|singlex\w*|tls\w*|slx\w*|500|519\w*", MECH),
    ("Ricoh", r"kr10\w*|xr7\w*|xr10\w*|xr20\w*|xrs|xrx\w*|xrp\w*|500(?:g|me|rf)\w*", ELEC),
    ("Ricoh", r"ff\w*|rz\w*|shotmaster\w*|mirai\w*|ac\d|af\w*|fz\w*|35zf|myport\w*", COMPACT),
    # Chinon, Cosina, Konica, Mamiya
    ("Chinon", r"cm\w*|cs\w*|m1", MECH),
    ("Chinon", r"ce\w*|ca\w*|cg\w*", ELEC),
    ("Chinon", r"cp\w*|35\w*|auto\w*|genesis\w*|bellami\w*", COMPACT),
    ("Cosina", r"ct1\w*|hi-?lite\w*", MECH),
    ("Cosina", r"compact\w*", COMPACT),
    ("Konica", r"autos\d\w*|auto\w*|ft\w*|fp\w*|fc\w*|fs\w*|tc\w*", ELEC),
    ("Konica", r"c35\w*|pop\w*|mt\w*|mr\w*|zup\w*|efp\w*|a4|af\w*|bigmini\w*", COMPACT),
    ("Mamiya", r"msx\w*|press\w*|c33\w*|c22\w*|c3|universal\w*|rb\w*|\d{3,4}dtl|dsx\w*", MECH),
    ("Mamiya", r"ze\w*|zm\w*|6\w*|7\w*", ELEC),
    ("Mamiya", r"135\w*|u\w*", COMPACT),
    # Olympus, Contax, Praktica, Zenit
    ("Olympus", r"pen(?:d\w*|s|w)?|om2000|ftl", MECH),
    ("Olympus", r"35(?:rc|sp|ec|dc)\w*|om(?:10|20|30|40|101|707|f|g|pc)\w*", ELEC),
    ("Olympus", r"trip\w*|af\w*|is\w*|az\w*|superzoom\w*|mju\w*|miju\w*|am\w*|centurion\w*|tenuta\w*|zoom\w*|xa\w*|penee\w*|peneed", COMPACT),
    ("Contax", r"s2\w*|iii\w*|ii\w*|i", MECH),
    ("Contax", r"167mt|rts\w*|137\w*|139\w*|159\w*|aria|st|rx\w*|167", ELEC),
    ("Contax", r"g\d|tvs\w*|t\d\w*|n\w*", AF),
    ("Praktica", r"b\w*|ee\w*|electronic\w*|plelectronic\w*", ELEC),
    ("Praktica", r"lb|mtl\w*|tl\w*|supertl\w*|ltl\w*|nova\w*|super\w*", MECH),
    ("Praktica", r"prix\w*|softlite\w*|fm35\w*|z\d+\w*|af\w*", COMPACT),
    ("Zenit", r"\d{1,2}\w*|e\w*|ttl\w*", MECH),
    # Older European and Soviet makers: mechanical shutters
    ("Zeiss Ikon", r"contessamat\w*", ELEC), ("Zeiss Ikon", r"\w*", MECH),
    ("Voigtländer", r"vitrona\w*|vf\w*", COMPACT), ("Voigtländer", r"\w*", MECH),
    ("Agfa", r"clack|synchro\w*|box\w*|isoly\w*|lux|agfascop\w*|paramat\w*|selecta\w*|optima\w*", COMPACT),
    ("Agfa", r"\w*", MECH),
    ("Kodak", r"retina\w*|retinette\w*|six\w*|620|folding\w*|pony\w*", MECH),
    ("Kodak", r"\w*", COMPACT),
    ("Bencini", r"\w*", MECH), ("Ferrania", r"\w*", MECH), ("Lubitel", r"\w*", MECH), ("Smena", r"\w*", MECH),
    ("Zorki", r"10|11|12", ELEC), ("Zorki", r"\w*", MECH), ("FED", r"\d{2}\w*", COMPACT), ("FED", r"\w*", MECH),
    ("Kiev", r"\w*", MECH), ("Exakta", r"\w*", MECH), ("Ihagee", r"\w*", MECH), ("Edixa", r"\w*", MECH),
    ("Beirette", r"\w*", MECH), ("Petri", r"\w*", MECH), ("Topcon", r"\w*", MECH), ("Miranda", r"\w*", MECH),
    ("Linhof", r"\w*", MECH), ("Bronica", r"etr\w*|sq\w*|gs\w*", ELEC), ("Bronica", r"\w*", MECH),
    ("Seagull", r"\w*", MECH), ("Pentacon", r"six\w*", MECH), ("Pentacon", r"\w*", COMPACT),
    ("Rollei", r"xf\w*|a110|af\w*|prego\w*", COMPACT),
    ("Rollei", r"sl35e|sl2000\w*|3003", ELEC), ("Rollei", r"\w*", MECH),
    ("Hasselblad", r"\d{3}el\w*|el\w*|\d{4}\w*", ELEC), ("Hasselblad", r"\w*", MECH),
    ("Leica", r"\w*", MECH),
    ("Minox", r"\w*", COMPACT), ("Haking", r"\w*", COMPACT), ("Halina", r"\w*", COMPACT),
    ("Hanimex", r"\w*", COMPACT), ("Samsung", r"\w*", COMPACT), ("Kyocera", r"\w*", COMPACT),
    ("Photax", r"\w*", COMPACT), ("Olympia", r"\w*", COMPACT), ("Vivitar", r"v\d{4}\w*", MECH),
    ("Polaroid", r"\w*", COMPACT),
]
_COMPILED = [(brand, re.compile(rf"(?:{pattern})$"), kind) for brand, pattern, kind in _RULES]


def camera_kind(name):
    """'Minolta X-300' -> 'полуавтомат / электроника'; '?' when not known."""
    if not name:
        return UNKNOWN
    for brand, rx, kind in _COMPILED:
        if name.startswith(brand + " "):
            model = re.sub(r"[\s\-./]", "", name[len(brand) + 1:].lower())
            if rx.match(model):
                return kind
    return UNKNOWN
