"""Lens recognition in titles. Run: python -m tests.test_lenses"""
from tracker import lenses

CASES = [
    # title, model, kind
    ("Helios 44-2 58mm f/2 M42", "Helios-44-2", "lens"),
    ("Гелиос-44М-4 2/58", "Helios-44M-4", "lens"),
    ("МС Гелиос-44М-6", "MC Helios-44M-6", "lens"),
    ("MC Helios 44M-6 58mm f2 Zebra", "MC Helios-44M-6", "lens"),
    ("Helios 44 2/58 silver 13 blades", "Helios-44", "lens"),
    ("Helios-44M 58mm", "Helios-44M", "lens"),
    ("Helios 44K-4 Pentax K", "Helios-44K-4", "lens"),
    ("Helios 40-2 85mm f/1.5", "Helios-40-2", "lens"),
    ("Helios-81N Nikon", "Helios-81N", "lens"),
    ("Гелиос-81-Автомат Киев", "Helios-81 Avtomat", "lens"),
    ("Super-Takumar 1:1.4/50 M42", "Super-Takumar 50mm f/1.4", "lens"),
    ("Asahi Super Takumar 50mm F1.4", "Super-Takumar 50mm f/1.4", "lens"),
    ("Super-Takumar 55mm f/1.8", None, None),
    ("Super takumar 1.4 (8 elementi)", "Super-Takumar 50mm f/1.4", "lens"),
    ("Canon FD 1.4", None, "unclear"),
    ("SMC Takumar 1:1.8/55", "SMC Takumar 55mm f/1.8", "lens"),
    ("Super-Multi-Coated Takumar 135mm 3.5", "SMC Takumar 135mm f/3.5", "lens"),
    ("Jupiter-8 2/50 M39", "Jupiter-8 50mm f/2", "lens"),
    ("Юпитер-8 50мм", "Jupiter-8 50mm f/2", "lens"),
    ("Jupiter 8M Kiev", "Jupiter-8M 50mm f/2", "lens"),
    ("Canon FD 50mm 1:1.4 S.S.C.", "Canon FD 50mm f/1.4 (SSC / nFD)", "lens"),
    ("Canon nFD 50mm f1.4", "Canon FD 50mm f/1.4 (SSC / nFD)", "lens"),
    ("Canon FD 50mm 1.8", "Canon FD 50mm f/1.8", "lens"),
    ("Nikkor 50mm 1:1.4 AI-S", "Nikkor 50mm f/1.4 (Pre-AI / AI / AI-S)", "lens"),
    ("Nikon AF Nikkor 50mm f/1.4D", None, None),
    ("Olympus OM Zuiko 50mm f1.8", "Zuiko 50mm f/1.8", "lens"),
    ("Olympus M.Zuiko 45mm f/1.8", None, None),
    ("Zuiko 1.8/50", "Zuiko 50mm f/1.8", "lens"),
    ("Pentacon auto 2.8/29", "Pentacon 29mm f/2.8", "lens"),
    ("Pentacon prakticar 50mm 1.8", "Pentacon Prakticar 50mm f/1.8", "lens"),
    ("Carl Zeiss Planar 50mm f/1.7 T* C/Y", "Carl Zeiss Planar 50mm f/1.7 T* (C/Y)", "lens"),
    ("Rollei HFT Planar 1.8/50 QBM", "Rollei-HFT Planar 50mm f/1.8", "lens"),
    ("SMC Pentax-M 1:1.7 50mm", "SMC Pentax-M 50mm f/1.7", "lens"),
    ("Minolta MD 50mm 1.7", "Minolta MD 50mm f/1.7", "lens"),
    ("Konica Hexanon AR 40mm 1.8", "Konica Hexanon AR 40mm f/1.8", "lens"),
    ("Orestor 135mm f/2.8", "Orestor 135mm", "lens"),
    # every Canon FD lens, named by maker, focal length and aperture; '135/F3.5'
    ("Vivitar 28mm f/2.8 Canon FD", "Vivitar 28mm f/2.8 (Canon FD)", "lens"),
    ("Tokina 70-210mm f/4-5.6 FD", "Tokina 70-210mm f/4-5.6 (Canon FD)", "lens"),
    ("Objektiv Canon FD 135mm 1:3.5", "Canon FD 135mm f/3.5", "lens"),
    ("Obiettivo Konica 135/F3.5 Hexanon AR", "Konica Hexanon AR 135mm f/3.5", "lens"),
    # a word of the list without details: 'Без деталей'
    ("Obiettivo helios", None, "unclear"),
    ("Tokina Objektive", None, "unclear"),
    ("Helios 44-4M Zenit", None, "unclear"),
    ("Helios lens with a Sony E-mount adapter", None, "unclear"),
    # a camera with the lens: the camera tracker's
    ("Zenit E + Helios 44-2 58mm", "Helios-44-2", "kit"),
    ("Canon AE-1 Program mit FD 50mm 1.4", "Canon FD 50mm f/1.4 (SSC / nFD)", "kit"),
    ("Super Takumar 50mm 1.4 für Pentax Spotmatic", "Super-Takumar 50mm f/1.4", "lens"),
    ("Helios 44-2 avec Zenit E", "Helios-44-2", "kit"),
    # things for the lens
    ("Adapter M42 Sony E für Helios 44-2", "Helios-44-2", "accessory"),
    ("Gegenlichtblende für Jupiter-8", "Jupiter-8 50mm f/2", "accessory"),
    ("Helios 44-2 mit Adapter Sony E", "Helios-44-2", "lens"),
    # adapters without a lens of the list: the adapter word first, or with no 'with' / lens word before it
    ("Urth FD-E Adapter – Canon FD to Sony E – Brand New", None, "accessory"),
    ("Adaptateur K&F Concept Canon FD vers Micro 4/3", None, "accessory"),
    ("Adattatori Olympus sony minolta", None, "accessory"),
    ("Canon FD/FL Lens adapter - Canon EOS EF Camera", None, "accessory"),
    ("Tamron Adaptall-2 Adapter for Minolta SRT - Japan", None, "accessory"),
    ("Pentacon Praktica M42 naar Praktica B (PB) lensadapter", None, "accessory"),
    ("Tokina lens minolta adaptor", None, "unclear"),
    ("Obiettivo canon fd 24mm vintage f 2.8 con adattatore", "Canon FD 24mm f/2.8", "lens"),
    # a zoom range with '~' is not a focal length of the list
    ("Tokina AT-X 16~28mm F2.8 PRO FX", None, None),
    # hoods, caps, cases, filters, manuals without a lens of the list: wherever the word stands
    ("Minolta D57KB pare soleil metal", None, "accessory"),
    ("Mode emploi tamron adaptall-2", None, "accessory"),
    ("Canon FD Libretto Obiettivi Vintage '80", None, "accessory"),
    ("Vivitar lens case lot van 3 fotografie", None, "accessory"),
    ("Set original Canon FD  Camera Body Cap + Rear lens cap", None, "accessory"),
]


def main():
    bad = 0
    for title, model, kind in CASES:
        got = lenses.classify(title)
        if (got["model"], got["kind"]) != (model, kind):
            bad += 1
            print(f"FAIL: {title!r}: expected {model} / {kind}, got {got['model']} / {got['kind']}")
    assert "parts?" in lenses.classify("Helios 44-2 defekt, für Teile")["flags"]
    assert lenses.classify("Obiettivo helios", "Helios 44M-4 58mm in ottime condizioni")["model"] == "Helios-44M-4"
    # The description names another lens of the maker: out; a focal length of the list, a filter size, the
    # film, an f-number - still unclear; a Helios of another variant stays unclear.
    kind = lambda title, description: lenses.classify(title, description)["kind"]
    assert kind("Objectif Tamron", "Tamron AF 70-300mm f/4-5.6 Di LD Macro, parfait état") == "other"
    assert kind("Obiettivo per reflex Soligor", "Lunghezza focale: 200mm - apertura massima 3.5") == "other"
    assert lenses.classify("Objectif Tamron", "Tamron 28mm f/2.5 Adaptall 2")["model"] == "Tamron 28mm f/2.5 Adaptall"
    assert kind("Super Albinar", "Super Albinar MC Auto 1:28 28mm 58 diametre") == "unclear", "a typo's aperture"
    assert kind("Tamron Objektiv", "Filtergewinde 52mm, guter Zustand") == "unclear"
    assert kind("Obiettivo Vivitar", "Teleobiettivo Vivitar 52mm") == "unclear", "52mm: a filter size"
    assert kind("Vivitar lens", "Blende f/3.5 bis f/22, für 35mm Kameras") == "unclear"
    assert kind("Obiettivo helios", "Helios 44-4M 58mm") == "unclear"
    assert kind("Tamron Adaptall-2 per attacco Contax Yashica", "Guarda il mio profilo. Tamron Adaptall-2 adattatore") \
        == "accessory"
    assert kind("Tamron Adaptall-2 pour Canon FD", "Je vends une monture/adaptateur Tamron Adaptall-2") == "accessory"
    assert kind("Obiettivo Tokina", "Obiettivo Tokina vintage, meccanico, con adattatore per canon") == "unclear"
    assert kind("Rare Carl Zeiss Jena Pancolar", "Lens with Thorium. Use with adapter only") == "unclear"
    # The description says it is a thing for the lens: out, even with a model in the title; a thing that
    # comes with the lens stays.
    assert kind("Canon FD 35-70mm f4 AF", "Custodia per obiettivo Canon FD 35-70mm f/4 AF") == "accessory"
    assert kind("Elmarit R 2.8 28mm", "Paraluce per Elmarit R 2.8 28mm Leitz Wetzlar Germany") == "accessory"
    assert kind("Bague extension macro Minolta Rokkor 50mm", "Bague tube adaptateur macro pour Minolta Rokkor") \
        == "accessory"
    assert kind("Obiettivo 50mm FD", "Compreso paraluce") == "lens"
    assert kind("Helios 44-2 58mm f/2", "Adapter für Sony E inklusive. Schönes Objektiv") == "lens"
    assert kind("Super Takumar 50mm 1.4", "Deckel vorne und hinten vorhanden") == "lens"
    assert kind("Objektiv 50 mm SMC Pentax-M 1:1,7", "Ohne Deckel") == "lens"
    assert kind("Objectif canon FD 1.8/50 mm", "Avec sa boîte d'origine") == "lens"
    assert lenses.classify("Helios 44-2 M42 mit Adapter Sony E")["mount"] == "M42"
    assert lenses.classify("Vivitar 200mm f/3.5 Canon FD")["mount"] == "Canon FD", "the title's mount, not the model's"
    assert len(lenses.model_names()) > 60 and "Helios-44-2" in lenses.model_names()
    print(f"{len(CASES) - bad}/{len(CASES)} passed")
    assert not bad


if __name__ == "__main__":
    main()
