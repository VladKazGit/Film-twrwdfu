"""Words that mark a listing as no camera, by kind and language: the 24 languages of the EU
(Vinted's sellers write in their own). Written as people spell them; models.py normalizes them
like titles (lower case, no accents, Cyrillic in Latin letters, any apostrophe) and adds them to
its rules. Each kind says where a word counts.

Started from the listings that slipped into 'Список':
  'Praktica MTL50' - 'Mode d'emploi, Notice d'utilisation, manuel' (a manual),
  'Revue Canon AL-1' - a French magazine (revue; only before another brand, see models.py),
  'Livella per fotocamera' - a spirit level, 'Fotocamera solo a scopo dimostrativo',
  'Lot 3 ouvrages anciens Leica - M3' - books (ouvrages, publications),
  'Scatola Nikon FE', 'Leica M4 scatola e istruzioni' ('Confezione originale'),
  'SOLO SCATOLA VUOTA' (Olympus OM-10), 'Boîte vide' (Nikon MF3) - empty boxes.
Words that also name camera things are left out ('magazine' is a film back too, 'manual' a
mechanical camera, 'iris' a diaphragm, Romanian 'carte' is French for a card).
"""

# A manual or instructions: an accessory, unless kit / 'with' words say the camera comes too.
# Title anywhere; a description that starts with it.
MANUAL = {
    "bg": ["ръководство", "инструкция за употреба", "упътване", "ръководства", "инструкции"],
    "cs": ["návod k obsluze", "návod", "příručka", "návody", "příručky"],
    "da": ["brugsanvisning", "betjeningsvejledning", "vejledning", "brugsanvisninger", "vejledninger"],
    "de": ["Bedienungsanleitung", "Gebrauchsanweisung", "Gebrauchsanleitung", "Betriebsanleitung", "Handbuch", "Bedienungsanleitungen", "Gebrauchsanweisungen", "Gebrauchsanleitungen", "Betriebsanleitungen", "Handbücher", "Anleitungen"],
    "el": ["εγχειρίδιο", "οδηγίες χρήσης", "εγχειρίδια"],
    "en": ["user manual", "owner's manual", "instruction manual", "instructions", "user guide", "user manuals", "instruction manuals", "owner's manuals", "user guides"],
    "es": ["manual de instrucciones", "manual de usuario", "instrucciones", "manuales de instrucciones"],
    "et": ["kasutusjuhend", "juhend", "kasutusjuhendid", "juhendid"],
    "fi": ["käyttöohje", "ohjekirja", "käyttöohjeet", "ohjekirjat"],
    "fr": ["mode d'emploi", "mode emploi", "notice d'utilisation", "manuel d'utilisation", "notice", "modes d'emploi", "notices", "manuels d'utilisation", "notices d'utilisation"],
    "ga": ["lámhleabhar", "treoracha", "lámhleabhair"],
    "hr": ["upute za uporabu", "upute", "priručnik", "priručnici"],
    "hu": ["használati útmutató", "kezelési útmutató", "kézikönyv", "útmutató", "kézikönyvek", "használati útmutatók", "útmutatók"],
    "it": ["manuale d'uso", "manuale di istruzioni", "libretto di istruzioni", "istruzioni", "libretto", "libretti", "manuali d'uso", "libretti di istruzioni"],
    "lt": ["naudojimo instrukcija", "instrukcija", "vadovas", "instrukcijos", "vadovai"],
    "lv": ["lietošanas instrukcija", "instrukcija", "rokasgrāmata", "instrukcijas", "rokasgrāmatas"],
    "mt": ["manwal", "struzzjonijiet", "manwali"],
    "nl": ["handleiding", "gebruiksaanwijzing", "handleidingen", "gebruiksaanwijzingen"],
    "pl": ["instrukcja obsługi", "instrukcja", "instrukcje", "instrukcje obsługi"],
    "pt": ["manual de instruções", "manual do utilizador", "manual do usuário", "instruções", "manuais de instruções"],
    "ro": ["manual de utilizare", "manual de instrucțiuni", "instrucțiuni de utilizare", "instrucțiuni", "manuale de utilizare"],
    "sk": ["návod na obsluhu", "návod", "príručka", "návody", "príručky"],
    "sl": ["navodila za uporabo", "navodila", "priročnik", "priročniki"],
    "sv": ["bruksanvisning", "instruktionsbok", "bruksanvisningar", "instruktionsböcker"],
}

# Printed matter - magazines, books, brochures, catalogues, posters and advertisements, framed or not
# ('Affiche publicité Canon 1966 encadrée'): an accessory unless a 'with' word comes
# before it. Title anywhere; a description that starts with it (and names no camera).
PRINT = {
    "bg": ["списание", "книга", "брошура", "каталог", "плакат", "реклама", "списания", "брошури", "каталози", "плакати", "реклами"],
    "cs": ["časopis", "kniha", "knihy", "brožura", "katalog", "prospekt", "plakát", "reklama", "časopisy", "brožury", "katalogy", "prospekty", "plakáty", "reklamy"],
    "da": ["tidsskrift", "bog", "bøger", "brochure", "katalog", "plakat", "reklame", "tidsskrifter", "brochurer", "kataloger", "plakater", "reklamer"],
    "de": ["Zeitschrift", "Buch", "Bücher", "Broschüre", "Prospekt", "Katalog", "Plakat", "Werbeplakat", "Werbung", "Reklame", "gerahmt", "Zeitschriften", "Broschüren", "Prospekte", "Kataloge", "Plakate", "Werbeplakate",
           # Kleinanzeigen: 'Leitz Arbeitsblatt Leicaflex', 'LEICA M6 und anderes Prospektmaterial'
           "Arbeitsblatt", "Datenblatt", "Faltblatt", "Merkblatt", "Werbeblatt", "Infoblatt", "Preisliste",
           "Prospektmaterial", "Werbeprospekt", "Bildband", "Fotobuch", "Fachbuch", "Arbeitsblätter",
           "Datenblätter", "Faltblätter", "Preislisten", "Werbeprospekte", "Bildbände", "Fotobücher", "Fachbücher"],
    "el": ["περιοδικό", "βιβλίο", "φυλλάδιο", "κατάλογος", "αφίσα", "διαφήμιση", "περιοδικά", "βιβλία", "φυλλάδια", "κατάλογοι", "αφίσες", "διαφημίσεις"],
    "en": ["book", "books", "brochure", "catalogue", "catalog", "publication", "advertisement", "advert", "framed print", "framed", "brochures", "catalogues", "catalogs", "publications", "advertisements", "adverts", "posters", "magazines"],
    "es": ["revista", "libro", "libros", "folleto", "catálogo", "cartel", "póster", "publicidad", "anuncio publicitario", "enmarcado", "revistas", "folletos", "catálogos", "carteles", "pósters", "anuncios"],
    "et": ["ajakiri", "raamat", "brošüür", "kataloog", "plakat", "reklaam", "ajakirjad", "raamatud", "brošüürid", "kataloogid", "plakatid", "reklaamid"],
    "fi": ["aikakauslehti", "kirja", "kirjat", "esite", "juliste", "mainos", "aikakauslehdet", "esitteet", "julisteet", "mainokset"],
    "fr": ["livre", "livres", "ouvrage", "ouvrages", "publication", "publications", "brochure", "catalogue",
           "prospectus", "affiche", "publicité", "réclame", "encadrée", "encadré", "brochures", "catalogues", "affiches", "publicités", "réclames", "magazines"],
    "ga": ["leabhar", "bróisiúr", "póstaer", "leabhair", "bróisiúir", "póstaeir"],
    "hr": ["časopis", "knjiga", "brošura", "katalog", "plakat", "reklama", "časopisi", "knjige", "brošure", "katalozi", "plakati", "reklame"],
    "hu": ["folyóirat", "könyv", "prospektus", "katalógus", "plakát", "reklám", "folyóiratok", "könyvek", "prospektusok", "katalógusok", "plakátok", "reklámok"],
    "it": ["rivista", "libro", "libri", "opuscolo", "depliant", "catalogo", "manifesto", "locandina", "pubblicità", "incorniciato", "incorniciata", "riviste", "opuscoli", "depliants", "cataloghi", "manifesti", "locandine"],
    "lt": ["žurnalas", "knyga", "brošiūra", "katalogas", "plakatas", "reklama", "žurnalai", "knygos", "brošiūros", "katalogai", "plakatai", "reklamos"],
    "lv": ["žurnāls", "grāmata", "brošūra", "katalogs", "plakāts", "reklāma", "žurnāli", "grāmatas", "brošūras", "katalogi", "plakāti", "reklāmas"],
    "mt": ["rivista", "ktieb", "fuljett", "reklam", "rivisti", "kotba", "fuljetti"],
    "nl": ["tijdschrift", "boek", "boeken", "brochure", "catalogus", "affiche", "reclame", "advertentie", "ingelijst", "tijdschriften", "brochures", "catalogi", "affiches", "advertenties"],
    "pl": ["czasopismo", "książka", "książki", "broszura", "katalog", "prospekt", "plakat", "reklama", "oprawiony", "czasopisma", "broszury", "katalogi", "prospekty", "plakaty", "reklamy"],
    "pt": ["revista", "livro", "livros", "folheto", "catálogo", "cartaz", "anúncio publicitário", "publicidade", "emoldurado", "revistas", "folhetos", "catálogos", "cartazes", "anúncios"],
    "ro": ["revistă", "broșură", "catalog", "afiș", "reclamă", "înrămat", "reviste", "broșuri", "cataloage", "afișe", "reclame", "cărți"],
    "sk": ["časopis", "kniha", "knihy", "brožúra", "katalóg", "plagát", "reklama", "časopisy", "brožúry", "katalógy", "plagáty", "reklamy"],
    "sl": ["revija", "knjiga", "brošura", "katalog", "plakat", "revije", "knjige", "brošure", "katalogi", "plakati"],
    "sv": ["tidskrift", "tidning", "bok", "böcker", "broschyr", "katalog", "affisch", "reklam", "inramad", "tidskrifter", "tidningar", "broschyrer", "kataloger", "affischer"],
}

# A box or packaging: before the model it is what is sold ('Scatola Nikon FE'); after it the
# camera comes boxed. A description that starts with it too.
BOX = {
    "bg": ["кутия", "опаковка", "кутии", "опаковки"],
    "cs": ["krabice", "krabička", "balení", "krabičky"],
    "da": ["æske", "emballage", "æsker"],
    "de": ["Schachtel", "Verpackung", "Originalverpackung", "Karton", "Originalkarton", "Schachteln", "Verpackungen", "Originalverpackungen", "Kartons"],
    "el": ["κουτί", "συσκευασία", "κουτιά"],
    "en": ["box", "packaging", "boxes"],
    "es": ["caja", "embalaje", "cajas", "embalajes"],
    "et": ["karp", "pakend", "karbid"],
    "fi": ["laatikko", "pakkaus", "rasia", "laatikot", "rasiat"],
    "fr": ["boîte", "emballage", "carton", "boîtes", "emballages", "cartons"],
    "ga": ["bosca", "boscaí"],
    "hr": ["kutija", "ambalaža", "kutije"],
    "hu": ["doboz", "csomagolás", "dobozok"],
    "it": ["scatola", "confezione", "imballo", "imballaggio", "scatole", "confezioni", "scatoline"],
    "lt": ["dėžutė", "pakuotė", "dėžutės"],
    "lv": ["kaste", "kastīte", "iepakojums", "kastes", "kastītes"],
    "mt": ["kaxxa", "kaxxi"],
    "nl": ["doos", "verpakking", "dozen", "verpakkingen"],
    "pl": ["pudełko", "pudło", "opakowanie", "pudełka", "opakowania"],
    "pt": ["caixa", "embalagem", "caixas", "embalagens"],
    "ro": ["cutie", "ambalaj", "cutii"],
    "sk": ["krabica", "krabička", "balenie", "krabice", "krabičky"],
    "sl": ["škatla", "škatlica", "embalaža", "škatle", "škatlice"],
    "sv": ["kartong", "förpackning", "kartonger", "förpackningar"],
}

# The description says the camera in the photos is not sold, or only the (empty) box is.
# Description anywhere.
NOT_SOLD = {
    "bg": ["празна кутия", "само кутия", "фотоапаратът не е включен"],
    "cs": ["prázdná krabice", "pouze krabice", "fotoaparát není součástí"],
    "da": ["tom æske", "kun æsken", "kameraet medfølger ikke"],
    "de": ["leere Schachtel", "nur die Schachtel", "nur die Verpackung", "Kamera nicht enthalten",
           "Kamera nicht im Lieferumfang"],
    "el": ["άδειο κουτί", "μόνο το κουτί", "η κάμερα δεν περιλαμβάνεται"],
    "en": ["empty box", "box only", "camera not included", "for display only"],
    "es": ["caja vacía", "solo la caja", "cámara no incluida", "solo para exhibición"],
    "et": ["tühi karp", "ainult karp", "kaamera ei kuulu komplekti"],
    "fi": ["tyhjä laatikko", "pelkkä laatikko", "kamera ei sisälly"],
    "fr": ["boîte vide", "uniquement la boîte", "appareil non inclus"],
    "ga": ["bosca folamh"],
    "hr": ["prazna kutija", "samo kutija", "fotoaparat nije uključen"],
    "hu": ["üres doboz", "csak a doboz", "a fényképezőgép nem tartozék"],
    "it": ["scatola vuota", "solo scatola", "fotocamera non inclusa", "solo a scopo dimostrativo"],
    "lt": ["tuščia dėžutė", "tik dėžutė", "fotoaparatas neįeina"],
    "lv": ["tukša kaste", "tikai kaste", "fotoaparāts nav iekļauts"],
    "mt": ["kaxxa vojta"],
    "nl": ["lege doos", "alleen de doos", "camera niet inbegrepen"],
    "pl": ["puste pudełko", "samo pudełko", "aparat nie jest w zestawie", "aparat nie wchodzi w skład"],
    "pt": ["caixa vazia", "só a caixa", "apenas a caixa", "câmera não incluída", "câmara não incluída"],
    "ro": ["cutie goală", "doar cutia", "aparatul nu este inclus"],
    "sk": ["prázdna krabica", "iba krabica", "fotoaparát nie je súčasťou"],
    "sl": ["prazna škatla", "samo škatla", "fotoaparat ni vključen"],
    "sv": ["tom kartong", "endast kartongen", "kameran ingår inte"],
}

# A spirit level for the hot shoe ('Livella per fotocamera'): an accessory word.
LEVEL = {
    "bg": ["либела", "нивелир", "либели"],
    "cs": ["vodováha", "libela", "vodováhy"],
    "da": ["vaterpas", "vaterpasse"],
    "de": ["Wasserwaage", "Libelle", "Wasserwaagen", "Libellen"],
    "el": ["αλφάδι", "αλφάδια"],
    "en": ["spirit level", "bubble level", "hot shoe level", "spirit levels", "bubble levels"],
    "es": ["nivel de burbuja", "niveles de burbuja"],
    "et": ["vesilood", "vesiloodid"],
    "fi": ["vesivaaka", "vesivaa'at"],
    "fr": ["niveau à bulle", "niveaux à bulle"],
    "ga": ["leibhéal"],
    "hr": ["libela", "vaservaga", "libele"],
    "hu": ["vízmérték", "libella", "vízmértékek"],
    "it": ["livella", "livelle"],
    "lt": ["gulsčiukas", "gulsčiukai"],
    "lv": ["līmeņrādis", "līmeņrāži"],
    "mt": ["livell"],
    "nl": ["waterpas", "waterpassen"],
    "pl": ["poziomica", "poziomnica", "poziomice"],
    "pt": ["nível de bolha", "níveis de bolha"],
    "ro": ["nivelă", "nivel cu bulă", "nivele"],
    "sk": ["vodováha", "vodováhy"],
    "sl": ["libela", "vodna tehtnica", "libele"],
    "sv": ["vattenpass", "vattenpassar"],
}

# Macro extension tubes / rings ('Canon EF extension tube bagues macro': the EF mount, not the
# camera): an accessory word. Not 'bellows' - folding cameras have them.
TUBES = {
    "bg": ["удължителни пръстени", "макро пръстени"],
    "cs": ["mezikroužky", "prodlužovací kroužky", "makro kroužky"],
    "da": ["mellemringe", "makroringe"],
    "de": ["Zwischenring", "Zwischenringe", "Makroringe", "Makro-Zwischenringe"],
    "el": ["δακτύλιοι επέκτασης", "μακρο δακτύλιοι"],
    "en": ["extension tube", "extension tubes", "extension rings", "macro tubes", "macro rings"],
    "es": ["tubo de extensión", "tubos de extensión", "anillos macro"],
    "et": ["vaheringid", "makrorõngad"],
    "fi": ["välirenkaat", "makrorenkaat"],
    "fr": ["bague allonge", "bagues allonges", "bagues allonge", "bagues macro", "bagues d'extension",
           "tubes allonge", "tubes macro"],
    "ga": ["feadáin síneadh"],
    "hr": ["međuprstenovi", "makro prstenovi"],
    "hu": ["közgyűrű", "közgyűrűk", "makrogyűrű"],
    "it": ["tubi di prolunga", "anelli di prolunga", "tubi di estensione", "anelli macro", "tubi macro"],
    "lt": ["tarpiniai žiedai", "makro žiedai"],
    "lv": ["starpgredzeni", "makro gredzeni"],
    "mt": ["tubi ta' estensjoni"],
    "nl": ["tussenring", "tussenringen", "macro ringen", "macroringen"],
    "pl": ["pierścienie pośrednie", "pierścienie makro", "tuleje makro"],
    "pt": ["tubos de extensão", "anéis macro"],
    "ro": ["inele de extensie", "tuburi de extensie", "inele macro"],
    "sk": ["medzikrúžky", "makro krúžky"],
    "sl": ["vmesni obročki", "makro obročki"],
    "sv": ["mellanringar", "makroringar"],
}

# Body parts - bottom / top plate, back door, battery door ('Piastra inferiore Olympus OM10',
# 'Sportello posteriore Olympus OM10'): a part anywhere in the title, unless a 'with' word comes
# before it or 'for' does ('… per ricambi' is a camera for parts). A description that starts with it.
PARTS = {
    "bg": ["долна плоча", "горен капак", "заден капак", "долни плочи", "капаци"],
    "cs": ["spodní kryt", "horní kryt", "zadní kryt", "zadní dvířka", "spodní kryty", "zadní kryty"],
    "da": ["bundplade", "topdæksel", "bagklap", "bagdæksel", "bundplader", "bagklapper"],
    "de": ["Bodenplatte", "Bodendeckel", "Rückwand", "Kamerarückwand", "Deckkappe", "Batteriefachdeckel", "Bodenplatten", "Rückwände", "Kamerarückwände", "Deckkappen"],
    "el": ["κάτω πλάκα", "πάνω καπάκι", "πίσω καπάκι", "κάτω πλάκες", "πίσω καπάκια"],
    "en": ["bottom plate", "base plate", "top plate", "top cover", "back door", "back cover", "rear door",
           "battery door", "bottom plates", "base plates", "top plates", "top covers", "back doors", "back covers", "rear doors", "battery doors"],
    "es": ["placa inferior", "tapa inferior", "tapa superior", "tapa trasera", "puerta trasera", "placas inferiores", "tapas inferiores", "tapas superiores", "tapas traseras", "puertas traseras"],
    "et": ["põhjaplaat", "ülakaas", "tagakaas", "põhjaplaadid", "tagakaaned"],
    "fi": ["pohjalevy", "yläkansi", "takakansi", "pohjalevyt", "takakannet"],
    "fr": ["plaque inférieure", "plaque de fond", "capot supérieur", "porte arrière", "dos du boîtier",
           "trappe à pile", "trappe", "plaques inférieures", "plaques de fond", "capots supérieurs", "portes arrière", "trappes"],
    "ga": ["clúdach cúil"],
    "hr": ["donja ploča", "gornji poklopac", "stražnji poklopac", "stražnja vrata", "donje ploče", "stražnji poklopci"],
    "hu": ["alsó fedél", "felső fedél", "hátsó fedél", "hátlap", "alsó fedelek", "hátsó fedelek", "hátlapok"],
    "it": ["piastra inferiore", "piastra", "sportello posteriore", "sportello", "dorso posteriore", "piastre inferiori", "piastre", "sportelli posteriori", "sportelli", "dorsi posteriori"],
    "lt": ["apatinė plokštė", "viršutinis dangtelis", "galinis dangtelis", "apatinės plokštės", "galiniai dangteliai"],
    "lv": ["apakšējā plāksne", "augšējais vāciņš", "aizmugurējais vāciņš", "apakšējās plāksnes", "aizmugurējie vāciņi"],
    "mt": ["għatu ta' wara"],
    "nl": ["bodemplaat", "onderplaat", "bovenkap", "achterwand", "achterklep", "bodemplaten", "onderplaten", "bovenkappen", "achterwanden", "achterkleppen"],
    "pl": ["płytka dolna", "dolna pokrywa", "górna pokrywa", "tylna pokrywa", "tylna klapka", "płytki dolne", "dolne pokrywy", "górne pokrywy", "tylne pokrywy", "tylne klapki"],
    "pt": ["placa inferior", "tampa inferior", "tampa superior", "tampa traseira", "porta traseira", "placas inferiores", "tampas inferiores", "tampas superiores", "tampas traseiras", "portas traseiras"],
    "ro": ["placa inferioară", "capac inferior", "capac superior", "capac spate", "ușa din spate", "plăci inferioare", "capace inferioare", "capace superioare", "capace spate"],
    "sk": ["spodný kryt", "horný kryt", "zadný kryt", "zadné dvierka", "spodné kryty", "zadné kryty"],
    "sl": ["spodnja plošča", "zgornji pokrov", "zadnji pokrov", "zadnja vratca", "spodnje plošče", "zadnji pokrovi"],
    "sv": ["bottenplatta", "topplock", "baklucka", "bakstycke", "bottenplattor", "bakluckor"],
}

# Replacement covering / leatherette for a body ('Contax 137 MA leather skin, self adhesive body cover'):
# a body part, as PARTS (not after a camera word, not in a set).
COVERING = {
    "bg": ["облицовка", "самозалепваща облицовка"],
    "cs": ["potah", "samolepicí potah"],
    "da": ["betræk", "selvklæbende"],
    "de": ["Belederung", "Ersatzbelederung", "Lederbezug", "selbstklebend", "selbstklebende"],
    "el": ["επένδυση", "αυτοκόλλητη επένδυση"],
    "en": ["leather skin", "leatherette", "body covering", "body cover", "self adhesive", "self-adhesive",
           "replacement leather", "replacement covering", "covering kit"],
    "es": ["revestimiento", "piel de repuesto", "autoadhesivo", "autoadhesiva"],
    "et": ["isekleepuv", "nahkkate"],
    "fi": ["päällyste", "itseliimautuva"],
    "fr": ["gainage", "similicuir", "gainage de remplacement"],
    "ga": ["clúdach leathair"],
    "hr": ["presvlaka", "samoljepljiva presvlaka"],
    "hu": ["bőrözés", "öntapadó"],
    "it": ["rivestimento", "similpelle", "pelle di ricambio", "autoadesivo", "autoadesiva"],
    "lt": ["apmušalas", "lipnus apmušalas"],
    "lv": ["pārvalks", "pašlīmējošs"],
    "mt": ["kisja tal-ġilda"],
    "nl": ["bekleding", "zelfklevend", "zelfklevende"],
    "pl": ["okleina", "samoprzylepna okleina"],
    "pt": ["revestimento", "autoadesivo"],
    "ro": ["autoadeziv", "piele de schimb"],
    "sk": ["poťah", "samolepiaci"],
    "sl": ["prevleka", "samolepilna"],
    "sv": ["klädsel", "självhäftande"],
}

# Body, lens and rear caps ('Coppia tappi Canon EF', 'Tappi fotocamera Nikon F'): an accessory word
# before the model (after it they come with the camera).
CAPS = {
    "bg": ["капачка", "капачки"],
    "cs": ["krytka", "krytky", "víčko"],
    "da": ["dæksel", "objektivdæksel", "husdæksel"],
    "de": ["Gehäusedeckel", "Objektivdeckel", "Rückdeckel", "Bajonettdeckel", "Frontdeckel"],
    "el": ["καπάκι", "καπάκια"],
    "en": ["body cap", "body caps", "lens cap", "lens caps", "rear cap", "rear caps", "front cap"],
    "es": ["tapa", "tapas", "tapa de objetivo"],
    "et": ["objektiivikork", "kerekork"],
    "fi": ["tulppa", "runkotulppa", "takatulppa", "objektiivinsuojus"],
    "fr": ["bouchon", "bouchons"],
    "ga": ["caipín"],
    "hr": ["poklopac", "poklopci"],
    "hu": ["objektívsapka", "vázsapka"],
    "it": ["tappo", "tappi", "tappino", "tappini"],
    "lt": ["dangtelis", "dangteliai"],
    "lv": ["vāciņš", "vāciņi"],
    "mt": ["għatu"],
    "nl": ["lensdop", "bodydop", "achterdop", "doppen"],
    "pl": ["dekiel", "dekielek", "dekle"],
    "pt": ["tampa", "tampas"],
    "ro": ["capac", "capace"],
    "sk": ["krytka", "viečko"],
    "sl": ["pokrovček", "pokrovčki"],
    "sv": ["linsskydd", "huslock", "baklock"],
}

# Mount adapters and adapter rings ('Anello adattatore URTH Canon EF-FD': EF to FD, not the EF
# camera; 'Adattatori Macro Canon AE-1'), also in the plural: an accessory word.
ADAPTER = {
    "bg": ["адаптер", "преходник", "адаптери", "преходници"],
    "cs": ["adaptér", "redukce", "adaptéry"],
    "da": ["adapter", "adapterring", "adaptere", "adapterringe"],
    "de": ["Adapter", "Adapterring", "Objektivadapter", "Bajonettadapter", "Adapterringe", "Objektivadaptern"],
    "el": ["αντάπτορας", "προσαρμογέας", "αντάπτορες", "προσαρμογείς"],
    "en": ["adapter", "adaptor", "mount adapter", "adapter ring", "lens adapter", "adapters", "adaptors", "adapter rings", "lens adapters", "mount adapters"],
    "es": ["adaptador", "anillo adaptador", "adaptadores", "anillos adaptadores"],
    "et": ["adapter", "adapterid"],
    "fi": ["adapteri", "sovitin", "adapterit", "sovittimet"],
    "fr": ["adaptateur", "bague d'adaptation", "bague adaptatrice", "adaptateurs", "bagues d'adaptation", "bagues adaptatrices"],
    "ga": ["cuibheoir", "cuibheoirí"],
    "hr": ["adapter", "prilagodnik", "adapteri"],
    "hu": ["adapter", "átalakító", "adapterek"],
    "it": ["adattatore", "anello adattatore", "adattatori", "anelli adattatori"],
    "lt": ["adapteris", "adapteriai"],
    "lv": ["adapteris", "adapteri"],
    "mt": ["adapter", "adapters"],
    "nl": ["adapter", "adapterring", "verloopring", "adapters", "verloopringen"],
    "pl": ["adapter", "przejściówka", "redukcja", "adaptery", "przejściówki"],
    "pt": ["adaptador", "anel adaptador", "adaptadores", "anéis adaptadores"],
    "ro": ["adaptor", "inel adaptor", "adaptoare", "adaptori"],
    "sk": ["adaptér", "redukcia", "adaptéry"],
    "sl": ["adapter", "prilagojevalnik", "adapterji"],
    "sv": ["adapter", "adapterring", "adaptrar", "adapterringar"],
}

# Made for a camera ('Livella per fotocamera'): in a title without a model and without a camera
# word before it, the thing is for a camera, not one.
FOR_CAMERA = {
    "bg": ["за фотоапарат", "за камера", "за фотоапарати"],
    "cs": ["pro fotoaparát", "k fotoaparátu", "na fotoaparát", "pro fotoaparáty", "k fotoaparátům"],
    "da": ["til kamera", "til kameraet", "til kameraer"],
    "de": ["für Kamera", "für die Kamera", "für Fotoapparat", "für Kameras", "für Fotoapparate"],
    "el": ["για φωτογραφική μηχανή", "για κάμερα", "για φωτογραφικές μηχανές", "για κάμερες"],
    "en": ["for camera", "for the camera", "for cameras"],
    "es": ["para cámara", "para la cámara", "para cámaras"],
    "et": ["kaamerale", "fotoaparaadile", "kaameratele"],
    "fi": ["kameraan", "kameralle", "kameroille", "kameroihin"],
    "fr": ["pour appareil photo", "pour appareil", "pour appareils photo", "pour appareils"],
    "ga": ["le haghaidh ceamara"],
    "hr": ["za fotoaparat", "za kameru", "za fotoaparate"],
    "hu": ["fényképezőgéphez", "kamerához", "fényképezőgépekhez"],
    "it": ["per fotocamera", "per macchina fotografica", "per fotocamere", "per macchine fotografiche"],
    "lt": ["fotoaparatui", "fotoaparatams"],
    "lv": ["fotoaparātam", "fotoaparātiem"],
    "mt": ["għall-kamera"],
    "nl": ["voor camera", "voor fototoestel", "voor camera's", "voor fototoestellen"],
    "pl": ["do aparatu", "do aparatu fotograficznego", "do aparatów", "do aparatów fotograficznych"],
    "pt": ["para câmera", "para câmara", "para máquina fotográfica", "para câmeras", "para câmaras", "para máquinas fotográficas"],
    "ro": ["pentru aparat foto", "pentru aparatul foto", "pentru cameră", "pentru aparate foto"],
    "sk": ["pre fotoaparát", "k fotoaparátu", "na fotoaparát", "pre fotoaparáty"],
    "sl": ["za fotoaparat", "za fotoaparate"],
    "sv": ["för kamera", "för kameran", "till kamera", "för kameror", "till kameror"],
}

# 'With' words: what follows comes with the camera ('Praktica MTL 5 com manual' is a camera with
# its manual). They keep a listing a camera; the de/en/fr/it/nl/es ones are in models.py. Left
# out: words that are also model or mount letters - Slavic 'z' / 's' / 'с', Spanish 'y'
# ('Mamiya M645 … finder S … manual'), Latvian 'ar' (Konica Hexanon AR), Polish 'ze' (Mamiya ZE-X),
# Lithuanian 'ir' (IR filters) - and 'se' / 'su' / 'sa' (Spanish 'se vende', Italian 'on').
WITH = {
    "da": ["med"], "el": ["με"], "et": ["koos"], "fi": ["kanssa"], "pl": ["wraz z"], "pt": ["com"],
    "ro": ["cu"], "sv": ["med"],
}

# Each kind lists the singular and the plural ('Scatole Nikon FE', 'Manuali Canon AE-1').
KINDS = {  # name (Russian, for people) -> words by language
    "инструкция": MANUAL, "журнал / книга / каталог": PRINT, "коробка": BOX,
    "камера не продаётся / пустая коробка": NOT_SOLD, "уровень": LEVEL, "макрокольца / удлинительные трубки": TUBES,
    "запчасти корпуса": PARTS, "обтяжка корпуса": COVERING, "крышки": CAPS, "адаптер": ADAPTER, "«для камеры»": FOR_CAMERA,
}
