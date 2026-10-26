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

from . import markers
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
    "Braun": (EUROPE, ["braun"]),
    "Altix": (EAST, ["altix", "altissa"]),
    "Gamma": (EUROPE, ["gamma"]),
    "Pax": (JAPAN, ["pax"]),
    "Edixa": (EUROPE, ["edixa"]),
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
    ("Nikon", "Nikkormat FTn", MECH, S35, ["nikkormat ftn!", "ftn", "^ft n"], None),
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
    ("Pentax", "Pentax Spotmatic", MECH, S35, ["spotmatic!", "^sp"], r"(?:sp ?)?(?:ii|iia|2|500|1000)(?![a-z0-9])"),
    ("Pentax", "Pentax Spotmatic F", MECH, S35, ["spotmatic f!", "^sp f"], None),
    ("Pentax", "Pentax SV", MECH, S35, ["^sv"], None),
    ("Pentax", "Pentax K1000", MECH, S35, ["k 1000!"], None),
    ("Pentax", "Pentax KM", MECH, S35, ["^=km"], None),
    ("Pentax", "Pentax MX", MECH, S35, ["mx"], None),
    ("Pentax", "Pentax KX", MECH, S35, ["^=kx"], None),
    ("Olympus", "Olympus OM-1", MECH, S35, ["om 1!"], None),
    ("Olympus", "Olympus OM-1n", MECH, S35, ["om 1 n!"], None),
    ("Olympus", "Olympus OM-1 MD", MECH, S35, ["om 1 md!"], None),
    ("Olympus", "Olympus OM-3", MECH, S35, ["om 3!"], None),
    ("Olympus", "Olympus OM-3Ti", MECH, S35, ["om 3 ti!", "om 3 titan!"], None),
    ("Olympus", "Olympus M-1", MECH, S35, ["^m 1"], None),  # the first name of the OM-1 (1972)
    ("Olympus", "Olympus OM-2000", MECH, S35, ["om 2000!"], None),
    ("Olympus", "Olympus FTL", MECH, S35, ["^ftl"], None),
    # half-frame SLRs (1963-1970); the digital PEN-F of 2016 is told apart by DIGITAL_TWINS
    ("Olympus", "Olympus Pen F", MECH, S35, ["pen f"], None),
    ("Olympus", "Olympus Pen FT", MECH, S35, ["pen ft"], None),
    ("Olympus", "Olympus Pen FV", MECH, S35, ["pen fv"], None),
    ("Minolta", "Minolta SR-T 101", MECH, S35, ["sr t 101!", "sr t 101 b!"], None),
    ("Minolta", "Minolta SR-T 100X", MECH, S35, ["sr t 100 x!"], None),  # 1975
    # SR-T 303 is the European name of the SR-T 102
    ("Minolta", "Minolta SR-T 102", MECH, S35, ["sr t 102!", "sr t 303!", "sr t 303 b!"], None),
    ("Minolta", "Minolta SR-T 201", MECH, S35, ["sr t 201!"], None),
    ("Minolta", "Minolta SR-7", MECH, S35, ["sr 7"], None),
    # with the SR-1s; not a lens marking 'SR 1:1.4'
    ("Minolta", "Minolta SR-1", MECH, S35, ["sr 1", "sr 1 s"], r"[:,.]\s*\d"),
    ("Konica", "Konica Auto-Reflex", MECH, S35, ["auto reflex"], r"(?:t|tc|t2|t3|t4|a|a1|a3|p)(?![a-z0-9])"),
    ("Konica", "Konica Autoreflex T", MECH, S35, ["auto reflex t!"], None),
    ("Konica", "Konica Autoreflex T2", MECH, S35, ["auto reflex t 2!"], None),
    ("Konica", "Konica Autoreflex T3", MECH, S35, ["auto reflex t 3!", "auto reflex t 3 n!"], None),
    ("Konica", "Konica Autoreflex T4", MECH, S35, ["auto reflex t 4!"], None),
    ("Yashica", "Yashica FX-3", MECH, S35, ["fx 3"], r"super"),
    ("Yashica", "Yashica FX-3 Super 2000", MECH, S35, ["fx 3 super 2000!"], None),
    ("Yashica", "Yashica FX-3 Super", MECH, S35, ["fx 3 super"], r"2000"),  # 1984
    ("Yashica", "Yashica FX-2", MECH, S35, ["fx 2"], None),  # 1976
    ("Mamiya", "Mamiya C330", MECH, MED, ["c 330!", "c 330 professional!"], None),
    ("Mamiya", "Mamiya C33", MECH, MED, ["c 33!"], None),  # 1965
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
    ("Leica", "Leica CL", MECH, S35, ["^cl"], None),  # Leitz-Minolta, 1973; the digital CL of 2017 is a twin
    # screw-mount rangefinders (Barnack, 1925-1957): 'Leica IIIf', 'Leica III f', 'Leica 3f', 'Leica II D'
    ("Leica", "Leica I", MECH, S35, ['^i'], None),
    ("Leica", "Leica Ic", MECH, S35, ['^i c'], None),
    ("Leica", "Leica If", MECH, S35, ['^i f'], None),
    ("Leica", "Leica Ig", MECH, S35, ['^i g'], None),
    ("Leica", "Leica II", MECH, S35, ['^ii', '^ii d'], None),
    ("Leica", "Leica IIc", MECH, S35, ['^ii c'], None),
    ("Leica", "Leica IIf", MECH, S35, ['^ii f'], None),
    ("Leica", "Leica III", MECH, S35, ['^iii'], None),
    ("Leica", "Leica IIIa", MECH, S35, ['^iii a', '^3 a'], None),
    ("Leica", "Leica IIIb", MECH, S35, ['^iii b', '^3 b'], None),
    ("Leica", "Leica IIIc", MECH, S35, ['^iii c', '^3 c'], None),
    ("Leica", "Leica IIIf", MECH, S35, ['^iii f', '^3 f'], None),
    ("Leica", "Leica IIIg", MECH, S35, ['^iii g', '^3 g'], None),
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
    # the other mechanical Praktica bodies (M42 and earlier); Super TL1000 stays out
    ("Praktica", "Praktiflex", MECH, S35, ['praktiflex!'], None),
    ("Praktica", "Praktica FX", MECH, S35, ['^fx'], None),
    ("Praktica", "Praktica FX2", MECH, S35, ['^fx 2'], None),
    ("Praktica", "Praktica FX3", MECH, S35, ['^fx 3'], None),
    ("Praktica", "Praktica IV", MECH, S35, ['^iv'], None),
    ("Praktica", "Praktica IVB", MECH, S35, ['^iv b'], None),
    ("Praktica", "Praktica IVM", MECH, S35, ['^iv m'], None),
    ("Praktica", "Praktica IVBM", MECH, S35, ['^iv bm'], None),
    ("Praktica", "Praktica IVF", MECH, S35, ['^iv f'], None),
    ("Praktica", "Praktica IVFB", MECH, S35, ['^iv fb'], None),
    ("Praktica", "Praktica V", MECH, S35, ['^v'], None),
    ("Praktica", "Praktica VF", MECH, S35, ['^v f'], None),
    ("Praktica", "Praktica Nova", MECH, S35, ['^nova'], None),
    ("Praktica", "Praktica Nova B", MECH, S35, ['^nova b'], None),
    ("Praktica", "Praktica Nova I", MECH, S35, ['^nova 1', '^nova i', '^pl nova 1', '^pl nova i'], None),
    ("Praktica", "Praktica Nova IB", MECH, S35, ['^nova 1 b', '^nova ib', '^pl nova 1 b', '^pl nova ib'], None),
    ("Praktica", "Praktica Super TL2", MECH, S35, ['super tl 2'], None),
    ("Praktica", "Praktica Super TL3", MECH, S35, ['super tl 3'], None),
    ("Praktica", "Praktica L2", MECH, S35, ['^l 2'], None),
    ("Praktica", "Praktica LTL2", MECH, S35, ['ltl 2'], None),
    ("Praktica", "Praktica LTL3", MECH, S35, ['ltl 3'], None),
    ("Praktica", "Praktica LLC", MECH, S35, ['^llc'], None),
    ("Praktica", "Praktica Mat", MECH, S35, ['^mat'], None),
    ("Praktica", "Praktica MTL 50", MECH, S35, ['mtl 50!'], None),
    ("Praktica", "Praktica PLC2", MECH, S35, ['^plc 2'], None),
    ("Praktica", "Praktica PLC3", MECH, S35, ['^plc 3'], None),
    ("Praktica", "Praktica VLC", MECH, S35, ['^vlc'], None),
    ("Praktica", "Praktica VLC2", MECH, S35, ['^vlc 2'], None),
    ("Praktica", "Praktica VLC3", MECH, S35, ['^vlc 3'], None),
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
    ("Zenit", "Zenit 12", MECH, S35, ["^12"], None),  # 1983
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
    ("Zorki", "Zorki 1", MECH, S35, ["^1"], None),  # 1948
    ("Zorki", "Zorki 2C", MECH, S35, ["^2 c", "^2 s"], None),  # 1955, Зоркий-2С
    # marked green by the user on 'Предложение' and 'По фото: без названия' (and the Fujica ST family)
    ("Fujica", "Fujica ST701", MECH, S35, ['^st 701'], None),
    ("Fujica", "Fujica ST801", MECH, S35, ['^st 801'], None),
    ("Fujica", "Fujica ST605", MECH, S35, ['^st 605'], None),
    ("Fujica", "Fujica ST605N", MECH, S35, ['^st 605 n', '^st 605 ii'], None),
    ("Fujica", "Fujica ST705", MECH, S35, ['^st 705', '^st 705 w'], None),
    ("Fujica", "Fujica STX-1", MECH, S35, ['^stx 1'], None),
    ("Fujica", "Fujica STX-1N", MECH, S35, ['^stx 1 n'], None),
    ("Nikon", "Nikkormat FT", MECH, S35, ['^ft', 'nikkormat ft!'], r"n(?![a-z])|el\b|[23]"),  # not FTn / FT2 / FT3
    ("Canon", "Canon Canonet QL17", ELEC, S35, ['canonet ql 17!', 'canonet g iii ql 17!', 'canonet ql 17 g iii!', 'canonet g iii 17!'], None),
    ("Minolta", "Minolta XG-2", ELEC, S35, ['xg 2'], None),
    ("Minolta", "Minolta Hi-Matic F", ELEC, S35, ['hi matic f!', 'himatic f!', '^matic f'], None),
    ("Yashica", "Yashica Electro 35 GSN", ELEC, S35, ['electro 35 gsn'], None),
    ("Yashica", "Yashica 44 LM", MECH, MED, ['^44 lm', 'yashica 44 lm!'], None),
    ("Agfa", "Agfa Super Silette", MECH, S35, ['super silette!'], None),
    ("Zeiss Ikon", "Zeiss Ikon Ikonta", MECH, MED, ['ikonta!', r'~ikonta[\s\-.,_/]*\d{3}(?:/\d+)?'], None),  # 'Ikonta 521/16'
    ("Zeiss Ikon", "Zeiss Ikon Nettar", MECH, MED, ['nettar!', r'~nettar[\s\-.,_/]*\d{3}(?:/\d+)?'], None),  # 'Nettar 515/2'
    ("Zeiss Ikon", "Zeiss Ikon Symbolica", MECH, S35, ['symbolica!'], None),
    ("Zeiss Ikon", "Zeiss Ikon Taxona", MECH, S35, ['taxona!'], None),
    ("Braun", "Braun SR 2000", MECH, S35, ['^sr 2000'], None),
    ("Altix", "Altix NB", MECH, S35, ['^n b', 'altix n b!'], None),
    ("Gamma", "Gamma Perla", MECH, S35, ['^perla'], None),
    ("Pax", "Pax M4", MECH, S35, ['^m 4'], None),
    ("Edixa", "Edixa Prismaflex", MECH, S35, ['^prismaflex'], None),
    ("Zorki", "Zorki 4K", MECH, S35, ["^4 k"], None),
    # Ihagee Exa (Dresden, 1951-1987): 'Ihagee EXA-I', 'Exa Ia', 'Exa 1b'
    ("Exakta", "Ihagee Exa", MECH, S35, ['exa!'], None),
    ("Exakta", "Ihagee Exa I", MECH, S35, ['exa 1!', 'exa i!'], None),
    ("Exakta", "Ihagee Exa Ia", MECH, S35, ['exa 1 a!', 'exa ia!'], None),
    ("Exakta", "Ihagee Exa Ib", MECH, S35, ['exa 1 b!', 'exa ib!'], None),
    ("Exakta", "Ihagee Exa Ic", MECH, S35, ['exa 1 c!', 'exa ic!'], None),
    ("Exakta", "Ihagee Exa II", MECH, S35, ['exa 2!', 'exa ii!'], None),
    ("Exakta", "Ihagee Exa IIa", MECH, S35, ['exa 2 a!', 'exa ii a!'], None),
    ("Exakta", "Ihagee Exa IIb", MECH, S35, ['exa 2 b!', 'exa ii b!'], None),
    ("Exakta", "Ihagee Exa 500", MECH, S35, ['exa 500!'], None),
    ("Kiev", "Kiev 4", MECH, S35, ["^4"], None),
    ("Kiev", "Kiev 4A", MECH, S35, ["^4 a"], None),
    ("Kiev", "Kiev 4M", MECH, S35, ["^4 m"], None),
    ("Kiev", "Kiev 4AM", MECH, S35, ["^4 am"], None),
    ("Kiev", "Kiev 88", MECH, MED, ["^88"], r"(?:cm|sm)(?![a-z0-9])"),
    ("Kiev", "Kiev 60", MECH, MED, ["^60"], None),
    ("Kiev", "Kiev 6C", MECH, MED, ["^6 c", "^6 s"], None),
    # the other mechanical Kievs: rangefinders, Nikon-mount SLRs, medium format
    ("Kiev", "Kiev 2", MECH, S35, ['^2'], None),
    ("Kiev", "Kiev 2A", MECH, S35, ['^2 a'], None),
    ("Kiev", "Kiev 3", MECH, S35, ['^3'], None),
    ("Kiev", "Kiev 3A", MECH, S35, ['^3 a'], None),
    ("Kiev", "Kiev 5", MECH, S35, ['^5'], None),
    ("Kiev", "Kiev 17", MECH, S35, ['^17'], None),
    ("Kiev", "Kiev 19", MECH, S35, ['^19'], None),
    ("Kiev", "Kiev 19M", MECH, S35, ['^19 m'], None),
    ("Kiev", "Kiev 20", MECH, S35, ['^20'], None),
    ("Kiev", "Kiev 88CM", MECH, MED, ['^88 cm', '^88 sm'], None),
    ("Kiev", "Kiev Salut", MECH, MED, ['^salut'], None),
    ("Kiev", "Kiev Salut-S", MECH, MED, ['^salut s'], None),
    ("Kiev", "Kiev 90", MECH, MED, ['^90'], None),
    # --- semi-automatic, hybrid, electronic
    ("Canon", "Canon AE-1", ELEC, S35, ["ae 1!"], None),
    ("Canon", "Canon AE-1 Program", ELEC, S35, ["ae 1 program!", "ae 1 programm!", "ae 1 prog!", "ae 1 p!"], None),
    ("Canon", "Canon A-1", ELEC, S35, ["^a 1"], None),
    ("Canon", "Canon AV-1", ELEC, S35, ["av 1"], None),
    ("Canon", "Canon AL-1", ELEC, S35, ["al 1"], None),
    # right after the brand only: 'shutter at 1/125' in a description is no camera
    ("Canon", "Canon AT-1", ELEC, S35, ["^at 1"], None),
    ("Canon", "Canon T90", ELEC, S35, ["t 90"], None),
    # the rest of the FD-mount T series
    ("Canon", "Canon T50", ELEC, S35, ["t 50"], None),
    ("Canon", "Canon T60", ELEC, S35, ["t 60"], None),
    ("Canon", "Canon T70", ELEC, S35, ["t 70"], None),
    ("Canon", "Canon T80", ELEC, S35, ["t 80"], None),
    ("Canon", "Canon EF", ELEC, S35, ["^ef"],
     r"\d|s(?![a-z])|m(?![a-z])|objektiv|obiettiv|objectif|lens|zoom|usm|optik"),
    ("Canon", "Canon New F-1", ELEC, S35, ["new f 1"], None),
    ("Nikon", "Nikon F3", ELEC, S35, ["^f3", "^f3 hp", "^f3 t", "^f3 p"], None),
    ("Nikon", "Nikon F4", ELEC, S35, ["^f4", "^f4 s", "^f4 e"], None),
    ("Nikon", "Nikon FE", ELEC, S35, ["fe"], None),
    ("Nikon", "Nikon FE2", ELEC, S35, ["fe 2"], None),
    ("Nikon", "Nikon FA", ELEC, S35, ["^fa"], None),
    ("Nikon", "Nikon FG", ELEC, S35, ["fg"], None),
    ("Nikon", "Nikon FG-20", ELEC, S35, ["fg 20"], None),
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
    # the simplified R4, with its Mod 2 ('R4-S', 'R4s Mod. 2')
    ("Leica", "Leica R4s", ELEC, S35, ["r4 s", "r4 s mod 2", "r4 s mod2"], None),
    ("Leica", "Leica R5", ELEC, S35, ["r5"], None),
    # the simplified R5; 're' right after the brand only
    ("Leica", "Leica R-E", ELEC, S35, ["^r e"], None),
    ("Leica", "Leica R7", ELEC, S35, ["r7"], None),
    ("Leica", "Leica R8", ELEC, S35, ["r8"], None),
    ("Leica", "Leica R9", ELEC, S35, ["r9"], None),
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
VERSION = 46

# Models added later: the model search looks for their old listings first (once).
# Searched again first after the search covered 3714/3717 (cameras found there).
PRIORITY_SEARCH = ("Canon FX", "Canon FP", "Canon TL", "Canon TLb", "Canon TX", "Canon AT-1", "Nikon FG-20",
                   "Canon AE-1", "Canon AE-1 Program", "Canon AV-1", "Canon F-1", "Canon A-1", "Leica R-E", "Leica R4s",
                   "Minolta SR-1", "Minolta SR-T 102", "Leica R9", "Canon T50", "Canon T60", "Canon T70", "Canon T80",
                   "Praktiflex", "Praktica FX", "Praktica FX2", "Praktica FX3", "Praktica IV", "Praktica IVB", "Praktica IVM", "Praktica IVBM", "Praktica IVF", "Praktica IVFB", "Praktica V", "Praktica VF", "Praktica Nova", "Praktica Nova B", "Praktica Nova I", "Praktica Nova IB", "Praktica Super TL2", "Praktica Super TL3", "Praktica L2", "Praktica LTL2", "Praktica LTL3", "Praktica LLC", "Praktica Mat", "Praktica MTL 50", "Praktica PLC2", "Praktica PLC3", "Praktica VLC", "Praktica VLC2", "Praktica VLC3", "Kiev 2", "Kiev 2A", "Kiev 3", "Kiev 3A", "Kiev 5", "Kiev 17", "Kiev 19", "Kiev 19M", "Kiev 20", "Kiev 88CM", "Kiev Salut", "Kiev Salut-S", "Kiev 90",
                   "Olympus M-1", "Olympus OM-2000", "Olympus FTL", "Olympus Pen F", "Olympus Pen FT", "Olympus Pen FV",
                   "Minolta SR-T 100X", "Yashica FX-2", "Yashica FX-3 Super", "Zenit 12", "Zorki 1", "Zorki 2C", "Mamiya C33",
                   "Fujica ST701", "Fujica ST801", "Fujica ST605", "Fujica ST605N", "Fujica ST705", "Fujica STX-1", "Fujica STX-1N", "Nikkormat FT", "Canon Canonet QL17", "Minolta XG-2", "Minolta Hi-Matic F", "Yashica Electro 35 GSN", "Yashica 44 LM", "Agfa Super Silette", "Zeiss Ikon Ikonta", "Zeiss Ikon Nettar", "Zeiss Ikon Symbolica", "Zeiss Ikon Taxona", "Braun SR 2000", "Altix NB", "Gamma Perla", "Pax M4", "Edixa Prismaflex",
                   "Olympus OM-1 MD", "Leica CL", "Leica I", "Leica Ic", "Leica If", "Leica Ig", "Leica II", "Leica IIc", "Leica IIf", "Leica III", "Leica IIIa", "Leica IIIb", "Leica IIIc", "Leica IIIf", "Leica IIIg", "Ihagee Exa", "Ihagee Exa I", "Ihagee Exa Ia", "Ihagee Exa Ib", "Ihagee Exa Ic", "Ihagee Exa II", "Ihagee Exa IIa", "Ihagee Exa IIb", "Ihagee Exa 500")

# Models that must not match when the text also contains this pattern.
MODEL_EXCLUDE = {
    "Canon EF": re.compile(r"\beos\b"),  # 'Canon EF' there is the EOS lens mount, not the 1973 camera
}
# Models whose names digital cameras share: a title match is dropped (flag 'digital?') when the
# title or the description shows the digital one (the Micro Four Thirds PEN-F of 2016, 'E-M1').
_DIGITAL_TWIN = (r"(?<![a-z])m\.? ?zuiko|\bmft\b|micro ?(?:four|4) ?thirds|\bsensor|auslosungen|shutter count"
                 r"|declenchements|\bevf\b|\b4k\b|\bibis\b|\d ?mp\b|megapixel|digital|numerique"
                 # chargers, rechargeable batteries, screens: the half-frame Pen F has no battery at all
                 r"|mirrorless|spiegellos|hybride|caricabatter|ladegerat|ladekabel|chargeur|\bcharger|\bakku|\blcd\b"
                 r"|\bwi-?fi\b|\bvideo\b|\bjpe?g\b")
# The film OM-1 is sold with words like 'hybride', 'video', 'digital' around it ('pas hybride'),
# so the OM System OM-1 of 2022 and the E-M1 are told by Micro Four Thirds signs only.
_DIGITAL_OM = (r"(?<![a-z])m\.? ?zuiko|micro ?(?:four|4) ?thirds|\bmft\b|\d ?mp\b|megapixel|mirrorless|spiegellos"
               r"|\bevf\b|\bibis\b|\bom system om-?1\b|\bom-?d\b|\be-?m ?1\b|mark ?(?:ii|iii|2|3)\b")
DIGITAL_TWINS = {
    "Olympus Pen F": re.compile(_DIGITAL_TWIN),
    "Olympus M-1": re.compile(_DIGITAL_OM),
    "Olympus OM-1": re.compile(_DIGITAL_OM),
    # the digital Leica CL of 2017: APS-C, TL lenses
    "Leica CL": re.compile(_DIGITAL_OM + r"|aps-?c|\btl\b|\btl ?2\b|vario|\b4k\b|ladegerat|caricabatter|chargeur|\bcharger|\bakku"),
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


_BETWEEN = (r"(?:kamera|camera|appareil(?: photo)?|fotocamera|spiegelreflex(?:kamera)?|slr|reflex"
            r"|analog(?:e|ue)?|analogique|argentique|vintage"
            # a lens maker named with the camera: 'Macchina Canon Vivitar AT-1 funzionante'
            r"|vivitar)")


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
        tail += r"(?!\s*-?\s*(?:(?!1[89]\d\d\b)\d{2,}(?![\d.,:]|\s*mm)|\d" + _NOT_OTHER_MODEL + "))"
    # Mount names: 'Nikon F mount', 'Canon EF Bajonett' are lenses/adapters.
    tail += rf"(?!{SEP}(?:mount|bajonett|bayonet|anschluss|adapter|adaptateur|monture|attacco|innesto|vatting))"
    # 'Canon Kamera F-1', 'Nikon analoge FM': one word naming the camera may sit in between.
    head = _START + (_brand_pattern(BRANDS[brand][1]) + SEP + f"(?:{_BETWEEN}{SEP})?" if adjacent else "")
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
    # cases: it / fr / nl / es ('Custodia in pelle originale Olympus OM series')
    r"|custodia|astuccio|\bfodero|\bhousse|\bhoes\b|\bfunda\b"
    r"|objektiv|\blens(?:es)?\b|obiettiv|objectif|\blente\b|blitz|\bflash|speedlite"
    r"|winder|motor ?drive|\bbooster\b|anleitung|(?<!fully )(?<!full )\bmanual\b(?!\s*(?:focus|fokus|camera|kamera|slr|exposure|mode))"
    r"|handbuch|mode d.emploi|istruzioni|handleiding"
    r"|zubehor|accessoire|accessori|toebehoren|\bfilter|deckel|\bprism|mattscheibe|focusing screen"
    r"|\badapter|batterie|\bbattery|\bgriff\b|\bgrip\b|stativ|tripod|treppiede|belichtungsmesser"
    r"|\blivella|wasserwaage|\blibelle\b|niveau a bulle|bubble level|spirit level|waterpas"
    r"|light ?meter|posemetre|esposimetro|ruckteil|\bfilm ?back|magazin\b|gegenlichtblende"
    r"|lens hood|ausloser|\bfilm(?:e|s)?\b(?!\s*(?:kamera|camera))|pellicol|pellicule|\bfilmrolle"
    r"|\bback\b|data ?back|(?<!range)finder|(?<!mess)sucher\b|\bviseur|\bmirino|waist ?level|lichtschacht"
    r"|zubehor\b|acc?es+oires?\b|accessori[oe]?\b|accessor(?:y|ies)\b|toebehoren\b"
    r"|katalog|catalog|cataloghi|catalogue|depliant|prospekt|brochure|broschure|\bguide\b|\bguida\b|ratgeber|leitfaden|\bbuch\b|\bbook\b|\blibro\b|\blivre\b|\bposter\b|zeitschrift|rivista|\bflyer")
# Lens makers and zoom: 'Zoom Vivitar 70/210 per Nikon F' is a lens.
_LENS_WORDS = re.compile(r"\bzoom\b|vivitar|tamron|\bsigma\b|tokina|soligor|hanimex"
                         r"|makinon|exaktar|\bkiron\b|samyang|rokinon|beroflex|danubia|revuenon|panagor|\bosawa\b|cimko")
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
    # 'manuel' is also a manual camera ('appareil photo argentique manuel'): as a document only
    r"|^manuel\b|\bmanuel\b(?=\s+(?:d.utilisation|d.utilisateur|utilisateur|de l.utilisateur|d.instructions?"
    r"|original|en\s|francais|anglais|allemand))"
    r"|(?<!fully )(?<!full )\bmanual\b(?!\s*(?:focus|fokus|camera|kamera|slr|exposure|mode))"
    # 'Lot of Nikon usermanuals': manuals in the plural or run together are documents
    r"|user ?manuals?|\bmanuals\b|owner.?s manual")
# Spare parts. Preceded by "for/per/für..." it is a camera sold for parts instead.
_PARTS = re.compile(
    r"ricambi[oa]?\b|ersatzteil|spare parts?\b|pieces? detachees?|onderde(?:el|len)\b|calotta|top cover"
    r"|bottom plate|bodenplatte|shutter curtain|verschlussvorhang"
    # it: front plate, frame counter, winding, lever, dial, knob, cover, bottom plate
    r"|mascherina|contapose|avvolgimento|\bleva\b|\bghiera|manopola|coperchio|fondello"
    # de: front plate, top cover, advance lever, frame counter, leatherette
    r"|frontplatte|deckkappe|aufzugshebel|zahlwerk|belederung"
    # en / fr / nl
    r"|front plate|advance lever|rewind crank|frame counter|leatherette"
    r"|\bcapot\b|levier d.armement|\bcompteur\b|\bgainage|\bmousses?\b|bovenkap|onderplaat"
    # badge, battery cap / compartment, eyecup and cap
    r"|etichetta|\btappo\b|\bvano\b|oeilleton|\bcache\b|eyecup|augenmuschel|oculaire"
    # body / lens / rear caps
    r"|body ?caps?\b|gehausedeckel|ruckdeckel|lens caps?\b|objektivdeckel"
    # focusing screen; keychains
    r"|depoli|matglas|porte ?-?cles?\b|keychain|key ?ring|schlusselanhanger|portachiavi|sleutelhanger"
    r"|ecran de visee|verre de visee|mattscheibe|einstellscheibe|focusing screen|schermo di messa a fuoco"
    r"|vetrino di messa a fuoco|matglazen|\bmatglas"
    # rewind crank / knob / lever
    # jewellery, magnets and stickers shaped like a camera ('Ciondolo Zenit 122')
    r"|ciondol[oi]|pendentif|kettenanhanger|halskette|necklace|collana|\bcollier\b|orecchin[oi]|ohrring\w*|earrings?\b"
    r"|\bmagnet\b|kuhlschrankmagnet|\baimant\b|calamita|sticker|aufkleber|adesiv[oi]|autocollant"
    # pin badges and memorabilia ('Vintage Leica Red Logo Pin Badge M6'); not 'pinhole'
    r"|\bpins?\b(?! ?hole)|\bbadges?\b|anstecker|anstecknadel|\bspilla\b|epinglette|\bpin s\b|memorabilia"
    # bare 'parts' and dials ('Spotmatic shutter speed ASA dial parts'); 'parts or repair' is a camera
    r"|\bparts?\b(?!\s*(?:or|/|&|and|\+)\s*repairs?)|\bdials?\b"
    # lens hoods ('Paraluce in gomma Mamiya 80-100 M645')
    r"|paraluce|gegenlichtblende|streulichtblende|pare ?-?soleil|lens ?hoods?\b|zonnekap"
    # clothing and shoes ('Splendido abito … Fantasia Zenit e colori')
    r"|\b(?:abito|vestito|gonna|camicia|maglia|maglietta|felpa|giacca|cappotto|pantaloni|kleid|bluse|pullover"
    r"|jacke|mantel|robe|jupe|chemise|manteau|pantalon|dress|skirt|t ?shirt|shirt|hoodie|sweater|jacket|trousers|jurk"
    r"|trui|broek|scarpe|schuhe|chaussures|sneakers)\b"
    r"|manivelle|rembobinage|ruckspul\w*|rewind (?:knob|lever)|manovella|riavvolgimento|terugspoel\w*")
# Light seals: a part before the model ('Kit guarnizioni luce Canon AE-1 Program'); after it they
# praise the camera ('Canon AE-1 neue Lichtdichtungen').
_SEALS = re.compile(r"light ?seals?\b|guarnizion\w*|lichtdichtung\w*|lichtafdichting\w*|joints? (?:de )?(?:mousse|lumiere)")
_FOR_BEFORE = re.compile(r"\b(?:per|for|pour|fur|als|voor|para)\s+(?:\w+\s+)?$")
# Words that say the listing is a camera body or kit, not just its manual.
_COMPATIBLE_AFTER = re.compile(r"\W*(?:passend|passt|kompatibel|compatible|compatibile|fits|adatt[oa]|geeignet)\b")
_KIT_LENS = re.compile(r"objektiv|lens(?:es)?|obiettiv|objectif|lente")
_KIT_PLUS_LENS = re.compile(r"\+\s*(?:[a-z]+\s+){0,2}\d{2,3}\s?mm")
_BUNDLE = re.compile(r"\b(?:lot|lotto|konvolut|bundle|set|kit)\b")
_KIT_WORDS = re.compile(r"\bbody\b|gehause|boitier|\bcorpo\b|objektiv|\blens|obiettiv|objectif|\bkit\b|\bset\b|\bnur\b")
# A description that starts with one of these (and names no camera) is about an accessory.
_LEAD_FILLER = re.compile(
    r"^(?:\W|(?:vendo|verkaufe|verkauf|je vends|vends|selling|sell|for sale|zu verkaufen|original[e]?|neu|new|nuov[oa]"
    r"|top|sehr|gut|guter|ottim[oa]|bon|bonne|tres|very|good|perfekt|perfetto|parfait)\b)+")
_LEAD_ACCESSORY = re.compile(
    r"(?:brochure|broschure|prospekt|depliant|catalog|katalog|cataloghi|catalogue|manual|manuale|manuel|notice"
    r"|libretto|(?:bedienungs)?anleitung|istruzioni|handbuch|objektiv|obiettivo|objectif|lens|zoom|tasche|borsa"
    r"|etui|blitz|flash|winder|sucher|viseur|mirino"
    r"|scatol\w*|confezione|boites?\b|schachtel|verpackung|karton|doos\b|caja\b)")
# Words that make a listing an accessory unless a "with" word comes before them.
# Printed matter (catalogues, brochures, books) counts too.
_STRONG_ACCESSORY = re.compile(
    r"zubehor\b|acc?es+oires?\b|accessori[oe]?\b|accessor(?:y|ies)\b|toebehoren\b"
    r"|katalog|catalog|cataloghi|catalogue|depliant|prospekt|brochure|broschure|\bguide\b|\bguida\b|ratgeber|leitfaden|\bbuch\b|\bbook\b|\blibro\b|\blivre\b|\bposter\b|zeitschrift|rivista|\bflyer"
    r"|camera (?:strap|bag|case|accessor)|kamera(?:tasche|gurt)"
    # books in the plural, works, publications: 'Lot 3 ouvrages anciens Leica - M3, Matheson, Causeries'
    r"|\bouvrages?\b|\bpublications?\b|\blivres\b|\bbooks\b|\bbucher\b|\blibri\b|\bboeken\b|\bboek\b"
    r"|^revue (?:photo |appareil )?(?:canon|nikon|pentax|minolta|olympus|leica|contax|yashica|konica|rollei|hasselblad"
    r"|mamiya|fujica|asahi)\b")
# Boxes: before the model the box is what is sold ('Scatola Nikon FE'); after it, the camera comes boxed.
_BOX = re.compile(r"\bscatol\w*|\bconfezione|\bboites?\b|schachtel|\bverpackung|\b(?:original)?karton\b|\bdoos\b"
                  r"|\bcaja\b|\bbox\b")
# Made for a camera, no model named: 'Livella per fotocamera', 'Cinghia per fotocamera'.
_FOR_CAMERA = re.compile(r"\b(?:fur|for|pour|per|voor|para)\s+(?:(?:la|le|l|die|den|eine?n?|the|a|une?|il|de)\s+)?"
                         r"(?:kamera|camera|appareil|fotocamera|macchina|fototoestel|camara|spiegelreflex)")
# The description says the camera in the photos is not sold, or the listing is a magazine:
# 'Fotocamera solo a scopo dimostrativo', 'Je vends une revue appareil canon reflex'.
_GAP = r"(?:\s+(?:selbst|itself|lui.meme|stess[ao]|zelf|ist|is|wird|e|est))?"  # 'Kamera ist nicht …'
_NOT_SOLD_CAMERA = re.compile(
    rf"(?:fotocamera|macchina(?: fotografica)?){_GAP}\s+(?:(?:solo|solamente|soltanto)\s+(?:a|per)\s+scopo"
    r"\s+(?:dimostrativo|illustrativo|espositivo)|non\s+(?:e\s+)?(?:inclus[ao]|compres[ao]|in vendita))"
    rf"|kamera{_GAP}\s+(?:nicht (?:im lieferumfang|enthalten|inklusive|dabei|mit verkauft)"
    r"|nur (?:zur|zu) (?:demonstration|veranschaulichung|anschauung|dekoration))"
    rf"|appareil(?: photo)?{_GAP}\s+(?:non (?:inclus|fourni|vendu)|n.est pas (?:inclus|fourni|vendu|a vendre)"
    r"|pas (?:inclus|fourni|vendu)|(?:present|utilise|montre)\w* (?:uniquement |seulement )?(?:a titre|pour) "
    r"(?:d.exemple|d.illustration|indicatif|la demonstration|la photo))"
    rf"|camera{_GAP}\s+(?:not included|is not (?:included|for sale)|for (?:illustration|demonstration|display)"
    r" (?:purposes )?only|only for (?:illustration|demonstration|display)|niet inbegrepen|(?:wordt )?niet meegeleverd)"
    r"|\b(?:une|la|cette|ma) revue (?:photo|appareil|sur|consacree|technique|canon|nikon|pentax|minolta|olympus|leica)"
    # only the (empty) box: 'SOLO SCATOLA VUOTA'
    r"|\bsolo (?:la )?scatola|scatola vuota|\bnur (?:die |der |den )?(?:original)?(?:verpackung|schachtel|karton|box)\b"
    r"|\bleere (?:original)?(?:schachtel|verpackung|box|karton)|(?:uniquement|seulement) (?:la )?boite|boite vide"
    r"|empty box|\bbox only|only the (?:original )?box|lege doos|alleen de doos")
_LEADING_FILLER = re.compile(
    r"^(?:\W|(?:vintage|rare|ancien(?:ne)?|alt(?:e|er)?|old|lot|lotto|set|kit|neu|new|nuovo)\b)+")
_MODEL_NUMBER = re.compile(r"[a-z]*\d+[a-z0-9]*")
_WITH_WORDS = re.compile(r"\b(?:mit|with|avec|con|met|inkl|incl|inklusive|including|plus|und|and|et|e)\b|[+&]")
_FOR_WORDS = re.compile(r"\b(?:fur|for|pour|per|voor|passend|passt|compatible|kompatibel|compatibile)\b")
# 'für Canon Cameras', 'per fotocamera', 'pour appareils Nikon': the camera word after 'for' (with a
# brand between at most) is what the thing fits.
_FOR_TARGET = re.compile(
    _FOR_WORDS.pattern + r"\s+(?:(?:" + "|".join(rx.pattern for rx in _BRAND_RX.values()) + r")\s+)?"
    r"(?:kameras?|cameras?|appareils?(?: photo)?|fotocamer[ae]|macchin[ae](?: fotografiche?)?|fototoestel(?:len)?)\b")
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
    r"|\bminox\b|miniatur"
    # Olympus OM-D / E-M10 / E-PL: Micro Four Thirds
    r"|\bom-?d\b|\be-?m ?(?:1|5|10)\b|\be-?pl? ?\d")

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


def _marker_words(kind):
    """The phrases of a marker kind (tracker/markers.py) as one pattern: normalized like titles,
    whole words, any apostrophe, a space or a dash between words."""
    phrases = sorted({normalize(p) for words in kind.values() for p in words}, key=len, reverse=True)
    parts = [re.escape(p).replace("'", ".").replace("\u2019", ".").replace("\\-", r"[\s\-]?")
             .replace("\\ ", r"[\s\-]+") for p in phrases]
    return r"\b(?:" + "|".join(parts) + r")\b"


# The multilingual base of words that mark no camera (tracker/markers.py) joins the rules above.
_MANUAL = re.compile(f"{_MANUAL.pattern}|{_marker_words(markers.MANUAL)}")
# Body parts: unlike _PARTS, not after a camera word or in a set ('Nikon F3 Analoge Kamera Set … Rückwand').
_BODY_PARTS = re.compile(_marker_words(markers.PARTS))
_STRONG_ACCESSORY = re.compile(f"{_STRONG_ACCESSORY.pattern}|{_marker_words(markers.PRINT)}")
_LEAD_ACCESSORY = re.compile(f"{_LEAD_ACCESSORY.pattern}|{_marker_words(markers.PRINT)}|{_marker_words(markers.BOX)}")
_BOX = re.compile(f"{_BOX.pattern}|{_marker_words(markers.BOX)}")
_ACCESSORY_WORDS = re.compile(
    f"{_ACCESSORY_WORDS.pattern}|{_marker_words(markers.LEVEL)}|{_marker_words(markers.TUBES)}")
_FOR_CAMERA = re.compile(f"{_FOR_CAMERA.pattern}|{_marker_words(markers.FOR_CAMERA)}")
_NOT_SOLD_CAMERA = re.compile(f"{_NOT_SOLD_CAMERA.pattern}|{_marker_words(markers.NOT_SOLD)}")
_WITH_WORDS = re.compile(f"{_WITH_WORDS.pattern}|{_marker_words(markers.WITH)}")


def _camera_joined(head):
    """'Objectif Sigma 28mm + appareil photo argentique ...': a camera joined to the accessory
    (not 'Objektiv und Blitz für Kamera ...')."""
    joined = _WITH_WORDS.search(head)
    rest = head[joined.end():] if joined else ""
    return bool(joined and _CAMERA_WORDS.search(rest) and not _FOR_WORDS.search(rest))


def _is_accessory(norm, model_span):
    strong = _STRONG_ACCESSORY.search(norm)
    if strong and not _WITH_WORDS.search(norm[:strong.start()]):
        return True  # "Nikon F3 accessoires", "Film Back - Camera Accessory"
    part = _PARTS.search(norm)
    if part and not _WITH_WORDS.search(norm[:part.start()]) and not _FOR_BEFORE.search(norm[:part.start()]):
        return True  # "Calotta superiore Pentax ME Super ricambio originale"
    body = _BODY_PARTS.search(norm)
    if body and not (_WITH_WORDS.search(norm[:body.start()]) or _FOR_BEFORE.search(norm[:body.start()])
                     or _CAMERA_WORDS.search(norm[:body.start()]) or _BUNDLE.search(norm)):
        return True  # "Sportello posteriore Olympus OM10"
    manual = _MANUAL.search(norm)
    if manual and not _WITH_WORDS.search(norm[:manual.start()]) and not _KIT_WORDS.search(norm):
        return True  # "Notice appareil photo Nikon FE2", "Mamiya M645 ... multi language manual"
    if model_span is not None:
        head = norm[:model_span[0]]
        # 'für Canon Cameras' is what the thing is for, not a camera on sale
        if (_LENS_WORDS.search(head) or _FOR_WORDS.search(head)) and not _CAMERA_WORDS.search(_FOR_TARGET.sub(" ", head)):
            return True  # "Zoom Vivitar 70/210 per Nikon F", "Exaktar 200mm 1:3,5 für Canon Cameras A-1"
        if _SEALS.search(head) and not _camera_joined(head):
            return True  # "Kit guarnizioni luce Canon AE-1 Program"
        if _BOX.search(head) and not _camera_joined(head):
            return True  # "Scatola Nikon FE": the box is sold
        if _COMPATIBLE_AFTER.match(norm[model_span[1]:]):
            return True  # "Canon FD 50mm 1:1.8 T50 passend": fits the camera
    if model_span is None:
        made_for = _FOR_CAMERA.search(norm)
        if made_for and not (_CAMERA_WORDS.search(norm[:made_for.start()]) or _WITH_WORDS.search(norm[:made_for.start()])):
            return True  # 'Livella per fotocamera': made for a camera
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
    if (_ACCESSORY_WORDS.search(head) or _FOR_WORDS.search(head)) and not _camera_joined(head):
        return True  # "Winder für Canon AE-1", "Leica data back R4"
    if _BUNDLE.search(norm):
        return False  # "Lot canon Av-1 vintage avaec objects, flash et accessoires": a camera with its kit
    tail = norm[end:]
    # A lens after the camera's name is its kit lens ('Canon AE1 Program | canon f1.8 macro lens'):
    # lenses sold alone name their mount ('Canon FD 50mm'), not a camera.
    acc = next((a for a in _ACCESSORY_WORDS.finditer(tail) if not _KIT_LENS.fullmatch(a.group(0))), None)
    # "Nikon F2 viseur DP1 + Nikon 100mm + Nikon 80-200": a camera sold with its finder and lenses.
    if _KIT_PLUS_LENS.search(tail):
        return False
    # "Mamiya RZ67 Pro Sekor Z 110mm f2.8 Lens, Extension Tubes & ...": its kit lens comes first.
    if acc and _KIT_LENS.search(tail[:acc.start()]):
        return False
    # "Nikon F Waist Level Finder ... Case": accessory words, no camera, no "with".
    return bool(acc) and not _WITH_WORDS.search(tail[:acc.start()]) and not _CAMERA_WORDS.search(norm)


# 'Open to offers' (de/fr/it/en/nl): with a price of a few EUR it is a placeholder, not the price.
_OFFERS = re.compile(
    r"offen fur (?:angebote|preisvorschlage|vorschlage)|angebote? (?:erwunscht|willkommen|gerne)|preisvorschlag"
    r"|preis (?:ist )?verhandelbar|verhandlungsbasis|\bvb\b"
    r"|ouverte? (?:a|aux) (?:offres?|propositions?|negociations?)|faites? (?:moi )?(?:une |vos )?(?:offres?|propositions?)"
    r"|faire (?:une )?offre|prix a debattre"
    r"|aperto a (?:offerte|proposte)|accetto (?:offerte|proposte)|fate(?:mi)? (?:un.)?offert[ae]|trattabil[ei]"
    r"|open (?:to|for) offers|make (?:me )?an offer|best offer|\bobo\b"
    r"|open voor (?:biedingen|bod)|\bbieden\b|\bbod\b")


def asks_for_offers(text):
    """The seller waits for offers ('Accetto offerte', 'offen für Angebote')."""
    return bool(text and _OFFERS.search(normalize(text)))


def names_camera(title):
    """The title says it is a camera or a kit ('Kamera', 'appareil', 'body', 'mit Objektiv')."""
    norm = normalize(title)
    return bool(_CAMERA_WORDS.search(norm) or _KIT_WORDS.search(norm))


def accessory_words(title):
    """Accessory/part/manual words *before* the model in a title (for review): words after it
    describe the kit ('Canon T90 Kamera Objektiv Speedlite'), words before it the object
    ('Winder für Canon AE-1'). Nothing if the title names no model."""
    norm = normalize(title)
    hits = find_models(norm)
    if not hits:
        return []
    head = norm[:hits[0][0]]
    if _camera_joined(head):
        return []  # 'Objectif Sigma 28mm + appareil photo argentique Konica Autoreflex TC'
    words = []
    for rx in (_PARTS, _MANUAL, _ACCESSORY_WORDS, _LENS_WORDS):
        for m in rx.finditer(head):
            if not _WITH_WORDS.search(head[:m.start()]) and m.group(0).strip() not in words:
                words.append(m.group(0).strip())
    return words


def lead_word(description):
    """The accessory/part/manual word a description starts with, or None."""
    lead = _LEAD_FILLER.sub("", normalize(description or "")[:160])
    m = _PARTS.match(lead) or _MANUAL.match(lead) or _BODY_PARTS.match(lead) or _LEAD_ACCESSORY.match(lead)
    return m.group(0).strip() if m else None


def lead_is_accessory(description):
    """The description starts with a part or manual word ('coperchio superiore fotocamera ...':
    the camera is what the part is for), or with an accessory word (brochure, lens...) and names
    no camera."""
    norm = normalize(description)[:160]
    lead = _LEAD_FILLER.sub("", norm)
    first = _PARTS.match(lead) or _MANUAL.match(lead) or _BODY_PARTS.match(lead)
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


# ---------------------------------------------------------------- exact camera names outside the list

# Camera makers for names outside the list (display name -> spellings); the list brands come too.
NAME_BRANDS = {
    "Zeiss Ikon": ["zeiss ikon"], "Carl Zeiss": ["carl zeiss"], "Ihagee": ["ihagee"], "Exakta": ["exakta"],
    "Hanimex": ["hanimex"], "Porst": ["porst"], "Revue": ["revue"], "Edixa": ["edixa"], "Balda": ["balda"],
    "Bilora": ["bilora"], "Ferrania": ["ferrania"], "Bencini": ["bencini"], "Beirette": ["beirette"],
    "Certo": ["certo"], "Welta": ["welta"], "Dacora": ["dacora"], "Wirgin": ["wirgin"], "Iloca": ["iloca"],
    "Braun": ["braun"], "Regula": ["regula"], "Adox": ["adox"], "Haking": ["haking"], "Halina": ["halina"],
    "Seagull": ["seagull"], "Vivitar": ["vivitar"], "Kowa": ["kowa"], "Minox": ["minox"], "Ensign": ["ensign"],
    "Argus": ["argus"], "Graflex": ["graflex"], "Plaubel": ["plaubel"], "Linhof": ["linhof"], "Sigma": ["sigma"],
    "Samsung": ["samsung"], "Kyocera": ["kyocera"], "Olympia": ["olympia"], "Photax": ["photax"],
    "Beroflex": ["beroflex"], "Yashica": ["yashica"], "Voigtländer": ["voigtlander", "voigtlaender"],
}
# Model names without a digit that are real models ('Zeiss Ikon Contaflex', 'Kodak Retina Ia').
_NAMED_MODELS = {
    "contaflex", "contessa", "contina", "contarex", "ikoflex", "icarex", "comet", "retina", "retinette", "spotmatic",
    "nikkormat", "unirex", "vito", "vitessa", "vitoret", "bessa", "bessamatic", "prominent", "silette", "isolette",
    "ambi", "karat", "electro", "trip", "pen", "canonet", "demi", "rapid", "sokol", "praktiflex", "varex",
    "werra", "penti", "paxette", "retinax", "colorsnap", "rolleicord", "flexaret", "autocord", "minoltacord",
    "yashicamat", "ricohflex", "primoflex", "dynax", "maxxum", "lubitel", "smena", "vega", "start", "topcon",
    "auto", "super", "program", "quartz", "spot", "electronic", "mat", "sport", "nova",
}
_NAME_FILLER = re.compile(
    r"^(?:kamera|camera|fotocamera|appareil|photo|foto|fotoapparat|fototoestel|toestel|argentique|analog\w*|vintage"
    r"|reflex|slr|spiegelreflex\w*|macchina|macchinetta|fotografica|retro|ancien\w*|alte|alter|old|35mm|24x36|film"
    r"|messsucher\w*|rangefinder|telemetro|body|gehause|boitier|corpo|black|chrome|silver|noir|noire|schwarz|nero"
    r"|biottica|bi-objectif|tlr|wetzlar|germany|japan|made|in|kleinbild\w*|mittelformat\w*|sucherkamera)$")
_NAME_STOP = re.compile(
    r"^(?:mit|with|avec|con|und|and|et|e|met|y|\+|&|objektiv\w*|obiettiv\w*|objectif|lens|lente|lenzen|f|mm|"
    r"\d+mm|\d+[.,]\d|\d+/\d+|\d{2,3}-\d{2,3}(?:mm)?|f=\S*|f\d[.,]\d+|f/\S+|de|da|di|del|della|du|per|pour|for|fur|incl\w*|plus"
    r"|set|lot|kit|-|–|—|\||/|,|completa"
    r"|complet|komplett|funktion\w*|fonctionne\w*|funzionante|testet|teste|testato|tested|vendu|pas|anni|annees"
    r"|jahre|years|model|modell|modele|modello|type|typ|tipo|neuf|nuovo|new|neu|gebraucht|usato|avec|sans|ohne"
    r"|a|al|il|la|le|les|the|un|une|en|im|zu|zum|appareil|kamera|camera|fotocamera|macchina"
    # serial numbers read on a photo, condition words, lens names
    r"|\d{5,}\w*|inc|ltd|co|gmbh|corp|ottim[eoia]|buon[oa]|gut\w*|sehr|top|mint|excellent\w*|etat|bon|tres|perfekt\w*|perfett\w*"
    r"|rokkor|nikkor|zuiko|takumar|hexanon|yashinon|tessar|pancolar|helios|industar|jupiter|summicron|elmar|planar"
    r"|sonnar|xenar|skopar|cosinon|fujinon|serenar|color)$")


def _name_brand_rx():
    spellings = {}
    for brand, (_, aliases) in BRANDS.items():
        for alias in aliases:
            spellings[alias] = brand
    for brand, aliases in NAME_BRANDS.items():
        for alias in aliases:
            spellings[alias] = brand
    pattern = "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))
    return re.compile(r"(?<![a-z0-9])(" + pattern + r")(?![a-z0-9])"), spellings


_NAME_BRAND_RX, _NAME_SPELLINGS = _name_brand_rx()


def _model_token(token, raw, first, from_photo):
    """A token that can be (part of) a model name: has a digit, is a known model word, was written
    in capitals ('LB', 'SFX', 'GSN'), or - right after the brand in a seller's text - starts with a
    capital ('Agfa Selecta'). Text read on a photo is all capitals and noisy: digits need company."""
    if re.search(r"\d", token):
        return not from_photo or (len(token) >= 2 and token.isascii())
    if token in _NAMED_MODELS or re.fullmatch(r"i{1,3}[abcdfg]?|iv[a-z]?|v[a-z]?", token):  # 'Retina IIa', 'Leica IIIf'
        return True
    raw = raw.replace("-", "") if raw else raw  # 'SR-T', 'FT-N'
    if not raw or not raw.isalpha():
        return False
    if raw.isupper() and len(raw) == 1:
        return not first  # 'Rollei 35 S'
    if len(set(raw.lower())) < 2:
        return False
    if raw.isupper():
        return 1 < len(raw) <= 5
    return first and not from_photo and raw[0].isupper() and len(raw) >= 2  # 'Agfa Selecta', 'Pax Jr'


def _pretty(token):
    if re.search(r"\d", token) or len(token) <= 3 or re.fullmatch(r"[a-z]{1,3}(?:-[a-z]{1,3})+", token):
        return token.upper()  # 'X300S', 'LM', 'SR-T'
    return token.capitalize()


def camera_name(text, from_photo=False):
    """The exact camera named in a text, as (brand, model): 'minolta x300s' -> ('Minolta', 'X300S'),
    'Zeiss Ikon Contaflex' -> ('Zeiss Ikon', 'Contaflex'). None without a brand followed by a model.
    from_photo: the text was read on the photo (stricter)."""
    if not text:
        return None
    text = re.sub(r"[+&/]", " + ", text)
    raw_tokens = {}
    for raw in re.findall(r"[\w\-]+", text):
        raw_tokens.setdefault(normalize(raw), raw)
    norm = re.sub(r"\bf ?/ ?\d+(?:[.,]\d+)?|\bf\d+[.,]\d+", " | ", normalize(text))  # apertures: f/2.8, f1.8
    norm = re.sub(r"[(),;:!?\"'«»*•’‘`´.]", " ", norm)
    for match in _NAME_BRAND_RX.finditer(norm):
        brand = _NAME_SPELLINGS[match.group(1)]
        model = []
        for token in norm[match.end():].split():
            if _NAME_STOP.match(token) or _NAME_BRAND_RX.fullmatch(token) or re.fullmatch(r"(?:18|19|20)\d\d", token):
                break
            if _NAME_FILLER.match(token):
                if model:
                    break
                continue
            if not _model_token(token, raw_tokens.get(token), not model, from_photo):
                break
            model.append(token)
            if len(model) == 3:
                break
        if model:
            return brand, " ".join(_pretty(t) for t in model)
    return None


_LOT = re.compile(r"\b(?:lot|lots|lotto|set|konvolut|sammlung|collection|collezione|bundle|kit)\b"
                  r"|\b(?:\d|zwei|drei|deux|trois|due|tre|two|three|twee|drie) ?(?:x )?(?:kameras|cameras|appareils"
                  r"|macchine|fotocamere|fototoestellen|analogkameras)\b|\b\d ?x\b")


def bundle_names(title):
    """The cameras of a listing that sells several, or a lot: ['Pax M4', 'Pax Jr'] from '2x Vintage Pax
    camera - Pax M4 & Pax Jr'; [] for one camera. By the title only (descriptions compare with other
    models). Its price is not one camera's."""
    if not title:
        return []
    names = [m for _, _, m in find_models(title)]
    norm = normalize(title)
    pos = 0
    for match in _NAME_BRAND_RX.finditer(norm):
        # the same brand in the original text, so that capitals ('Pax Jr', 'MTL') still count
        spelled = re.compile(re.escape(match.group(1)).replace(r"\ ", r"[\s\-]*"), re.I).search(title, pos)
        piece = title[spelled.start():] if spelled else norm[match.start():]
        if spelled:
            pos = spelled.end()
        got = camera_name(piece)
        if got:
            name = list_model_of(*got) or f"{got[0]} {got[1]}"
            if name not in names:
                names.append(name)
    if len(names) >= 2 or (names and _LOT.search(norm)):
        return names
    return []


def _series(model_text):
    """The letters a model name starts with: 'X-700' -> 'x', 'FM2n' -> 'fm', 'OM-10' -> 'om', '122' -> ''."""
    return re.match(r"[a-z]*", normalize(model_text).replace(" ", "").replace("-", "")).group(0)


_LIST_SERIES = {}
for _m, _info in MODEL_INFO.items():
    _rest = _m[len(_info["brand"]):].strip() if _m.startswith(_info["brand"]) else _m
    _LIST_SERIES.setdefault((_info["brand"], _series(_rest)), []).append(_m)


def list_model_of(brand, model_text):
    """The list model a named camera is, or None ('Canon', 'AE-1 PROGRAM' -> 'Canon AE-1 Program')."""
    hits = find_models(f"{brand} {model_text}")
    return hits[0][2] if hits else None


def siblings(brand, model_text):
    """List models of the same brand and series as a camera outside the list ('Minolta', 'X-300'
    -> ['Minolta X-1', 'Minolta X-500', 'Minolta X-700']); [] if it is a list model itself."""
    if list_model_of(brand, model_text):
        return []
    return _LIST_SERIES.get((brand, _series(model_text)), [])


# ---------------------------------------------------------------- not worth tracking

# Listings outside the list that are of no interest at all: kept out of the data ('Остальные'
# holds the other manual cameras only). By the title, first match wins.
_JUNK = [
    ("instant", re.compile(r"polaroid|instax|\bintax\b|\bimpulse\b|sofortbild|\binstant|\bsx ?70\b|onestep|one step\b|istantane")),
    ("aps / 110 / 126", re.compile(r"\baps\b|advantix|vectis|\bix ?240|\bix-?date|\bnexia\b|\belph\b|\brevio\b|instamatic"
                                   r"|agfamatic|\bpocket|\b110\b|\b126")),
    ("compact", re.compile(
        r"\bprima\b|\bmju\b|\bmu-?\d|µ|espio|superzoom|zoom ?\d{2,3}\b(?! ?mm|-\d)|\baf ?-?\d{3}\b|\b[a-z]{0,2}35 ?af\b|\baf ?35"
        r"|\bl35\b|\btrip\b|sure ?shot|autoboy|\briva\b|\bxa ?\d?\b|contax t ?[2-5]\b|minilux|leica c ?[1-3]\b|leica mini"
        r"|\bz2x\b|big mini|yashica t ?[2-5]\b|\b(?:28|35) ?ti\b|\bgr ?1[sv]?\b|stylus|\bultra f9\b|euming|optima|vitolux"
        r"|super shot|top shot|\bis-?\d{1,3}\b|\bez-?35|reusable|wiederverwendbar|\bbv ?35|\bfex\b|halina|tronic\b"
        r"|datematic|canomati[ck]|kanomatic|discomini"
        r"|point (?:and|&|n) shoot|point-and-shoot|\bkompakt|\bcompact|compatta|with ?flash|flash integr|eingebaut\w* blitz"
        r"|\bdl-?\d{3}|\bsuper ?105\b|\befp\b|\d ?ef\b|\brf ?2\b|\bqd\b")),
    ("toy / box / disposable", re.compile(
        r"chicco|spielzeug|giocattol|jouet|\bkinder|\btoy\b|brownie|box ?kamera|box camera|tengor|\b(?:agfa|kodak|zeiss) box\b"
        r"|\bbox (?:agfa|kodak)\b|agfa-box|einweg|jetable|usa e getta|disposable|quicksnap|fun ?saver|lomograph|\blomo\b"
        r"|\blc-?a\b|holga|\bdiana\b|super color 35|ektar h35|\bm35\b|\bm38\b|pouva|la sardina")),
    ("not wanted (user)", re.compile(r"\bnikon f-?301\b|\bom-?30\b|\byashica fx-?7\b")),
    ("action camera / drone", re.compile(
        r"\bdji\b|\bosmo\b|gimbal|zenmuse|gopro|go pro|insta ?360|\bdrone|\baction ?cam")),  # not '4K': Zorki 4K
    ("movie / video / projector", re.compile(
        r"cinepresa|cinecamera|super ?-?8\b|\bsuper8|schmalfilm|camescope|camcorder|handycam|videokamera|video ?camera"
        r"|\bdoppel ?8|normal ?8|autopak|projecteur|projektor|proiettore|projector|bolex|stereofilm")),
    ("flash / meter / printer", re.compile(
        r"^\W*(?:flash|blitz|esposimetr|belichtungsmesser|posemetre|light ?meter)|flitser|cartuccia|stampante|drucker"
        r"|printer|imprimante|telescreen|\bhulle\b|sprocket|printkit")),
    ("lens", re.compile(r"^\W*(?:[a-z]+ )?(?:af[- ]?s? |sp )?(?:nikkor|zuiko|takumar|rokkor|hexanon|serenar|yashinon"
                        r"|objektiv|obiettivo|objectif|lens|lente|tamron|tokina|soligor)\b")),
    ("modern AF", re.compile(
        r"\bnikon f ?-?(?:50|55|60|65|70|75|80|90x?|100|401[sx]?|501|601m?|801s?)\b|\bf-?(?:401|501|601|801)[sx]?\b"
        r"|\b401 ?s\b|\bom-?(?:101|707|88)\b"
        r"|\bn ?\d{4}s?\b(?=.*nikon)|\bnikon n ?\d{4}|\bminolta af\b|\baf ?\d{2}-\d{2,3}|dynax|maxxum|\beos\b|\bmz ?-?\d"
        r"|\bpentax z ?-?\d|\bsf ?\d\b|autofocus|auto focus|\b\d{3,4} ?af\b")),
]
# No camera word or camera brand in the title and one of these: not a camera.
_NOT_CAMERA = re.compile(r"esposimetr|belichtungsmesser|posemetre|light ?meter|lunasix|bisix|sekonic|filtre|\bfilter"
                         r"|visore|visionneuse|viewer|faretto|lampe|\blamp|papier|paper|rouleaux|stativ|tripod|treppiede"
                         r"|crayon|mcdonald|cokin")


def junk_reason(title, vinted_brand=None):
    """Why a listing outside the list is not worth tracking ('compact', 'instant', ...), or None."""
    norm = normalize(title)
    for reason, rx in _JUNK:
        if rx.search(norm):
            # 'Objectif Ricoh 40mm + Ricoh 500 GX', 'Nikon AF Nikkor foto toestel': a camera too
            if reason == "lens" and (_CAMERA_WORDS.search(norm) or _WITH_WORDS.search(norm)):
                continue
            return reason
    if (_NOT_CAMERA.search(norm) and not _CAMERA_WORDS.search(norm)
            and not brands_in(norm) and not brands_in(vinted_brand or "")):
        return "not a camera"
    return None


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
    if description and "accessory?" not in title_flags and _NOT_SOLD_CAMERA.search(normalize(description)):
        title_flags = title_flags + ["accessory?"]  # 'Fotocamera solo a scopo dimostrativo': not for sale
    # An accessory/digital title does not get a camera model from its description
    # ('Lotto depliant e cataloghi Leica' -> description mentions an M3).
    norm_title = normalize(title)
    lens = _LENS_TITLE.search(norm_title)
    # 'Spotmaic SP mit Takumar + Revuenon': a lens after 'with' comes with the camera
    lens_title = lens and not _CAMERA_WORDS.search(norm_title) and not _WITH_WORDS.search(norm_title[:lens.start()])
    if model is None and description and not NON_LIST_SERIES.search(norm_title) and not lens_title \
            and not {"accessory?", "digital?", "compact?"} & set(title_flags):
        norm_desc = normalize(description)
        title_brands = brands_in(title)
        # A title naming a brand takes only that brand's models ('Olympus OM2000': '… wie Canon T60').
        hits = [h for h in find_models(description, extra + title_brands[:1])
                if not _COMPATIBLE_BEFORE.search(norm_desc[:h[0]])
                and (not title_brands or MODEL_INFO[h[2]]["brand"] in title_brands)]
        if hits:
            model, source = hits[0][2], "description"

    if model in DIGITAL_TWINS and DIGITAL_TWINS[model].search(normalize(f"{title} {description or ''}")):
        model, source = None, None
        title_flags = title_flags + ["digital?"] if "digital?" not in title_flags else title_flags

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
