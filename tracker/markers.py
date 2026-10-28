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
    "bg": ["ръководство", "инструкция за употреба", "упътване"],
    "cs": ["návod k obsluze", "návod", "příručka"],
    "da": ["brugsanvisning", "betjeningsvejledning", "vejledning"],
    "de": ["Bedienungsanleitung", "Gebrauchsanweisung", "Gebrauchsanleitung", "Betriebsanleitung", "Handbuch"],
    "el": ["εγχειρίδιο", "οδηγίες χρήσης"],
    "en": ["user manual", "owner's manual", "instruction manual", "instructions", "user guide"],
    "es": ["manual de instrucciones", "manual de usuario", "instrucciones"],
    "et": ["kasutusjuhend", "juhend"],
    "fi": ["käyttöohje", "ohjekirja"],
    "fr": ["mode d'emploi", "mode emploi", "notice d'utilisation", "manuel d'utilisation", "notice"],
    "ga": ["lámhleabhar", "treoracha"],
    "hr": ["upute za uporabu", "upute", "priručnik"],
    "hu": ["használati útmutató", "kezelési útmutató", "kézikönyv", "útmutató"],
    "it": ["manuale d'uso", "manuale di istruzioni", "libretto di istruzioni", "istruzioni", "libretto"],
    "lt": ["naudojimo instrukcija", "instrukcija", "vadovas"],
    "lv": ["lietošanas instrukcija", "instrukcija", "rokasgrāmata"],
    "mt": ["manwal", "struzzjonijiet"],
    "nl": ["handleiding", "gebruiksaanwijzing"],
    "pl": ["instrukcja obsługi", "instrukcja"],
    "pt": ["manual de instruções", "manual do utilizador", "manual do usuário", "instruções"],
    "ro": ["manual de utilizare", "manual de instrucțiuni", "instrucțiuni de utilizare", "instrucțiuni"],
    "sk": ["návod na obsluhu", "návod", "príručka"],
    "sl": ["navodila za uporabo", "navodila", "priročnik"],
    "sv": ["bruksanvisning", "instruktionsbok"],
}

# Printed matter - magazines, books, brochures, catalogues, posters and advertisements, framed or not
# ('Affiche publicité Canon 1966 encadrée'): an accessory unless a 'with' word comes
# before it. Title anywhere; a description that starts with it (and names no camera).
PRINT = {
    "bg": ["списание", "книга", "брошура", "каталог", "плакат", "реклама"],
    "cs": ["časopis", "kniha", "knihy", "brožura", "katalog", "prospekt", "plakát", "reklama"],
    "da": ["tidsskrift", "bog", "bøger", "brochure", "katalog", "plakat", "reklame"],
    "de": ["Zeitschrift", "Buch", "Bücher", "Broschüre", "Prospekt", "Katalog", "Plakat", "Werbeplakat", "Werbung", "Reklame", "gerahmt"],
    "el": ["περιοδικό", "βιβλίο", "φυλλάδιο", "κατάλογος", "αφίσα", "διαφήμιση"],
    "en": ["book", "books", "brochure", "catalogue", "catalog", "publication", "advertisement", "advert", "framed print", "framed"],
    "es": ["revista", "libro", "libros", "folleto", "catálogo", "cartel", "póster", "publicidad", "anuncio publicitario", "enmarcado"],
    "et": ["ajakiri", "raamat", "brošüür", "kataloog", "plakat", "reklaam"],
    "fi": ["aikakauslehti", "kirja", "kirjat", "esite", "juliste", "mainos"],
    "fr": ["livre", "livres", "ouvrage", "ouvrages", "publication", "publications", "brochure", "catalogue",
           "prospectus", "affiche", "publicité", "réclame", "encadrée", "encadré"],
    "ga": ["leabhar", "bróisiúr", "póstaer"],
    "hr": ["časopis", "knjiga", "brošura", "katalog", "plakat", "reklama"],
    "hu": ["folyóirat", "könyv", "prospektus", "katalógus", "plakát", "reklám"],
    "it": ["rivista", "libro", "libri", "opuscolo", "depliant", "catalogo", "manifesto", "locandina", "pubblicità", "incorniciato", "incorniciata"],
    "lt": ["žurnalas", "knyga", "brošiūra", "katalogas", "plakatas", "reklama"],
    "lv": ["žurnāls", "grāmata", "brošūra", "katalogs", "plakāts", "reklāma"],
    "mt": ["rivista", "ktieb", "fuljett", "reklam"],
    "nl": ["tijdschrift", "boek", "boeken", "brochure", "catalogus", "affiche", "reclame", "advertentie", "ingelijst"],
    "pl": ["czasopismo", "książka", "książki", "broszura", "katalog", "prospekt", "plakat", "reklama", "oprawiony"],
    "pt": ["revista", "livro", "livros", "folheto", "catálogo", "cartaz", "anúncio publicitário", "publicidade", "emoldurado"],
    "ro": ["revistă", "broșură", "catalog", "afiș", "reclamă", "înrămat"],
    "sk": ["časopis", "kniha", "knihy", "brožúra", "katalóg", "plagát", "reklama"],
    "sl": ["revija", "knjiga", "brošura", "katalog", "plakat"],
    "sv": ["tidskrift", "tidning", "bok", "böcker", "broschyr", "katalog", "affisch", "reklam", "inramad"],
}

# A box or packaging: before the model it is what is sold ('Scatola Nikon FE'); after it the
# camera comes boxed. A description that starts with it too.
BOX = {
    "bg": ["кутия", "опаковка"],
    "cs": ["krabice", "krabička", "balení"],
    "da": ["æske", "emballage"],
    "de": ["Schachtel", "Verpackung", "Originalverpackung", "Karton", "Originalkarton"],
    "el": ["κουτί", "συσκευασία"],
    "en": ["box", "packaging"],
    "es": ["caja", "embalaje"],
    "et": ["karp", "pakend"],
    "fi": ["laatikko", "pakkaus", "rasia"],
    "fr": ["boîte", "emballage", "carton"],
    "ga": ["bosca"],
    "hr": ["kutija", "ambalaža"],
    "hu": ["doboz", "csomagolás"],
    "it": ["scatola", "confezione", "imballo", "imballaggio"],
    "lt": ["dėžutė", "pakuotė"],
    "lv": ["kaste", "kastīte", "iepakojums"],
    "mt": ["kaxxa"],
    "nl": ["doos", "verpakking"],
    "pl": ["pudełko", "pudło", "opakowanie"],
    "pt": ["caixa", "embalagem"],
    "ro": ["cutie", "ambalaj"],
    "sk": ["krabica", "krabička", "balenie"],
    "sl": ["škatla", "škatlica", "embalaža"],
    "sv": ["kartong", "förpackning"],
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
    "bg": ["либела", "нивелир"],
    "cs": ["vodováha", "libela"],
    "da": ["vaterpas"],
    "de": ["Wasserwaage", "Libelle"],
    "el": ["αλφάδι"],
    "en": ["spirit level", "bubble level", "hot shoe level"],
    "es": ["nivel de burbuja"],
    "et": ["vesilood"],
    "fi": ["vesivaaka"],
    "fr": ["niveau à bulle"],
    "ga": ["leibhéal"],
    "hr": ["libela", "vaservaga"],
    "hu": ["vízmérték", "libella"],
    "it": ["livella"],
    "lt": ["gulsčiukas"],
    "lv": ["līmeņrādis"],
    "mt": ["livell"],
    "nl": ["waterpas"],
    "pl": ["poziomica", "poziomnica"],
    "pt": ["nível de bolha"],
    "ro": ["nivelă", "nivel cu bulă"],
    "sk": ["vodováha"],
    "sl": ["libela", "vodna tehtnica"],
    "sv": ["vattenpass"],
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
    "bg": ["долна плоча", "горен капак", "заден капак"],
    "cs": ["spodní kryt", "horní kryt", "zadní kryt", "zadní dvířka"],
    "da": ["bundplade", "topdæksel", "bagklap", "bagdæksel"],
    "de": ["Bodenplatte", "Bodendeckel", "Rückwand", "Kamerarückwand", "Deckkappe", "Batteriefachdeckel"],
    "el": ["κάτω πλάκα", "πάνω καπάκι", "πίσω καπάκι"],
    "en": ["bottom plate", "base plate", "top plate", "top cover", "back door", "back cover", "rear door",
           "battery door"],
    "es": ["placa inferior", "tapa inferior", "tapa superior", "tapa trasera", "puerta trasera"],
    "et": ["põhjaplaat", "ülakaas", "tagakaas"],
    "fi": ["pohjalevy", "yläkansi", "takakansi"],
    "fr": ["plaque inférieure", "plaque de fond", "capot supérieur", "porte arrière", "dos du boîtier",
           "trappe à pile", "trappe"],
    "ga": ["clúdach cúil"],
    "hr": ["donja ploča", "gornji poklopac", "stražnji poklopac", "stražnja vrata"],
    "hu": ["alsó fedél", "felső fedél", "hátsó fedél", "hátlap"],
    "it": ["piastra inferiore", "piastra", "sportello posteriore", "sportello", "dorso posteriore"],
    "lt": ["apatinė plokštė", "viršutinis dangtelis", "galinis dangtelis"],
    "lv": ["apakšējā plāksne", "augšējais vāciņš", "aizmugurējais vāciņš"],
    "mt": ["għatu ta' wara"],
    "nl": ["bodemplaat", "onderplaat", "bovenkap", "achterwand", "achterklep"],
    "pl": ["płytka dolna", "dolna pokrywa", "górna pokrywa", "tylna pokrywa", "tylna klapka"],
    "pt": ["placa inferior", "tampa inferior", "tampa superior", "tampa traseira", "porta traseira"],
    "ro": ["placa inferioară", "capac inferior", "capac superior", "capac spate", "ușa din spate"],
    "sk": ["spodný kryt", "horný kryt", "zadný kryt", "zadné dvierka"],
    "sl": ["spodnja plošča", "zgornji pokrov", "zadnji pokrov", "zadnja vratca"],
    "sv": ["bottenplatta", "topplock", "baklucka", "bakstycke"],
}

# Mount adapters and adapter rings ('Anello adattatore URTH Canon EF-FD': EF to FD, not the EF
# camera): an accessory word.
ADAPTER = {
    "bg": ["адаптер", "преходник"],
    "cs": ["adaptér", "redukce"],
    "da": ["adapter", "adapterring"],
    "de": ["Adapter", "Adapterring", "Objektivadapter", "Bajonettadapter"],
    "el": ["αντάπτορας", "προσαρμογέας"],
    "en": ["adapter", "adaptor", "mount adapter", "adapter ring", "lens adapter"],
    "es": ["adaptador", "anillo adaptador"],
    "et": ["adapter"],
    "fi": ["adapteri", "sovitin"],
    "fr": ["adaptateur", "bague d'adaptation", "bague adaptatrice"],
    "ga": ["cuibheoir"],
    "hr": ["adapter", "prilagodnik"],
    "hu": ["adapter", "átalakító"],
    "it": ["adattatore", "anello adattatore"],
    "lt": ["adapteris"],
    "lv": ["adapteris"],
    "mt": ["adapter"],
    "nl": ["adapter", "adapterring", "verloopring"],
    "pl": ["adapter", "przejściówka", "redukcja"],
    "pt": ["adaptador", "anel adaptador"],
    "ro": ["adaptor", "inel adaptor"],
    "sk": ["adaptér", "redukcia"],
    "sl": ["adapter", "prilagojevalnik"],
    "sv": ["adapter", "adapterring"],
}

# Made for a camera ('Livella per fotocamera'): in a title without a model and without a camera
# word before it, the thing is for a camera, not one.
FOR_CAMERA = {
    "bg": ["за фотоапарат", "за камера"],
    "cs": ["pro fotoaparát", "k fotoaparátu", "na fotoaparát"],
    "da": ["til kamera", "til kameraet"],
    "de": ["für Kamera", "für die Kamera", "für Fotoapparat"],
    "el": ["για φωτογραφική μηχανή", "για κάμερα"],
    "en": ["for camera", "for the camera"],
    "es": ["para cámara", "para la cámara"],
    "et": ["kaamerale", "fotoaparaadile"],
    "fi": ["kameraan", "kameralle"],
    "fr": ["pour appareil photo", "pour appareil"],
    "ga": ["le haghaidh ceamara"],
    "hr": ["za fotoaparat", "za kameru"],
    "hu": ["fényképezőgéphez", "kamerához"],
    "it": ["per fotocamera", "per macchina fotografica"],
    "lt": ["fotoaparatui"],
    "lv": ["fotoaparātam"],
    "mt": ["għall-kamera"],
    "nl": ["voor camera", "voor fototoestel"],
    "pl": ["do aparatu", "do aparatu fotograficznego"],
    "pt": ["para câmera", "para câmara", "para máquina fotográfica"],
    "ro": ["pentru aparat foto", "pentru aparatul foto", "pentru cameră"],
    "sk": ["pre fotoaparát", "k fotoaparátu", "na fotoaparát"],
    "sl": ["za fotoaparat"],
    "sv": ["för kamera", "för kameran", "till kamera"],
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

KINDS = {  # name (Russian, for people) -> words by language
    "инструкция": MANUAL, "журнал / книга / каталог": PRINT, "коробка": BOX,
    "камера не продаётся / пустая коробка": NOT_SOLD, "уровень": LEVEL, "макрокольца / удлинительные трубки": TUBES,
    "запчасти корпуса": PARTS, "адаптер": ADAPTER, "«для камеры»": FOR_CAMERA,
}
