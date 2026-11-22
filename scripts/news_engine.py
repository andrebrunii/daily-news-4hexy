#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meridiano 20:00 — Osservatorio Mondiale Live, Impatto Italia/UE & Top 10 Giornaliera (CET)
==========================================================================================
Funzionamento del ciclo di 24 ore (Europe/Rome) con motore Anti-Skip e Anti-Duplicati:
- Ore 00:00 -> 19:00 CET (Diretta della giornata odierna in prima pagina):
    * Superata la mezzanotte (00:00 CET), il `README.md` principale passa subito alla giornata odierna
      (includendo anche le ricerche preparatorie raccolte tra le 21:00 e le 23:00 della sera precedente).
    * Ogni ora raccoglie e pubblica in `README.md` le nuove notizie fino a quel momento.
    * Filtra rigorosamente i duplicati: una notizia già pubblicata NON viene ripetuta, salvo reali
      aggiornamenti/sviluppi sulla situazione rispetto alla prima segnalazione (marcati come 🔄 AGGIORNAMENTO).
- Ore 20:00 CET (Pubblicazione Top 10 Giornaliera & Chiusura Edizione):
    * Seleziona la TOP 10 delle notizie più rilevanti del ciclo (Posizioni #1–#5 Italia/UE/Geopolitica,
      Posizioni #6–#10 Rotazione IA/Tech, Economia, Scienza, Filosofia).
    * Pubblica l'edizione definitiva di oggi in `README.md` e la salva in `archivio/YYYY-MM-DD.md` (max 7 giorni).
    * L'edizione di oggi SMETTE di aggiornarsi alle 20:00 e resta visibile in `README.md` fino alle 23:59.
- Ore 21:00 -> 23:00 CET (Nuovo ciclo silenzioso per domani):
    * Parte il nuovo ciclo orario per il giorno successivo in background (`data/current_cycle.json` e `IN_CORSO.md`).
    * NON modifica `README.md` fino allo scattare della mezzanotte (`00:00 CET`), quando il nuovo giorno diventa visibile in prima pagina.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

try:
    import feedparser  # type: ignore
except ImportError:
    feedparser = None

try:
    import requests  # type: ignore
except ImportError:
    requests = None

try:
    ROME_TZ: dt.tzinfo = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = dt.timezone(dt.timedelta(hours=1), name="CET")
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ARCHIVE_DIR = ROOT_DIR / "archivio"
README_PATH = ROOT_DIR / "README.md"
LIVE_PATH = ROOT_DIR / "IN_CORSO.md"
CYCLE_JSON_PATH = DATA_DIR / "current_cycle.json"
SEEN_JSON_PATH = DATA_DIR / "seen_urls.json"

MAX_ARCHIVE_DAYS = 7
ITEMS_PER_HOUR = 4

# ---------------------------------------------------------------------------
# Catalogo Fonti RSS (Mondiali, Europee, Italiane, Tech, Scienza, Filosofia)
# ---------------------------------------------------------------------------
RSS_SOURCES: List[Dict[str, Any]] = [
    # --- CORE: GEOPOLITICA MONDIALE & IMPATTO ITALIA / EUROPA ---
    {
        "id": "ansa_mondo",
        "name": "ANSA Mondo",
        "url": "https://www.ansa.it/sito/notizie/mondo/mondo_rss.xml",
        "category": "geopolitica_ue",
        "badge": "🌍 Geopolitica & Mondo",
        "lang": "it",
        "is_core": True,
        "weight": 1.35,
    },
    {
        "id": "politico_eu",
        "name": "Politico Europe",
        "url": "https://www.politico.eu/feed/",
        "category": "geopolitica_ue",
        "badge": "🇪🇺 Unione Europea & Policy",
        "lang": "en",
        "is_core": True,
        "weight": 1.45,
    },
    {
        "id": "ilpost",
        "name": "Il Post",
        "url": "https://www.ilpost.it/feed/",
        "category": "geopolitica_ue",
        "badge": "🇮🇹 Italia & Esteri",
        "lang": "it",
        "is_core": True,
        "weight": 1.30,
    },
    {
        "id": "bbc_world",
        "name": "BBC World News",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "category": "geopolitica_ue",
        "badge": "🌐 Scacchiere Globale",
        "lang": "en",
        "is_core": True,
        "weight": 1.40,
    },
    {
        "id": "guardian_world",
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "category": "geopolitica_ue",
        "badge": "🌍 Esteri & Analisi",
        "lang": "en",
        "is_core": True,
        "weight": 1.30,
    },
    {
        "id": "euronews_it",
        "name": "Euronews Italia",
        "url": "https://it.euronews.com/rss",
        "category": "geopolitica_ue",
        "badge": "🇪🇺 Cronaca Europea",
        "lang": "it",
        "is_core": True,
        "weight": 1.35,
    },
    # --- ROTAZIONE 1: ECONOMIA, ENERGIA, MERCATI & MACRO ITALIA/UE ---
    {
        "id": "sole24ore_econ",
        "name": "Il Sole 24 Ore",
        "url": "https://www.ilsole24ore.com/rss/economia.xml",
        "category": "economia",
        "badge": "📈 Economia & Mercati",
        "lang": "it",
        "is_core": True,
        "weight": 1.30,
    },
    {
        "id": "ansa_economia",
        "name": "ANSA Economia",
        "url": "https://www.ansa.it/sito/notizie/economia/economia_rss.xml",
        "category": "economia",
        "badge": "💶 Macro & Finanza UE",
        "lang": "it",
        "is_core": False,
        "weight": 1.20,
    },
    {
        "id": "cnbc_world",
        "name": "CNBC Global Economy",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
        "category": "economia",
        "badge": "🏦 Mercati Globali",
        "lang": "en",
        "is_core": False,
        "weight": 1.20,
    },
    # --- ROTAZIONE 2: IA, TECNOLOGIA, CYBER & FUTURO DIGITALE ---
    {
        "id": "techmeme",
        "name": "Techmeme",
        "url": "https://www.techmeme.com/feed.xml",
        "category": "tech_ia",
        "badge": "🤖 IA & Frontiera Tech",
        "lang": "en",
        "is_core": False,
        "weight": 1.30,
    },
    {
        "id": "arstechnica",
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "category": "tech_ia",
        "badge": "💻 Tecnologia & Cyber",
        "lang": "en",
        "is_core": False,
        "weight": 1.20,
    },
    {
        "id": "mit_tech",
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "category": "tech_ia",
        "badge": "⚡ Futuro & Deep Tech",
        "lang": "en",
        "is_core": False,
        "weight": 1.25,
    },
    # --- ROTAZIONE 3: SCIENZA, SPAZIO, CLIMA & BIOLOGIA ---
    {
        "id": "nature",
        "name": "Nature Research",
        "url": "https://www.nature.com/nature.rss",
        "category": "scienza",
        "badge": "🧬 Scienza & Scoperte",
        "lang": "en",
        "is_core": False,
        "weight": 1.25,
    },
    {
        "id": "sciencedaily",
        "name": "ScienceDaily",
        "url": "https://www.sciencedaily.com/rss/top.xml",
        "category": "scienza",
        "badge": "🔭 Ricerca & Spazio",
        "lang": "en",
        "is_core": False,
        "weight": 1.15,
    },
    # --- ROTAZIONE 4: FILOSOFIA, PENSIERO A LUNGO TERMINE & SOCIETÀ ---
    {
        "id": "aeon",
        "name": "Aeon Philosophy & Ideas",
        "url": "https://aeon.co/feed.rss",
        "category": "filosofia",
        "badge": "🏛️ Filosofia & Idee",
        "lang": "en",
        "is_core": False,
        "weight": 1.30,
    },
    {
        "id": "bigthink",
        "name": "Big Think",
        "url": "https://bigthink.com/feed/",
        "category": "filosofia",
        "badge": "🧠 Paradigmi & Lunghi Orizzonti",
        "lang": "en",
        "is_core": False,
        "weight": 1.20,
    },
]

# Parole chiave ad alto impatto (verificate con word-boundary \b per evitare falsi positivi su parole corte)
HIGH_IMPACT_KEYWORDS_EU_IT = [
    "italia", "italy", "roma", "rome", "meloni", "mattarella", "giorgetti", "governo",
    "europa", "europe", "eu", "ue", "bruxelles", "brussels", "bce", "ecb",
    "commissione europea", "eurozona", "pil", "inflazione", "dazi", "tariffs",
    "energia", "gas", "petrolio", "mediterraneo", "nato", "ucraina", "ukraine",
    "russia", "medio oriente", "medioriente", "cina", "china", "usa", "stati uniti", "trump",
    "difesa", "debito", "pnrr", "industria", "manifattura", "automotive",
    "intelligenza artificiale", "ai act", "semiconduttori", "chip", "sciopero",
    "clima", "transizione", "demografia", "migranti", "sicurezza", "cyber", "banche", "fisco",
]

GLOBAL_PARADIGM_KEYWORDS = [
    "quantum", "quantistico", "agi", "llm", "gemini", "openai", "anthropic", "nvidia",
    "fusion", "fusione", "crispr", "longevity", "longevità", "space", "spazio",
    "mars", "moon", "philosophy", "filosofia", "consciousness", "coscienza",
    "ethics", "etica", "democracy", "democrazia", "algorithm", "algoritmo",
    "brain", "cervello", "neuro", "climate", "antropocene", "biotech", "robot",
]


def has_keyword(text: str, kw: str) -> bool:
    """Verifica la presenza di una keyword con confini di parola (\b) per evitare match errati (es. 'ia' in 'italia')."""
    return bool(re.search(rf"\b{re.escape(kw.lower())}\b", text.lower()))


def has_any_keyword(text: str, keywords: List[str]) -> bool:
    lower_t = text.lower()
    return any(bool(re.search(rf"\b{re.escape(k.lower())}\b", lower_t)) for k in keywords)


# ---------------------------------------------------------------------------
# Utilità di Pulizia Testo e Traduzione Automatica Keyless (EN -> IT)
# ---------------------------------------------------------------------------
def strip_html(raw_text: str) -> str:
    if not raw_text:
        return ""
    text = html.unescape(raw_text)
    text = re.sub(r"<script.*?>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


_TRANSLATE_CACHE: Dict[str, str] = {}


def translate_to_italian(text: str, source_lang: str = "en") -> str:
    """
    Traduce automaticamente dall'inglese all'italiano usando gli endpoint pubblici
    gratuiti di Google Translate con fallback automatico e retry anti-rate-limit.
    """
    if not text or source_lang == "it":
        return text
    clean = text.strip()
    if len(clean) < 4:
        return clean
    if clean in _TRANSLATE_CACHE:
        return _TRANSLATE_CACHE[clean]

    snippet = clean[:900]
    q_enc = urllib.parse.quote(snippet)
    sl_enc = urllib.parse.quote(source_lang)

    urls = [
        f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl_enc}&tl=it&dt=t&q={q_enc}",
        f"https://clients5.google.com/translate_a/single?client=at&sl={sl_enc}&tl=it&dt=t&q={q_enc}",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    for attempt, url in enumerate(urls):
        try:
            if attempt > 0:
                time.sleep(0.35)
            if requests is not None:
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and data and isinstance(data[0], list):
                        translated = "".join(part[0] for part in data[0] if part and part[0])
                        if translated:
                            res = translated.strip()
                            _TRANSLATE_CACHE[clean] = res
                            return res
            else:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    if isinstance(data, list) and data and isinstance(data[0], list):
                        translated = "".join(part[0] for part in data[0] if part and part[0])
                        if translated:
                            res = translated.strip()
                            _TRANSLATE_CACHE[clean] = res
                            return res
        except Exception:
            continue
    return clean


# ---------------------------------------------------------------------------
# Motore Editoriale: Analisi Impatto Italia/UE, Lungo Termine & Filosofia
# ---------------------------------------------------------------------------
def generate_editorial_analysis(
    title_it: str,
    summary_it: str,
    category: str,
    source_name: str,
) -> Dict[str, str]:
    """
    Genera tre livelli di lettura per ogni notizia:
    1. Impatto su Italia / Europa (CET)
    2. Prospettiva Strategica a Lungo Termine (5-20 anni)
    3. Riflessione Filosofica & Sistemica
    """
    combined = f"{title_it} {summary_it}".lower()
    seed = int(hashlib.md5(combined.encode("utf-8")).hexdigest()[:8], 16)

    # 1. Analisi Impatto Italia / UE (usando word-boundaries per precisione tematica)
    if has_any_keyword(combined, ["bce", "inflazione", "tassi", "debito", "spread", "pil", "banca", "banche", "fisco", "tasse", "bilancio", "manovra", "mercati", "borsa"]):
        impacts = [
            "Riflesso diretto sul costo del credito nell'Eurozona e sui margini di manovra della finanza pubblica italiana, con effetti a catena su mutui, investimenti industriali e tenuta del potere d'acquisto domestico.",
            "Per l'Italia e il tessuto produttivo europeo, ogni variazione negli equilibri monetari, bancari e fiscali ridefinisce la sostenibilità del debito e la capacità delle PMI di finanziare innovazione e lavoro.",
            "Impatto immediato sui mercati regolamentati europei (Piazza Affari, Francoforte, Parigi): la trasmissione della politica economica e fiscale costringe Roma e Bruxelles a ricalibrare le priorità di crescita.",
        ]
    elif has_any_keyword(combined, ["dazi", "cina", "usa", "trump", "commercio", "export", "manifattura", "auto", "automotive", "supply chain", "congresso"]):
        impacts = [
            "L'Italia, seconda manifattura d'Europa e fortemente orientata all'export, è esposta in prima linea a ogni attrito commerciale tra blocchi: dazi o colli di bottiglia logistici toccano direttamente meccanica, moda, agroalimentare e componentistica.",
            "Bruxelles si trova stretta tra assertività americana e sovracapacità asiatica; per il sistema industriale del Nord e Centro Italia significa dover accorciare le filiere e cercare nuovi sbocchi ad alto valore aggiunto.",
            "Riconfigurazione delle catene del valore euro-mediterranee: ciò che appare come uno scontro geoeconomico lontano si traduce in costi di approvvigionamento e nuove barriere normative per gli esportatori italiani.",
        ]
    elif has_any_keyword(combined, ["energia", "gas", "petrolio", "nucleare", "rinnovabili", "clima", "cop", "cop31", "elettricità", "bollette", "emissioni"]):
        impacts = [
            "Il differenziale del costo dell'energia resta il tallone d'Achille della competitività italiana ed europea: ogni scossa sugli approvvigionamenti o sulle tecnologie energetiche incide direttamente sulle bollette e sulla tenuta delle imprese energivore.",
            "Rafforza la centralità strategica dell'Italia come hub energetico del Mediterraneo (Piano Mattei e interconnessioni Sud-Nord verso il cuore dell'Europa), accelerando il dibattito sul mix tra rinnovabili, stoccaggi e nuovo nucleare.",
            "Impatto strutturale sui target del Green Deal europeo: la sfida per Roma e Bruxelles è coniugare decarbonizzazione e sicurezza energetica senza sacrificare la base industriale continentale.",
        ]
    elif has_any_keyword(combined, ["ucraina", "russia", "mosca", "zelensky", "nato", "difesa", "esercito", "medio oriente", "medioriente", "israele", "iran", "guerra", "armi", "droni", "sicurezza", "mediterraneo"]):
        impacts = [
            "Ridefinisce l'architettura di sicurezza del fianco Est e del Mediterraneo Allargato: per l'Italia e l'UE comporta scelte inevitabili su spesa per la difesa comune, tutela delle rotte marittime (Mar Rosso/Suez) e stabilità dei confini esterni.",
            "Aumenta la pressione politica sulle capitali europee affinché passino da una dipendenza strategica a una reale capacità di deterrenza e diplomazia autonoma, con ricadute dirette sugli impegni internazionali di Roma.",
            "Ogni instabilità lungo l'arco di crisi euro-mediterraneo si riflette immediatamente sui flussi energetici, commerciali e diplomatici gestiti in prima battuta dall'Italia come frontiera meridionale d'Europa.",
        ]
    elif category == "tech_ia" or has_any_keyword(combined, ["ai", "ia", "intelligenza artificiale", "gemini", "openai", "anthropic", "nvidia", "chip", "semiconduttori", "cyber", "algoritmo", "algoritmi", "cloud", "data center"]):
        impacts = [
            "Mentre USA e Cina guidano la corsa alle infrastrutture di calcolo, l'Europa (con l'AI Act e il GDPR) gioca la partita della governance e dell'adozione industriale: per le aziende italiane la sfida è integrare questi strumenti per colmare il divario di produttività.",
            "Pone una questione cruciale di sovranità digitale europea: dipendere da piattaforme, chip e modelli extra-UE trasforma una novità tecnologica in un fattore geopolitico che tocca pubblica amministrazione, lavoro cognitivo e sicurezza nazionale.",
            "Accelerazione nell'automazione dei servizi e della manifattura avanzata in Europa: in un Paese ad alto invecchiamento demografico come l'Italia, l'innovazione digitale può diventare un moltiplicatore vitale se accompagnata da formazione reale.",
        ]
    elif category == "scienza" or has_any_keyword(combined, ["ricerca", "proteina", "cervello", "medicina", "biologia", "spazio", "scienza", "studio", "laboratorio"]):
        impacts = [
            "Anche senza un impatto normativo immediato, i salti scientifici ridisegnano le priorità di ricerca europee (Horizon Europe), la sanità pubblica e le filiere biotech e aerospaziali in cui l'Italia vanta eccellenze di primo piano.",
            "Sposta la frontiera tecnologica su cui si misurerà la competitività europea nei prossimi dieci anni, chiamando università, centri di ricerca e poli industriali italiani a non restare semplici utilizzatori finali.",
            "Offre nuovi strumenti conoscitivi per affrontare sfide sistemiche europee — dalla longevità demografica alla resilienza sanitaria e climatica del bacino mediterraneo.",
        ]
    else:
        impacts = [
            "Pur non avendo un impatto normativo istantaneo su Roma o Bruxelles, agisce come indicatore anticipatore dei mutamenti culturali, sociali e istituzionali che attraversano le democrazie occidentali ed europee.",
            "Costringe l'opinione pubblica e i decisori europei a guardare oltre l'emergenza quotidiana, interrogandosi sulla tenuta del modello sociale europeo di fronte a trasformazioni globali silenziose ma profonde.",
            "Riflette tensioni civili, sociali e culturali che, per osmosi storica ed economica, raggiungono rapidamente il dibattito pubblico italiano ed europeo.",
        ]

    # 2. Prospettiva a Lungo Termine & Lente Filosofica
    if category == "tech_ia" or has_any_keyword(combined, ["ai", "ia", "intelligenza artificiale", "algoritmo", "algoritmi", "robot", "nvidia", "chip", "cloud", "data center"]):
        long_terms = [
            "**Orizzonte 5-15 anni:** Progressiva esternalizzazione dei processi decisionali e cognitivi verso infrastrutture sintetiche; il vantaggio competitivo si sposterà dal *saper fare* al *saper porre le domande giuste* e verificare la realtà.\n"
            "> 🧠 **Lente Filosofica:** Come analizza Luciano Floridi nell'*Infosfera*, non abitiamo più il mondo usando la tecnologia, ma abitiamo dentro l'informazione stessa. Quando la macchina genera risposte infinite a costo zero, il vero bene scarso diventa l'attenzione umana non frammentata e il discernimento critico.",
            "**Orizzonte 5-15 anni:** Riconfigurazione della divisione tra lavoro umano e calcolo automatico, con la nascita di nuove asimmetrie geopolitiche tra chi possiede l'infrastruttura dei semiconduttori e chi la affitta.\n"
            "> 🧠 **Lente Filosofica:** Da Prometeo al *Golem*, ogni protesi tecnica amplifica il potere d'azione ma riduce la frizione dell'esperienza. Come ammoniva Hans Jonas con il *Principio Responsabilità*, quando la nostra potenza tecnologica supera la nostra capacità di prevederne gli effetti ultimi, la prudenza cessa di essere debolezza e diventa la prima virtù politica.",
            "**Orizzonte 5-15 anni:** Ibridazione strutturale tra intelligenza biologica e silicio; le istituzioni nate nell'era della carta stampata dovranno reinventare i concetti di autorialità, verità probatoria e responsabilità giuridica.\n"
            "> 🧠 **Lente Filosofica:** Byung-Chul Han osserva che la società dell'iper-comunicazione non soffre di carenza di dati, ma di un eccesso di *rumore* che anestetizza il senso. Recuperare la profondità del tempo lento significa rifiutare il riflesso condizionato dello scrolling per tornare a comprendere le cause.",
        ]
    elif category == "scienza" or has_any_keyword(combined, ["proteina", "cervello", "invecchiamento", "biologia", "fisica", "spazio", "natura", "genetica"]):
        long_terms = [
            "**Orizzonte 10-20 anni:** Ciò che oggi nasce nei laboratori come scoperta sperimentale diventerà infrastruttura invisibile della medicina e dell'industria di domani, ridefinendo i limiti biologici ed energetici della specie.\n"
            "> 🧠 **Lente Filosofica:** Karl Popper ricordava che la scienza avanza per congetture e confutazioni, mai per dogmi definitivi. Ogni scoperta che allarga il cerchio della luce ingrandisce contemporaneamente il perimetro dell'ignoto con cui l'umanità deve fare i conti.",
            "**Orizzonte 10-20 anni:** Transizione da una comprensione descrittiva della natura a una capacità progettuale sulla materia vivente e sui processi cognitivi, con profondi interrogativi bioetici e distributivi.\n"
            "> 🧠 **Lente Filosofica:** Nella tensione tra *hybris* ed episteme, la conoscenza scientifica ci ricorda il paradosso cosmico: siamo una minuscola frazione di materia dell'universo diventata improvvisamente capace di studiare e riscrivere le proprie stesse leggi.",
        ]
    elif category == "economia" or has_any_keyword(combined, ["inflazione", "banche", "fisco", "gas", "energia", "mercati", "borsa", "pil", "sciopero", "lavoro"]):
        long_terms = [
            "**Orizzonte 5-10 anni:** Passaggio definitivo dall'era dell'efficienza *just-in-time* (globalizzazione piatta a costo minimo) all'era della resilienza *just-in-case* (blocchi regionali, sicurezza energetica e capitalismo strategico).\n"
            "> 🧠 **Lente Filosofica:** Come spiega Nassim Nicholas Taleb in *Antifragile*, i sistemi iper-ottimizzati che eliminano ogni ridondanza in nome del profitto trimestrale diventano segretamente fragili ai Cigni Neri. La vera solidità economica non consiste nel prevedere le tempeste, ma nel costruire strutture che si rafforzano attraversandole.",
            "**Orizzonte 5-10 anni:** Tensione strutturale tra dinamiche demografiche in contrazione nel mondo sviluppato, debito pubblico storico e necessità di finanziare contemporaneamente welfare, salari, difesa e transizione tecnologica.\n"
            "> 🧠 **Lente Filosofica:** Il denaro e i mercati non sono fatti fisici ma *finzioni intersoggettive* basate sulla fiducia nel futuro (Yuval Noah Harari). Quando i mercati o le piazze tremano, non stanno solo discutendo di cifre: stanno rinegoziando il patto di fiducia tra generazioni.",
        ]
    elif category == "filosofia":
        long_terms = [
            "**Orizzonte generazionale:** Le trasformazioni più radicali della storia non iniziano nei parlamenti o nelle borse, ma nel cambio silenzioso delle categorie mentali con cui una civiltà interpreta ciò che è normale, giusto o desiderabile.\n"
            "> 🧠 **Lente Filosofica:** Come scriveva Seneca, *«nessun vento è favorevole per il marinaio che non sa a quale porto vuol approdare»*. In un'epoca ossessionata dall'accelerazione dei mezzi, fermarsi a interrogare i fini è l'atto più sovversivo e necessario.",
            "**Orizzonte generazionale:** Erosione dei vecchi confini tra sfera pubblica e solitudine privata, con la necessità di fondare una nuova ecologia dell'attenzione, dell'educazione e del senso civico.\n"
            "> 🧠 **Lente Filosofica:** Hannah Arendt distingueva tra il semplice *lavorare per sopravvivere* e l'*agire* nello spazio pubblico insieme agli altri. Comprendere le correnti profonde del pensiero contemporaneo serve a non ridursi a ingranaggi passivi del presente.",
        ]
    else:
        long_terms = [
            "**Orizzonte 5-15 anni:** Progressiva transizione verso un mondo multipolare competitivo, in cui le regole del secondo dopoguerra vengono rinegoziate attraverso rapporti di forza energetici, tecnologici e demografici.\n"
            "> 🧠 **Lente Filosofica:** Niccolò Machiavelli ricordava che la *Fortuna* (il caso, gli choc storici) governa metà delle azioni umane, ma lascia l'altra metà alla *Virtù* — cioè alla capacità di preparare argini prima che il fiume esondi. Leggere i segnali geopolitici oggi significa costruire quegli argini.",
            "**Orizzonte 5-15 anni:** Ridefinizione degli equilibri tra sovranità nazionale, coesione sociale interna e interdipendenza globale; i Paesi che sapranno mantenere istituzioni solide e visione strategica guideranno il prossimo ciclo storico.\n"
            "> 🧠 **Lente Filosofica:** La storia raramente procede in linea retta: alterna decenni in cui non accade nulla a settimane in cui accadono decenni. Osservare la cronaca con sguardo filosofico permette di distinguere l'increspatura superficiale dell'onda dalla marea profonda.",
        ]

    impact_text = impacts[seed % len(impacts)]
    long_term_text = long_terms[seed % len(long_terms)]

    return {
        "impact_eu_it": impact_text,
        "long_term_philosophy": long_term_text,
    }


def score_article(item: Dict[str, Any]) -> float:
    """
    Calcola un punteggio di rilevanza per il ranking della Top 10:
    combina il peso della fonte, la presenza di keyword ad alto impatto Italia/UE (con word boundaries)
    e la rilevanza sistemica/globale.
    """
    base = float(item.get("source_weight", 1.0)) * 10.0
    text = f"{item.get('title_it', '')} {item.get('summary_it', '')} {item.get('title_orig', '')}".lower()

    eu_it_hits = sum(1 for kw in HIGH_IMPACT_KEYWORDS_EU_IT if has_keyword(text, kw))
    paradigm_hits = sum(1 for kw in GLOBAL_PARADIGM_KEYWORDS if has_keyword(text, kw))

    score = base + (eu_it_hits * 3.5) + (paradigm_hits * 2.5)

    summary_len = len(item.get("summary_it", ""))
    if summary_len > 140:
        score += 2.0
    elif summary_len < 40:
        score -= 1.5

    return round(score, 2)


# ---------------------------------------------------------------------------
# Raccolta e Parsing RSS con Fallback Nativo XML
# ---------------------------------------------------------------------------
def parse_rss_xml_fallback(xml_bytes: bytes) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return entries

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if title and link:
            entries.append({"title": title, "link": link, "summary": desc, "published": pub})

    if entries:
        return entries

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        link_el = entry.find("atom:link", ns)
        link = link_el.attrib.get("href", "").strip() if link_el is not None else ""
        desc = (
            entry.findtext("atom:summary", default="", namespaces=ns)
            or entry.findtext("atom:content", default="", namespaces=ns)
            or ""
        ).strip()
        pub = (
            entry.findtext("atom:updated", default="", namespaces=ns)
            or entry.findtext("atom:published", default="", namespaces=ns)
            or ""
        ).strip()
        if title and link:
            entries.append({"title": title, "link": link, "summary": desc, "published": pub})

    return entries


def fetch_source_entries(source: Dict[str, Any], max_items: int = 10) -> List[Dict[str, Any]]:
    url = source["url"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Meridiano2000Radar/3.0"
    }
    raw_bytes: Optional[bytes] = None
    try:
        if requests is not None:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                raw_bytes = resp.content
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                raw_bytes = response.read()
    except Exception:
        return []

    if not raw_bytes:
        return []

    parsed_items: List[Dict[str, str]] = []
    if feedparser is not None:
        try:
            feed = feedparser.parse(raw_bytes)
            for e in feed.entries[:max_items]:
                title = getattr(e, "title", "") or ""
                link = getattr(e, "link", "") or ""
                summary = getattr(e, "summary", "") or getattr(e, "description", "") or ""
                published = getattr(e, "published", "") or getattr(e, "updated", "") or ""
                if title and link:
                    parsed_items.append(
                        {
                            "title": title,
                            "link": link,
                            "summary": summary,
                            "published": published,
                        }
                    )
        except Exception:
            parsed_items = []

    if not parsed_items:
        parsed_items = parse_rss_xml_fallback(raw_bytes)[:max_items]

    results: List[Dict[str, Any]] = []
    for raw in parsed_items:
        clean_title = strip_html(raw["title"])
        clean_summary = strip_html(raw["summary"])
        if len(clean_summary) > 360:
            clean_summary = clean_summary[:357].rsplit(" ", 1)[0] + "..."
        if not clean_summary or clean_summary.lower() == clean_title.lower():
            clean_summary = "Approfondimento disponibile nella fonte originale collegata."

        results.append(
            {
                "title_orig": clean_title,
                "summary_orig": clean_summary,
                "link": raw["link"].strip(),
                "published": raw["published"],
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "badge": source["badge"],
                "lang": source["lang"],
                "is_core": source["is_core"],
                "source_weight": source["weight"],
            }
        )
    return results


def enrich_item(item: Dict[str, Any]) -> Dict[str, Any]:
    lang = item.get("lang", "it")
    orig_title = item.get("title_orig", "")
    orig_summary = item.get("summary_orig", "")
    existing_title_it = item.get("title_it", "")
    existing_summary_it = item.get("summary_it", "")

    if not existing_title_it or (lang != "it" and existing_title_it.strip() == orig_title.strip()):
        title_it = translate_to_italian(orig_title, lang)
    else:
        title_it = existing_title_it

    if not existing_summary_it or (lang != "it" and existing_summary_it.strip() == orig_summary.strip()):
        summary_it = translate_to_italian(orig_summary, lang)
    else:
        summary_it = existing_summary_it

    item["title_it"] = title_it
    item["summary_it"] = summary_it

    analysis = generate_editorial_analysis(
        title_it=title_it,
        summary_it=summary_it,
        category=item["category"],
        source_name=item["source_name"],
    )
    item["impact_eu_it"] = analysis["impact_eu_it"]
    item["long_term_philosophy"] = analysis["long_term_philosophy"]
    item["score"] = score_article(item)
    return item


# ---------------------------------------------------------------------------
# Gestione Stato, Deduplicazione Semantica, Rilevazione Aggiornamenti & Archivio
# ---------------------------------------------------------------------------
DEDUP_STOPWORDS = {
    # Italiano (incluse parole brevi 3 lettere)
    "che", "con", "per", "tra", "fra", "del", "nel", "sul", "dal", "gli", "una",
    "uno", "non", "più", "piu", "chi", "cui", "suo", "sua", "suoi", "sue", "loro",
    "dei", "dai", "nei", "sui", "all", "ema", "era", "così", "cosi", "poi", "già", "gia",
    "della", "delle", "degli", "dello", "nella", "nelle", "negli", "nello",
    "sulla", "sulle", "sugli", "sullo", "dalla", "dalle", "dagli", "dallo",
    "alla", "alle", "agli", "allo", "sono", "stato", "stata", "stati", "state",
    "essere", "avere", "hanno", "abbiamo", "aveva", "avevano", "sarà", "saranno",
    "come", "dopo", "prima", "anche", "solo", "tutti", "tutte", "tutto", "ogni",
    "questo", "questa", "questi", "queste", "quello", "quella", "quelli", "quelle",
    "quale", "quali", "quanto", "quanti", "perché", "perche", "mentre", "contro",
    "verso", "senza", "oltre", "entro", "sopra", "sotto", "ancora", "sempre",
    "molto", "molti", "poco", "pochi", "altro", "altra", "altri", "altre",
    "fatto", "dice", "dicono", "afferma", "secondo", "nuovo", "nuova", "nuovi",
    "nuove", "oggi", "ieri", "domani", "anno", "anni", "giorno", "giorni",
    "ora", "ore", "volta", "volte", "caso", "casi", "parte", "parti", "stesso",
    "stessa", "proprio", "propria", "può", "possono", "deve", "devono",
    "approfondimento", "disponibile", "fonte", "originale", "collegata",
    # Inglese (incluse parole brevi 3 lettere)
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "her", "was",
    "one", "our", "out", "day", "get", "has", "him", "his", "how", "its", "may",
    "new", "now", "old", "see", "two", "way", "who", "did", "let", "put", "say",
    "she", "too", "use", "off", "yet", "why", "via",
    "that", "this", "with", "from", "have", "had", "were", "been",
    "being", "will", "would", "could", "should", "about", "into", "over",
    "after", "before", "under", "between", "through", "during", "while",
    "where", "when", "what", "which", "whom", "whose", "their", "them",
    "they", "there", "these", "those", "more", "most", "some", "such", "than",
    "then", "only", "also", "just", "very", "much", "many", "other", "another",
    "says", "said", "told", "tells", "report", "reports", "reported", "news",
    "amid", "onto", "back", "still", "even", "make", "makes",
    "made", "take", "takes", "took", "year", "years", "today", "week", "month",
    "first", "last", "next", "time", "might", "must",
}

UPDATE_SIGNAL_KEYWORDS = {
    # Italiano
    "aggiornamento", "aggiornamenti", "svolta", "bilancio", "salgono", "sale",
    "scende", "aumenta", "aumentano", "replica", "risponde", "risposta",
    "conferma", "confermato", "confermata", "smentisce", "smentita", "accordo",
    "intesa", "rottura", "fallisce", "dimissioni", "dimette", "arresto",
    "arrestato", "arrestati", "sentenza", "condanna", "assolto", "approva",
    "approvato", "approvata", "boccia", "bocciato", "voto", "tregua",
    "cessate", "attacco", "attacchi", "raid", "feriti", "morti", "vittime",
    "evacuazione", "allerta", "sospeso", "sospesa", "riapre", "riprende",
    "annuncia", "annunciato", "rilancia", "ritira", "rinvia", "rinviato",
    "ultimora", "nuovi", "nuove", "nuovo", "nuova", "ulteriore", "ulteriori",
    "reazione", "reazioni", "contromossa", "ritorsione", "sanzioni",
    # Inglese
    "update", "updated", "updates", "latest", "breaking", "developments",
    "responds", "response", "confirms", "confirmed", "denies", "denied",
    "reaches", "deal", "agreement", "collapses", "resigns", "resignation",
    "arrested", "verdict", "approves", "approved", "rejects", "rejected",
    "ceasefire", "truce", "toll", "rises", "drops", "surges", "strikes",
    "retaliates", "retaliation", "evacuation", "resumes", "suspends",
    "announces", "announced", "delays", "postpones", "following", "escalates",
    "escalation", "withdraws", "sanctions", "reopens", "killed", "wounded",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_url(url: str) -> str:
    clean = (url or "").split("?")[0].split("#")[0].strip().lower()
    return clean.rstrip("/")


def normalize_url_key(url: str, title: str) -> str:
    clean_u = normalize_url(url)
    clean_t = re.sub(r"\W+", "", (title or "").lower())[:60]
    return hashlib.sha1(f"{clean_u}|{clean_t}".encode("utf-8")).hexdigest()[:16]


def content_fingerprint(title: str, summary: str) -> str:
    norm = re.sub(r"\s+", " ", f"{title or ''}|{summary or ''}".strip().lower())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def extract_tokens(text: str) -> List[str]:
    raw_words = re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", (text or "").lower())
    return sorted({w for w in raw_words if w not in DEDUP_STOPWORDS})


def _extract_item_token_sets(item: Dict[str, Any]) -> Tuple[set, set]:
    title_text = f"{item.get('title_orig', '')} {item.get('title_it', '')}"
    all_text = (
        f"{item.get('title_orig', '')} {item.get('summary_orig', '')} "
        f"{item.get('title_it', '')} {item.get('summary_it', '')}"
    )
    return set(extract_tokens(title_text)), set(extract_tokens(all_text))


def _hours_since_iso(iso_str: Optional[str], slot_dt: dt.datetime) -> float:
    if not iso_str:
        return 999.0
    try:
        prev_dt = dt.datetime.fromisoformat(iso_str)
        if prev_dt.tzinfo is None:
            prev_dt = prev_dt.replace(tzinfo=ROME_TZ)
        return (slot_dt - prev_dt).total_seconds() / 3600.0
    except Exception:
        return 999.0


def build_story_record(item: Dict[str, Any], slot_dt: dt.datetime) -> Dict[str, Any]:
    title_tokens, all_tokens = _extract_item_token_sets(item)
    return {
        "key": normalize_url_key(item.get("link", ""), item.get("title_orig", "")),
        "url_norm": normalize_url(item.get("link", "")),
        "date": slot_dt.strftime("%Y-%m-%d"),
        "published_at": slot_dt.strftime("%Y-%m-%d %H:00 CET"),
        "published_iso": slot_dt.strftime("%Y-%m-%dT%H:00:00"),
        "title_orig": item.get("title_orig", ""),
        "title_it": item.get("title_it", item.get("title_orig", "")),
        "content_hash": content_fingerprint(item.get("title_orig", ""), item.get("summary_orig", "")),
        "title_tokens": sorted(title_tokens),
        "all_tokens": sorted(all_tokens),
        "update_count": int(item.get("update_count", 0)),
    }


def load_seen_state(now_rome: dt.datetime, cycle_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Carica lo stato delle notizie già pubblicate negli ultimi 7 giorni.
    Compatibile automaticamente con il vecchio formato piatto `{hash: "YYYY-MM-DD"}`.
    """
    raw = load_json(SEEN_JSON_PATH, {})
    cutoff = (now_rome - dt.timedelta(days=MAX_ARCHIVE_DAYS)).strftime("%Y-%m-%d")

    keys: Dict[str, str] = {}
    stories: List[Dict[str, Any]] = []

    if isinstance(raw, dict) and ("keys" in raw or "stories" in raw):
        raw_keys = raw.get("keys", {})
        if isinstance(raw_keys, dict):
            keys = {k: str(v) for k, v in raw_keys.items() if str(v) >= cutoff}
        raw_stories = raw.get("stories", [])
        if isinstance(raw_stories, list):
            stories = [s for s in raw_stories if isinstance(s, dict) and str(s.get("date", "")) >= cutoff]
    elif isinstance(raw, dict):
        # Migrazione trasparente dal vecchio formato
        keys = {k: str(v) for k, v in raw.items() if str(v) >= cutoff}

    # Indicizza anche eventuali notizie già presenti nei batch di oggi (utile alla prima migrazione)
    if isinstance(cycle_data, dict):
        existing_keys = {s.get("key") for s in stories}
        existing_urls = {s.get("url_norm") for s in stories if s.get("url_norm")}
        for batch in cycle_data.get("hourly_batches", []):
            ts_str = batch.get("timestamp_str", "")
            m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}):\d{2}", ts_str)
            if m:
                try:
                    b_dt = dt.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:00:00").replace(tzinfo=ROME_TZ)
                except Exception:
                    b_dt = now_rome
            else:
                b_dt = now_rome
            for it in batch.get("items", []):
                rec = build_story_record(it, b_dt)
                if rec["key"] not in existing_keys and rec["url_norm"] not in existing_urls:
                    stories.append(rec)
                    existing_keys.add(rec["key"])
                    if rec["url_norm"]:
                        existing_urls.add(rec["url_norm"])
                keys[rec["key"]] = rec["date"]

    return {"keys": keys, "stories": stories}


def are_same_story_tokens(
    cand_title_tokens: set,
    cand_all_tokens: set,
    prev_title_tokens: set,
    prev_all_tokens: set,
) -> bool:
    if not cand_title_tokens or not prev_title_tokens:
        return False
    shared_title = cand_title_tokens & prev_title_tokens
    min_title = max(1, min(len(cand_title_tokens), len(prev_title_tokens)))
    overlap_title = len(shared_title) / min_title
    jaccard_title = len(shared_title) / max(1, len(cand_title_tokens | prev_title_tokens))

    if len(shared_title) >= 3 and (overlap_title >= 0.50 or jaccard_title >= 0.35):
        return True

    shared_all = cand_all_tokens & prev_all_tokens
    min_all = max(1, min(len(cand_all_tokens), len(prev_all_tokens)))
    overlap_all = len(shared_all) / min_all
    jaccard_all = len(shared_all) / max(1, len(cand_all_tokens | prev_all_tokens))
    if len(shared_all) >= 6 and (jaccard_all >= 0.35 or (len(shared_title) >= 2 and overlap_all >= 0.45)):
        return True

    return False


def classify_candidate(
    cand: Dict[str, Any],
    seen_state: Dict[str, Any],
    slot_dt: dt.datetime,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Classifica una notizia candidata rispetto a quelle già pubblicate:
    - "new": notizia mai pubblicata prima.
    - "update": notizia già trattata ma con aggiornamenti/sviluppi concreti rispetto alla prima pubblicazione.
    - "duplicate": notizia già pubblicata (stesso URL o stesso evento) senza nuovi sviluppi reali -> scartare.
    """
    cand_key = normalize_url_key(cand.get("link", ""), cand.get("title_orig", ""))
    cand_url = normalize_url(cand.get("link", ""))
    cand_hash = content_fingerprint(cand.get("title_orig", ""), cand.get("summary_orig", ""))
    cand_title_tokens, cand_all_tokens = _extract_item_token_sets(cand)

    stories: List[Dict[str, Any]] = seen_state.get("stories", [])
    keys: Dict[str, str] = seen_state.get("keys", {})

    # 1. Controllo stesso URL o stessa chiave normalizzata
    for story in stories:
        if (cand_url and story.get("url_norm") == cand_url) or story.get("key") == cand_key:
            if story.get("content_hash") == cand_hash:
                return "duplicate", story
            elapsed_h = _hours_since_iso(story.get("published_iso"), slot_dt)
            prev_all = set(story.get("all_tokens", []))
            new_tokens = cand_all_tokens - prev_all
            jaccard = len(cand_all_tokens & prev_all) / max(1, len(cand_all_tokens | prev_all))
            if elapsed_h >= 1.0 and len(new_tokens) >= 4 and jaccard < 0.78:
                return "update", story
            return "duplicate", story

    if cand_key in keys:
        return "duplicate", None

    # 2. Controllo semantico/tematico su tutte le notizie già pubblicate (anche da fonti o lingue diverse)
    for story in stories:
        prev_title = set(story.get("title_tokens", []))
        prev_all = set(story.get("all_tokens", []))
        if not are_same_story_tokens(cand_title_tokens, cand_all_tokens, prev_title, prev_all):
            continue

        elapsed_h = _hours_since_iso(story.get("published_iso"), slot_dt)
        if elapsed_h < 1.0:
            # Stessa fascia oraria o copertura simultanea da un'altra testata: è un duplicato, non un aggiornamento
            return "duplicate", story

        new_all = cand_all_tokens - prev_all
        new_title = cand_title_tokens - prev_title
        has_signal = bool((new_title | new_all) & UPDATE_SIGNAL_KEYWORDS)
        has_new_numbers = any(any(ch.isdigit() for ch in tok) for tok in (new_title | new_all))

        if len(new_all) >= 4 and len(new_title) >= 2 and (has_signal or has_new_numbers):
            return "update", story
        return "duplicate", story

    return "new", None


def register_published_story(
    item: Dict[str, Any],
    seen_state: Dict[str, Any],
    slot_dt: dt.datetime,
    matched_story: Optional[Dict[str, Any]] = None,
) -> None:
    """Registra una nuova notizia o aggiorna la storia esistente nello stato visto."""
    rec = build_story_record(item, slot_dt)
    seen_state["keys"][rec["key"]] = rec["date"]

    if matched_story is not None:
        matched_story["date"] = rec["date"]
        matched_story["published_at"] = rec["published_at"]
        matched_story["published_iso"] = rec["published_iso"]
        matched_story["content_hash"] = rec["content_hash"]
        matched_story["title_it"] = rec["title_it"]
        matched_story["title_tokens"] = sorted(
            set(matched_story.get("title_tokens", [])) | set(rec["title_tokens"])
        )
        matched_story["all_tokens"] = sorted(
            set(matched_story.get("all_tokens", [])) | set(rec["all_tokens"])
        )
        matched_story["update_count"] = int(matched_story.get("update_count", 0)) + 1
    else:
        seen_state["stories"].append(rec)


def adapt_readme_for_archive(content: str, edition_date: str) -> str:
    """Adatta i link relativi di README.md affinché funzionino correttamente dentro archivio/YYYY-MM-DD.md."""
    adapted = content.replace("(./IN_CORSO.md)", "(../IN_CORSO.md)")
    adapted = adapted.replace("(./archivio/", "(./")
    adapted = adapted.replace("(./README.md)", "(../README.md)")
    archive_banner = (
        f"> 🗄️ **Archivio Storico:** Stai consultando l'edizione archiviata del **{edition_date}**. "
        f"👉 **[Torna alla Pagina Principale di Oggi (`README.md`)](../README.md)**\n\n"
    )
    if "Stai consultando l'edizione archiviata" not in adapted:
        adapted = archive_banner + adapted
    return adapted


def sync_archive_nav_bars() -> None:
    """Aggiorna la barra di navigazione 'Ultimi 7 Giorni Archiviati' in tutti i file presenti in archivio/."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archives = sorted(ARCHIVE_DIR.glob("*.md"), key=lambda p: p.stem, reverse=True)[:MAX_ARCHIVE_DAYS]
    if not archives:
        return
    local_pills = " · ".join(f"[📅 **{p.stem}**](./{p.name})" for p in archives)
    new_line = f"📚 **Ultimi 7 Giorni Archiviati:** {local_pills}"
    for arch_file in archives:
        try:
            txt = arch_file.read_text(encoding="utf-8")
            updated = re.sub(
                r"^📚 \*\*Ultimi 7 Giorni Archiviati:\*\*.*$",
                new_line,
                txt,
                flags=re.MULTILINE,
            )
            if updated != txt:
                arch_file.write_text(updated, encoding="utf-8")
        except Exception:
            pass


def rotate_7day_archive(
    now_rome: dt.datetime,
    previous_edition_date: Optional[str] = None,
    current_edition_date: Optional[str] = None,
) -> List[str]:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    if README_PATH.exists() and previous_edition_date:
        archive_target = ARCHIVE_DIR / f"{previous_edition_date}.md"
        content = README_PATH.read_text(encoding="utf-8")
        if content.strip() and not archive_target.exists():
            archive_target.write_text(
                adapt_readme_for_archive(content, previous_edition_date),
                encoding="utf-8",
            )

    if current_edition_date:
        current_target = ARCHIVE_DIR / f"{current_edition_date}.md"
        if not current_target.exists():
            current_target.write_text("", encoding="utf-8")

    cutoff_date = (now_rome.date() - dt.timedelta(days=MAX_ARCHIVE_DAYS - 1)).strftime("%Y-%m-%d")
    all_archives = sorted(ARCHIVE_DIR.glob("*.md"), key=lambda p: p.stem, reverse=True)

    kept_files: List[str] = []
    for arch_file in all_archives:
        stem = arch_file.stem
        if stem < cutoff_date or len(kept_files) >= MAX_ARCHIVE_DAYS:
            try:
                arch_file.unlink()
            except Exception:
                pass
        else:
            kept_files.append(stem)

    return kept_files


def get_archive_links_markdown() -> str:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archives = sorted(ARCHIVE_DIR.glob("*.md"), key=lambda p: p.stem, reverse=True)[:MAX_ARCHIVE_DAYS]
    if not archives:
        return "_Nessun backup precedente ancora archiviato (il primo verrà salvato alle 20:00 CET / mezzanotte)._"
    pills = [f"[📅 **{p.stem}**](./archivio/{p.name})" for p in archives]
    return " · ".join(pills)


# ---------------------------------------------------------------------------
# Selezione TOP 10 (5 Core Geopolitica/Italia/UE + 5 Rotazione Globale)
# ---------------------------------------------------------------------------
def _deduplicate_top10_pool(all_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplica per URL e per storia semantica prima della selezione Top 10,
    preferendo l'aggiornamento più recente o la versione con punteggio più alto.
    """
    unique_map: Dict[str, Dict[str, Any]] = {}
    for item in all_candidates:
        item = enrich_item(dict(item))
        key = normalize_url_key(item.get("link", ""), item.get("title_orig", ""))
        if key not in unique_map or item.get("score", 0) > unique_map[key].get("score", 0):
            unique_map[key] = item

    # Ordina dando priorità agli aggiornamenti più recenti e poi allo score
    sorted_items = sorted(
        unique_map.values(),
        key=lambda x: (1 if x.get("is_update") else 0, x.get("score", 0)),
        reverse=True,
    )

    deduped: List[Dict[str, Any]] = []
    deduped_tokens: List[Tuple[set, set]] = []
    for item in sorted_items:
        t_toks, a_toks = _extract_item_token_sets(item)
        if any(are_same_story_tokens(t_toks, a_toks, pt, pa) for pt, pa in deduped_tokens):
            continue
        deduped.append(item)
        deduped_tokens.append((t_toks, a_toks))

    return sorted(deduped, key=lambda x: x.get("score", 0), reverse=True)


def select_top_10(all_candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    pool = _deduplicate_top10_pool(all_candidates)

    core_candidates = [
        x for x in pool if x.get("is_core") or x.get("category") == "geopolitica_ue"
    ]
    top_5_core: List[Dict[str, Any]] = []
    used_keys = set()
    source_counts: Dict[str, int] = {}

    for item in core_candidates:
        if len(top_5_core) >= 5:
            break
        key = normalize_url_key(item.get("link", ""), item.get("title_orig", ""))
        src = item.get("source_id", "")
        if source_counts.get(src, 0) >= 2:
            continue
        top_5_core.append(item)
        used_keys.add(key)
        source_counts[src] = source_counts.get(src, 0) + 1

    for item in pool:
        if len(top_5_core) >= 5:
            break
        key = normalize_url_key(item.get("link", ""), item.get("title_orig", ""))
        if key not in used_keys:
            top_5_core.append(item)
            used_keys.add(key)

    rotation_categories = ["tech_ia", "economia", "scienza", "filosofia", "geopolitica_ue"]
    top_5_rotation: List[Dict[str, Any]] = []

    for target_cat in rotation_categories:
        if len(top_5_rotation) >= 5:
            break
        for item in pool:
            key = normalize_url_key(item.get("link", ""), item.get("title_orig", ""))
            if key in used_keys:
                continue
            if item.get("category") == target_cat:
                top_5_rotation.append(item)
                used_keys.add(key)
                break

    for item in pool:
        if len(top_5_rotation) >= 5:
            break
        key = normalize_url_key(item.get("link", ""), item.get("title_orig", ""))
        if key not in used_keys:
            top_5_rotation.append(item)
            used_keys.add(key)

    return top_5_core, top_5_rotation


# ---------------------------------------------------------------------------
# Generazione Markdown: README.md (Pagina Principale Live di Oggi) & IN_CORSO.md
# ---------------------------------------------------------------------------
def render_top10_card(rank: int, item: Dict[str, Any]) -> str:
    medals = {
        1: "🥇 #1",
        2: "🥈 #2",
        3: "🥉 #3",
        4: "4️⃣ #4",
        5: "5️⃣ #5",
        6: "6️⃣ #6",
        7: "7️⃣ #7",
        8: "8️⃣ #8",
        9: "9️⃣ #9",
        10: "🔟 #10",
    }
    rank_label = medals.get(rank, f"#{rank}")
    badge = item.get("badge", "🌐 Mondo")
    update_tag = " `🔄 AGGIORNAMENTO`" if item.get("is_update") else ""
    title_it = item.get("title_it", item.get("title_orig", "Notizia"))
    source_name = item.get("source_name", "Fonte Internazionale")
    link = item.get("link", "#")
    summary_it = item.get("summary_it", "")
    impact_eu_it = item.get("impact_eu_it", "")
    long_term = item.get("long_term_philosophy", "")
    if "\n🧠" in long_term and "\n> 🧠" not in long_term:
        long_term = long_term.replace("\n🧠", "\n> 🧠")
    hour_collected = item.get("hour_slot", "Oggi")

    lines = [
        f"### {rank_label} · `{badge}`{update_tag} [{title_it}]({link})",
        f"**Fonte:** [{source_name}]({link}) · **Rilevata alle:** `{hour_collected}` · **Indice di Rilevanza:** `{item.get('score', 15.0)}`",
        "",
        f"> **📰 Il Fatto:** {summary_it}",
        f">",
        f"> **🇮🇹🇪🇺 Impatto Italia / Europa (CET):** {impact_eu_it}",
        f">",
        f"> 🔭 {long_term}",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def render_hourly_section(batch: Dict[str, Any], index_num: int, total_num: int) -> str:
    hour_label = batch.get("hour_label", "Ricerca Oraria")
    timestamp_str = batch.get("timestamp_str", "")
    items = batch.get("items", [])

    lines = [
        f"### 🕒 Ora `{hour_label}` — Ricerca Oraria ({index_num}/{total_num})",
        f"_Aggiornamento registrato il `{timestamp_str}`_",
        "",
    ]
    if not items:
        lines.extend(
            [
                "_Nessuna nuova notizia o aggiornamento rilevante rilevato in questa fascia oraria (le notizie già pubblicate senza nuovi sviluppi vengono filtrate automaticamente)._",
                "",
            ]
        )
        return "\n".join(lines)

    for i, it in enumerate(items, start=1):
        badge = it.get("badge", "🌐 News")
        update_tag = " `🔄 AGGIORNAMENTO`" if it.get("is_update") else ""
        title_it = it.get("title_it", it.get("title_orig", "Notizia"))
        link = it.get("link", "#")
        source_name = it.get("source_name", "Fonte")
        summary_it = it.get("summary_it", "")
        impact_short = it.get("impact_eu_it", "")

        lines.append(f"- **[{i}] `{badge}`{update_tag} [{title_it}]({link})** — *({source_name})*")
        if it.get("is_update"):
            prev_time = it.get("update_of_time", "in precedenza")
            lines.append(
                f"  - 🔄 **Aggiornamento:** Nuovi sviluppi sulla situazione rispetto alla prima segnalazione ({prev_time})."
            )
        lines.extend(
            [
                f"  - 📌 **Sintesi:** {summary_it}",
                f"  - 🇮🇹🇪🇺 **Riflesso UE/Italia:** {impact_short}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


ITALIAN_WEEKDAYS = {
    0: "Lunedì",
    1: "Martedì",
    2: "Mercoledì",
    3: "Giovedì",
    4: "Venerdì",
    5: "Sabato",
    6: "Domenica",
}

ITALIAN_MONTHS = {
    1: "Gennaio",
    2: "Febbraio",
    3: "Marzo",
    4: "Aprile",
    5: "Maggio",
    6: "Giugno",
    7: "Luglio",
    8: "Agosto",
    9: "Settembre",
    10: "Ottobre",
    11: "Novembre",
    12: "Dicembre",
}

TRAILING_STOPWORDS_IT = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "del", "dello", "della", "dei", "degli", "delle",
    "al", "allo", "alla", "ai", "agli", "alle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "e", "ed", "o", "od", "che", "non", "più", "come", "verso", "dopo", "prima",
}


def format_italian_date(date_str: str) -> str:
    try:
        d = dt.date.fromisoformat(date_str)
        wd = ITALIAN_WEEKDAYS.get(d.weekday(), "")
        mo = ITALIAN_MONTHS.get(d.month, "")
        return f"{wd} {d.day} {mo} {d.year}".strip()
    except Exception:
        return date_str


def _extract_headline_clause(title: str, max_len: int = 78) -> str:
    clean = re.sub(r"\s*\([^)]*\)\s*$", "", title.strip())
    clean = clean.strip("«»\"' ")
    for sep in [";", " — ", " – ", " - "]:
        if sep in clean:
            clean = clean.split(sep, 1)[0].strip()
    if len(clean) > max_len:
        words = clean[:max_len].rsplit(" ", 1)[0].split()
        while words and words[-1].lower().strip(",:;.!?'\"") in TRAILING_STOPWORDS_IT:
            words.pop()
        clean = " ".join(words).rstrip(",:;. ")
    return clean.strip("«»\"' ")


def generate_daily_summary_subtitle(
    top_5_core: List[Dict[str, Any]],
    top_5_rotation: List[Dict[str, Any]],
) -> str:
    clauses: List[str] = []
    if len(top_5_core) >= 1:
        c1 = _extract_headline_clause(top_5_core[0].get("title_it", ""), 75)
        if c1:
            clauses.append(c1)
    if len(top_5_core) >= 2:
        c2 = _extract_headline_clause(top_5_core[1].get("title_it", ""), 70)
        if c2:
            clauses.append(c2)
    if len(top_5_rotation) >= 1:
        c3 = _extract_headline_clause(top_5_rotation[0].get("title_it", ""), 70)
        if c3:
            clauses.append(c3)

    if not clauses:
        return "Sintesi ragionata delle ultime 24 ore tra geopolitica europea, economia e frontiera tecnologica"
    if len(clauses) == 1:
        return f"«{clauses[0]}»"
    if len(clauses) == 2:
        return f"«{clauses[0]} · {clauses[1]}»"
    return f"«{clauses[0]}; {clauses[1]} · {clauses[2]}»"


def _generate_live_subtitle(hourly_batches: List[Dict[str, Any]]) -> str:
    all_items = [it for b in hourly_batches for it in b.get("items", [])]
    if not all_items:
        return "Osservatorio in diretta: notizie della giornata aggiornate ogni ora · Top 10 alle 20:00 CET"
    top_core, top_rot = select_top_10(all_items)
    return generate_daily_summary_subtitle(top_core, top_rot)


def build_main_readme(cycle_data: Dict[str, Any], now_rome: dt.datetime) -> str:
    """
    Genera il `README.md` principale:
    - Dalle 00:00 alle 19:59 CET: mostra la giornata odierna in tempo reale (aggiornata ogni ora fino alle 19:00).
    - Alle 20:00 CET: pubblica la Top 10 definitiva di oggi; la pagina smette di aggiornarsi alle 20:00 e resta visibile fino alle 23:59 CET
      (mentre dalle 21:00 alle 23:00 il nuovo ciclo del giorno successivo accumula in background e diventa visibile dalle 00:00 CET).
    """
    edition_date = cycle_data.get("current_date") or cycle_data.get("target_edition_date") or now_rome.strftime("%Y-%m-%d")
    hourly_batches: List[Dict[str, Any]] = cycle_data.get("hourly_batches", [])
    has_top10 = (
        cycle_data.get("top10_published_date") == edition_date
        and bool(cycle_data.get("top_5_core") or cycle_data.get("top_5_rotation"))
    )
    top_5_core: List[Dict[str, Any]] = cycle_data.get("top_5_core", []) if has_top10 else []
    top_5_rotation: List[Dict[str, Any]] = cycle_data.get("top_5_rotation", []) if has_top10 else []
    published_at_str = cycle_data.get("top10_published_at_str") or f"{edition_date} alle ore 20:00 CET"

    archive_links = get_archive_links_markdown()
    total_hours = len(hourly_batches)
    total_articles = sum(len(b.get("items", [])) for b in hourly_batches)
    italian_day_label = format_italian_date(edition_date)
    last_update_label = (
        hourly_batches[-1].get("hour_label", now_rome.strftime("%H:00 CET"))
        if hourly_batches
        else now_rome.strftime("%H:00 CET")
    )

    if has_top10:
        daily_summary_subtitle = generate_daily_summary_subtitle(top_5_core, top_5_rotation)
        status_badge = (
            f"![Edizione](https://img.shields.io/badge/Top_10_Oggi-{edition_date.replace('-', '--')}_20%3A00_CET-1f6feb?style=for-the-badge) "
            f"![Ricerche Orarie](https://img.shields.io/badge/Ricerche_Nel_Ciclo-{total_hours}%2F23-2ea043?style=for-the-badge) "
            f"![Notizie Analizzate](https://img.shields.io/badge/Notizie_Nel_Ciclo-{total_articles}-8957e5?style=for-the-badge)"
        )
        nav_col1 = "**Edizione di oggi chiusa alle 20:00 CET.**<br>_Il nuovo ciclo per domani parte alle 21:00 in background e apparirà in questa pagina dopo la mezzanotte (00:00 CET)._"
        nav_col2 = "**Top 10 ufficiale delle 20:00 CET pubblicata.**<br>_Resta visibile in prima pagina fino alle 23:59 CET._"
    else:
        daily_summary_subtitle = _generate_live_subtitle(hourly_batches)
        status_badge = (
            f"![Diretta Oggi](https://img.shields.io/badge/Diretta_Oggi-{edition_date.replace('-', '--')}_{last_update_label.replace(':', '%3A').replace(' ', '_')}-e5534b?style=for-the-badge) "
            f"![Ricerche Orarie](https://img.shields.io/badge/Ricerche_Oggi-{total_hours}%2F23_verso_le_20%3A00-2ea043?style=for-the-badge) "
            f"![Notizie Analizzate](https://img.shields.io/badge/Notizie_Oggi-{total_articles}-8957e5?style=for-the-badge)"
        )
        nav_col1 = "**Stai leggendo la giornata di oggi in tempo reale.**<br>_Aggiornamento automatico ogni ora fino alle 20:00 CET. Zero ripetizioni: una notizia torna solo se ci sono nuovi sviluppi._"
        nav_col2 = "**Top 10 di oggi in arrivo alle 20:00 CET.**<br>_Alle 20:00 CET chiude l'edizione di oggi con la Top 10 in cima a questa pagina._"

    md = [
        "<div align=\"center\">",
        "",
        f"# 🧭 MERIDIANO 20:00 · {italian_day_label}",
        f"### {daily_summary_subtitle}",
        "",
        status_badge,
        "",
        "</div>",
        "",
        "---",
        "",
        "## 🧭 Pannello di Navigazione Rapida",
        "",
        "| 🔴 **DIRETTA OGGI (OGNI ORA)** | 🏆 **TOP 10 DELLE 20:00 CET** | 🗄️ **ARCHIVIO STORICO (MAX 7 GIORNI)** |",
        "| :--- | :--- | :--- |",
        f"| {nav_col1} | {nav_col2} | Backup automatico degli ultimi 7 giorni (i più vecchi vengono eliminati in automatico). |",
        "",
        f"📚 **Ultimi 7 Giorni Archiviati:** {archive_links}",
        "",
        "---",
        "",
    ]

    if has_top10:
        md.extend(
            [
                "## 🏆 TOP 10 NOTIZIE DI OGGI",
                f"_Pubblicata il **{published_at_str}** · Edizione definitiva della giornata (resta in prima pagina fino alle 23:59 CET)_",
                "",
                "### 🌍 PARTE I (Posizioni #1 – #5): Impatto Diretto Italia, Europa (CET) & Scacchiere Mondiale",
                "",
            ]
        )

        for idx, item in enumerate(top_5_core, start=1):
            md.append(render_top10_card(idx, item))

        md.extend(
            [
                "### 🔭 PARTE II (Posizioni #6 – #10): Rotazione Globale, Futuro, Scienza, Economia & Filosofia",
                "",
            ]
        )

        for idx, item in enumerate(top_5_rotation, start=6):
            md.append(render_top10_card(idx, item))

        md.extend(
            [
                "---",
                "",
                "## ⏱️ CRONOLOGIA ORARIA DELL'EDIZIONE (Dalla più recente)",
                "_Tutte le ricerche orarie raccolte nel ciclo che ha portato alla Top 10 delle 20:00 CET. Le notizie già pubblicate non vengono ripetute, salvo aggiornamenti concreti sulla situazione (`🔄 AGGIORNAMENTO`)._",
                "",
            ]
        )
    else:
        progress_filled = min(23, total_hours)
        progress_bar = "🟩" * progress_filled + "⬜" * max(0, 23 - progress_filled)
        md.extend(
            [
                f"**Progresso verso la Top 10 di oggi alle 20:00 CET ({min(23, total_hours)}/23 ricerche orarie):**",
                f"`{progress_bar}`",
                "",
                "## 📡 NOTIZIE DI OGGI FINO A QUESTO MOMENTO (Dalla più recente)",
                "_Aggiornato automaticamente ogni ora fino alle 20:00 CET. Le notizie non vengono mai ripetute, salvo aggiornamenti reali sulla situazione (`🔄 AGGIORNAMENTO`)._",
                "",
            ]
        )

    if not hourly_batches:
        md.extend(
            [
                "### ⏳ La nuova giornata è appena iniziata!",
                "_La prima ricerca oraria di oggi verrà pubblicata a breve in questa pagina._",
                "",
            ]
        )
    else:
        reversed_batches = list(reversed(hourly_batches))
        total_display = max(23, total_hours)
        for i, batch in enumerate(reversed_batches, start=1):
            chronological_idx = total_hours - i + 1
            md.append(render_hourly_section(batch, chronological_idx, total_display))

    md.extend(
        [
            "---",
            "",
            "## 🙏 Tributo & Ispirazione",
            "> Questo osservatorio nasce prendendo ispirazione dall'idea di raccolta automatizzata su GitHub ideata da [**@Reyzenello (Riccardo Bruzzese)** con il progetto *Signal-vs-InfiniteJest*](https://github.com/Reyzenello/Signal-vs-InfiniteJest). Un ringraziamento speciale al creatore originale per lo spunto sull'automazione oraria, qui ripensata in una chiave editoriale inedita centrata sull'impatto Italia/Europa (CET), sulla visione filosofica a lungo termine e sull'appuntamento serale della **Top 10 delle 20:00**.",
            "",
            "<div align=\"center\">",
            "<sub>🔒 <b>Zero-Data & Privacy Safe:</b> Generato automaticamente tramite GitHub Actions utilizzando esclusivamente feed RSS pubblici e l'indirizzo schermato <code>users.noreply.github.com</code>. Nessun dato personale viene mai letto o condiviso.</sub>",
            "</div>",
            "",
        ]
    )

    return "\n".join(md)


def build_live_in_corso_md(cycle_data: Dict[str, Any], now_rome: dt.datetime) -> str:
    """
    Mantiene `IN_CORSO.md` sincronizzato con la giornata odierna come mirror rapido,
    rimandando direttamente al `README.md` principale che ora è sempre live sulla giornata odierna.
    """
    hourly_batches: List[Dict[str, Any]] = cycle_data.get("hourly_batches", [])
    current_date = cycle_data.get("current_date", now_rome.strftime("%Y-%m-%d"))
    italian_day_label = format_italian_date(current_date)
    completed_count = len(hourly_batches)
    archive_links = get_archive_links_markdown()

    md = [
        "<div align=\"center\">",
        "",
        f"# 🔴 MERIDIANO 20:00 · {italian_day_label} (DIRETTA LIVE)",
        "### Le notizie della giornata odierna sono ora pubblicate direttamente nella pagina principale (`README.md`)",
        "",
        f"![Diretta](https://img.shields.io/badge/Diretta_Oggi-{current_date.replace('-', '--')}-e5534b?style=for-the-badge) "
        f"![Ricerche](https://img.shields.io/badge/Ricerche_Oggi-{completed_count}-2ea043?style=for-the-badge)",
        "",
        "</div>",
        "",
        "> 👉 **[APRI LA PAGINA PRINCIPALE (`README.md`)](./README.md)** — Dal cambio di mezzanotte (00:00 CET) la pagina principale mostra sempre la giornata odierna in tempo reale, con la **Top 10 alle 20:00 CET**.",
        "",
        f"📚 **Archivio 7 Giorni:** {archive_links}",
        "",
        "---",
        "",
    ]

    if not hourly_batches:
        md.extend(
            [
                "### ⏳ La nuova giornata è appena iniziata!",
                "_La prima ricerca oraria di oggi apparirà a breve sia qui sia in [`README.md`](./README.md)._",
                "",
            ]
        )
    else:
        md.extend(
            [
                "## 📡 Cronologia Live delle Ricerche di Oggi (Dalla più recente)",
                "",
            ]
        )
        reversed_batches = list(reversed(hourly_batches))
        for i, batch in enumerate(reversed_batches, start=1):
            chronological_idx = completed_count - i + 1
            md.append(render_hourly_section(batch, chronological_idx, max(20, completed_count)))

    return "\n".join(md)


# ---------------------------------------------------------------------------
# Raccolta Oraria & Motore Anti-Skip (Slot-by-Slot Catch-Up + Git Commit)
# ---------------------------------------------------------------------------
_RSS_CACHE: Optional[Dict[str, List[Dict[str, Any]]]] = None


def get_cached_rss_entries() -> Dict[str, List[Dict[str, Any]]]:
    """Carica i feed RSS una sola volta per esecuzione per velocizzare il catch-up di più ore."""
    global _RSS_CACHE
    if _RSS_CACHE is not None:
        return _RSS_CACHE
    cache: Dict[str, List[Dict[str, Any]]] = {}
    for src in RSS_SOURCES:
        cache[src["id"]] = fetch_source_entries(src, max_items=12)
    _RSS_CACHE = cache
    return cache


def collect_fresh_batch(
    slot_dt: dt.datetime,
    seen_state: Dict[str, Any],
    hour_index: int,
    count: int = ITEMS_PER_HOUR,
) -> List[Dict[str, Any]]:
    """
    Raccoglie fino a `count` notizie genuinamente nuove o con aggiornamenti concreti
    rispetto alla prima pubblicazione. NON reinserisce mai duplicati senza sviluppi.
    """
    rss_cache = get_cached_rss_entries()
    offset = hour_index % len(RSS_SOURCES)
    rotated_sources = RSS_SOURCES[offset:] + RSS_SOURCES[:offset]

    # Interleaving tra le fonti ruotate per massimizzare diversità e copertura
    raw_candidates: List[Dict[str, Any]] = []
    max_len = max((len(rss_cache.get(src["id"], [])) for src in rotated_sources), default=0)
    for idx in range(max_len):
        for src in rotated_sources:
            src_items = rss_cache.get(src["id"], [])
            if idx < len(src_items):
                raw_candidates.append(src_items[idx])

    # Pre-filtro rapido (evita di tradurre duplicati evidenti)
    pre_filtered: List[Dict[str, Any]] = []
    seen_local_keys = set()
    for cand in raw_candidates:
        key = normalize_url_key(cand.get("link", ""), cand.get("title_orig", ""))
        if key in seen_local_keys:
            continue
        seen_local_keys.add(key)
        status, _ = classify_candidate(cand, seen_state, slot_dt)
        if status != "duplicate":
            pre_filtered.append(cand)

    hour_slot_str = slot_dt.strftime("%H:00 CET")
    enriched_selected: List[Dict[str, Any]] = []
    used_sources = set()

    def try_accept(cand: Dict[str, Any], enforce_unique_source: bool) -> bool:
        if enforce_unique_source and cand.get("source_id") in used_sources:
            return False
        item = enrich_item(dict(cand))
        # Seconda verifica post-traduzione (intercetta duplicati cross-lingua IT <-> EN)
        status, matched_story = classify_candidate(item, seen_state, slot_dt)
        if status == "duplicate":
            return False
        item["hour_slot"] = hour_slot_str
        if status == "update" and matched_story is not None:
            item["is_update"] = True
            item["update_of_time"] = matched_story.get("published_at", "in precedenza")
            item["update_of_title"] = matched_story.get("title_it", "")
        else:
            item["is_update"] = False

        register_published_story(item, seen_state, slot_dt, matched_story=matched_story if status == "update" else None)
        enriched_selected.append(item)
        used_sources.add(item.get("source_id"))
        return True

    # Passata 1: bilanciamento 2 core + 2 rotazione da fonti distinte
    for want_core in [True, True, False, False]:
        if len(enriched_selected) >= count:
            break
        for cand in pre_filtered:
            if len(enriched_selected) >= count:
                break
            if bool(cand.get("is_core")) == want_core:
                if try_accept(cand, enforce_unique_source=True):
                    break

    # Passata 2: completa gli slot mancanti solo con notizie realmente nuove o aggiornamenti (mai duplicati!)
    if len(enriched_selected) < count:
        for cand in pre_filtered:
            if len(enriched_selected) >= count:
                break
            try_accept(cand, enforce_unique_source=False)

    return enriched_selected


def compute_target_edition_date(slot_dt: dt.datetime) -> str:
    """
    Le ore 00:00–19:00 appartengono all'edizione di oggi (visibile in README.md).
    Le ore 20:00 chiudono l'edizione di oggi.
    Le ore 21:00–23:00 iniziano il nuovo ciclo per domani (non visibile in README.md fino alle 00:00).
    """
    if slot_dt.hour <= 20:
        return slot_dt.strftime("%Y-%m-%d")
    return (slot_dt + dt.timedelta(days=1)).strftime("%Y-%m-%d")


def _default_cycle_data(slot_dt: dt.datetime) -> Dict[str, Any]:
    target_str = compute_target_edition_date(slot_dt)
    return {
        "current_date": target_str,
        "last_published_edition_date": None,
        "target_edition_date": target_str,
        "last_slot_iso": None,
        "top10_published_date": None,
        "top10_published_at_str": None,
        "top_5_core": [],
        "top_5_rotation": [],
        "hourly_batches": [],
    }


def ensure_cycle_state(cycle_data: Dict[str, Any], slot_dt: dt.datetime) -> Dict[str, Any]:
    """
    Allinea `cycle_data` alla data di edizione del ciclo corrente:
    - 21:00–23:00 del giorno D -> accumula per il ciclo del giorno D+1 (senza modificare README.md).
    - 00:00–19:00 del giorno D+1 -> prosegue lo stesso ciclo D+1 e lo rende visibile in README.md.
    - 20:00 del giorno D+1 -> chiude il ciclo D+1 con la Top 10 e avvia poi il ciclo D+2.
    """
    target_date = compute_target_edition_date(slot_dt)
    active_target = cycle_data.get("target_edition_date") or cycle_data.get("current_date")

    if active_target and active_target != target_date:
        cycle_data["current_date"] = target_date
        cycle_data["target_edition_date"] = target_date
        cycle_data["top_5_core"] = []
        cycle_data["top_5_rotation"] = []
        cycle_data["hourly_batches"] = []
        print(f"[CYCLE] Avviato nuovo ciclo editoriale per l'edizione {target_date}.")
    else:
        cycle_data["current_date"] = target_date
        cycle_data["target_edition_date"] = target_date
        cycle_data.setdefault("top10_published_date", None)
        cycle_data.setdefault("top10_published_at_str", None)
        cycle_data.setdefault("top_5_core", [])
        cycle_data.setdefault("top_5_rotation", [])
        cycle_data.setdefault("hourly_batches", [])

    return cycle_data


def git_commit_slot(slot_dt: dt.datetime, is_top10: bool) -> None:
    """Esegue un commit Git dedicato per lo specifico slot orario."""
    slot_str = slot_dt.strftime("%Y-%m-%d %H:00 CET")
    hour_str = slot_dt.strftime("%H")
    if is_top10:
        msg = f"🏆 Top 10 Giornaliera & Edizione Completa ({slot_str})"
    else:
        msg = f"📡 Ricerca Oraria #{hour_str}:00 ({slot_str})"

    try:
        subprocess.run(
            ["git", "add", "-A", "README.md", "IN_CORSO.md", "archivio/", "data/"],
            cwd=str(ROOT_DIR),
            check=False,
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(ROOT_DIR),
            check=False,
        )
        if diff.returncode != 0:
            env = os.environ.copy()
            iso_date = slot_dt.strftime("%Y-%m-%dT%H:00:00%z")
            env["GIT_AUTHOR_DATE"] = iso_date
            env["GIT_COMMITTER_DATE"] = iso_date
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=str(ROOT_DIR),
                env=env,
                check=False,
            )
            print(f"[GIT] Commit registrato: {msg}")
    except Exception as exc:
        print(f"[WARN] Impossibile eseguire git commit per {slot_str}: {exc}")


def run_hourly_update(slot_dt: dt.datetime) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cycle_data = load_json(CYCLE_JSON_PATH, _default_cycle_data(slot_dt))
    cycle_data = ensure_cycle_state(cycle_data, slot_dt)
    seen_state = load_seen_state(slot_dt, cycle_data=cycle_data)

    hourly_batches: List[Dict[str, Any]] = cycle_data.get("hourly_batches", [])
    hour_label = slot_dt.strftime("%H:00 CET")
    timestamp_str = slot_dt.strftime("%Y-%m-%d %H:00 CET")
    target_date = cycle_data["target_edition_date"]

    # Evita duplicati per la stessa ora nello stesso ciclo
    if any(b.get("timestamp_str") == timestamp_str for b in hourly_batches):
        cycle_data["last_slot_iso"] = slot_dt.strftime("%Y-%m-%dT%H:00:00")
        save_json(CYCLE_JSON_PATH, cycle_data)
        print(f"[SKIP] Slot {timestamp_str} già presente nel ciclo corrente.")
        return

    fresh_items = collect_fresh_batch(
        slot_dt=slot_dt,
        seen_state=seen_state,
        hour_index=slot_dt.hour + len(hourly_batches) * 3,
        count=ITEMS_PER_HOUR,
    )

    hourly_batches.append(
        {
            "hour_label": hour_label,
            "timestamp_str": timestamp_str,
            "items": fresh_items,
        }
    )

    if len(hourly_batches) > 23:
        hourly_batches = hourly_batches[-23:]

    cycle_data["hourly_batches"] = hourly_batches
    cycle_data["last_slot_iso"] = slot_dt.strftime("%Y-%m-%dT%H:00:00")

    save_json(CYCLE_JSON_PATH, cycle_data)
    save_json(SEEN_JSON_PATH, seen_state)

    # Assicura che l'ultima edizione consolidata sia presente in archivio/
    last_pub = cycle_data.get("last_published_edition_date")
    if last_pub and README_PATH.exists():
        last_arch = ARCHIVE_DIR / f"{last_pub}.md"
        if not last_arch.exists():
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            last_arch.write_text(
                adapt_readme_for_archive(README_PATH.read_text(encoding="utf-8"), last_pub),
                encoding="utf-8",
            )
            sync_archive_nav_bars()

    LIVE_PATH.write_text(build_live_in_corso_md(cycle_data, slot_dt), encoding="utf-8")

    if slot_dt.hour < 20:
        # Tra le 00:00 e le 19:00 CET il README.md principale mostra SEMPRE la giornata odierna in diretta!
        main_md = build_main_readme(cycle_data, slot_dt)
        README_PATH.write_text(main_md, encoding="utf-8")
        print(
            f"[OK] Ricerca oraria ({timestamp_str}) pubblicata in README.md "
            f"({len(fresh_items)} nuove/aggiornate, {len(hourly_batches)}/23 slot)."
        )
    else:
        # Tra le 21:00 e le 23:00 CET il README.md resta fermo sull'edizione delle 20:00 fino alle 23:59;
        # il nuovo ciclo di domani accumula in background e diventerà visibile in README.md alle 00:00 CET.
        print(
            f"[OK] Ricerca oraria ({timestamp_str}) salvata per il nuovo ciclo del {target_date} "
            f"({len(fresh_items)} nuove/aggiornate, {len(hourly_batches)}/23 slot — visibile in README.md dalle 00:00 CET)."
        )


def run_daily_top10_publication(slot_dt: dt.datetime) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cycle_data = load_json(CYCLE_JSON_PATH, _default_cycle_data(slot_dt))
    cycle_data = ensure_cycle_state(cycle_data, slot_dt)
    seen_state = load_seen_state(slot_dt, cycle_data=cycle_data)

    edition_date = slot_dt.strftime("%Y-%m-%d")
    hour_label = slot_dt.strftime("%H:00 CET")
    timestamp_str = slot_dt.strftime("%Y-%m-%d %H:00 CET")
    published_at_str = slot_dt.strftime("%d/%m/%Y alle ore 20:00 CET")

    hourly_batches: List[Dict[str, Any]] = cycle_data.get("hourly_batches", [])

    # Scansione finale delle 20:00 CET
    if not any(b.get("timestamp_str") == timestamp_str for b in hourly_batches):
        closing_items = collect_fresh_batch(
            slot_dt=slot_dt,
            seen_state=seen_state,
            hour_index=20,
            count=ITEMS_PER_HOUR,
        )
        hourly_batches.append(
            {
                "hour_label": hour_label,
                "timestamp_str": timestamp_str,
                "items": closing_items,
            }
        )

    all_candidates: List[Dict[str, Any]] = []
    for batch in hourly_batches:
        enriched_batch_items = [enrich_item(dict(it)) for it in batch.get("items", [])]
        batch["items"] = enriched_batch_items
        all_candidates.extend(enriched_batch_items)

    top_5_core, top_5_rotation = select_top_10(all_candidates)

    # Prepara lo snapshot definitivo delle 20:00 CET per README.md e archivio/YYYY-MM-DD.md
    published_snapshot = {
        "current_date": edition_date,
        "target_edition_date": edition_date,
        "last_published_edition_date": edition_date,
        "top10_published_date": edition_date,
        "top10_published_at_str": published_at_str,
        "top_5_core": top_5_core,
        "top_5_rotation": top_5_rotation,
        "hourly_batches": hourly_batches,
    }

    rotate_7day_archive(slot_dt, previous_edition_date=None, current_edition_date=edition_date)

    new_readme = build_main_readme(published_snapshot, slot_dt)
    README_PATH.write_text(new_readme, encoding="utf-8")

    # Salva immediatamente una copia definitiva in archivio/YYYY-MM-DD.md
    current_archive_path = ARCHIVE_DIR / f"{edition_date}.md"
    current_archive_path.write_text(
        adapt_readme_for_archive(new_readme, edition_date),
        encoding="utf-8",
    )
    sync_archive_nav_bars()

    # Chiude l'edizione di oggi (che non verrà più aggiornata in README.md fino a mezzanotte)
    # e prepara subito il nuovo ciclo vuoto per domani (che inizierà a raccogliere alle 21:00 in background)
    next_target = (slot_dt + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    new_cycle_data = {
        "current_date": next_target,
        "target_edition_date": next_target,
        "last_published_edition_date": edition_date,
        "last_slot_iso": slot_dt.strftime("%Y-%m-%dT20:00:00"),
        "top10_published_date": edition_date,
        "top10_published_at_str": published_at_str,
        "top_5_core": [],
        "top_5_rotation": [],
        "hourly_batches": [],
    }
    save_json(CYCLE_JSON_PATH, new_cycle_data)
    save_json(SEEN_JSON_PATH, seen_state)

    LIVE_PATH.write_text(build_live_in_corso_md(new_cycle_data, slot_dt), encoding="utf-8")
    print(
        f"[OK] TOP 10 delle 20:00 CET pubblicata e bloccata in README.md fino alle 23:59 "
        f"(archiviata in archivio/{edition_date}.md). Nuovo ciclo {next_target} pronto dalle 21:00!"
    )


def infer_last_slot_dt(cycle_data: Dict[str, Any], now_rome: dt.datetime) -> dt.datetime:
    """Ricava l'ultimo slot orario completato dal file di stato (normalizzato al minuto :00)."""
    last_iso = cycle_data.get("last_slot_iso")
    if last_iso:
        try:
            naive = dt.datetime.fromisoformat(last_iso)
            return naive.replace(minute=0, second=0, microsecond=0, tzinfo=ROME_TZ)
        except Exception:
            pass

    batches = cycle_data.get("hourly_batches", [])
    if batches:
        last_ts = batches[-1].get("timestamp_str", "")
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}):\d{2}", last_ts)
        if m:
            d_str, h_str = m.group(1), m.group(2)
            parsed = dt.datetime.fromisoformat(f"{d_str}T{h_str}:00:00")
            return parsed.replace(tzinfo=ROME_TZ)

    last_pub = cycle_data.get("last_published_edition_date")
    if last_pub:
        try:
            parsed = dt.datetime.fromisoformat(f"{last_pub}T20:00:00")
            return parsed.replace(tzinfo=ROME_TZ)
        except Exception:
            pass

    return (now_rome - dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def run_auto_with_catchup(now_rome: dt.datetime, do_git_commit: bool = False) -> None:
    """
    Calcola tutti gli slot orari (`HH:00 CET`) trascorsi dall'ultima esecuzione
    fino all'ora corrente. Se GitHub Actions ha saltato delle ore, le recupera
    in ordine cronologico (inclusi cambio giorno a 00:00 e Top 10 alle 20:00 CET)
    creando un commit distinto per ogni ora.
    """
    if not README_PATH.exists() or not CYCLE_JSON_PATH.exists():
        run_bootstrap(now_rome)
        if do_git_commit:
            git_commit_slot(now_rome.replace(minute=0, second=0, microsecond=0), is_top10=(now_rome.hour == 20))
        return

    cycle_data = load_json(CYCLE_JSON_PATH, {})
    last_slot_dt = infer_last_slot_dt(cycle_data, now_rome)
    current_slot_dt = now_rome.replace(minute=0, second=0, microsecond=0)

    if current_slot_dt <= last_slot_dt:
        print(
            f"[SKIP] Lo slot dell'ora corrente ({current_slot_dt.strftime('%Y-%m-%d %H:00 CET')}) "
            "è già stato completato. Nessun commit duplicato."
        )
        return

    pending_slots: List[dt.datetime] = []
    probe = last_slot_dt + dt.timedelta(hours=1)
    while probe <= current_slot_dt:
        pending_slots.append(probe)
        probe += dt.timedelta(hours=1)

    if len(pending_slots) > 72:
        pending_slots = pending_slots[-72:]

    print(f"[AUTO] {len(pending_slots)} slot orari da processare fino a {current_slot_dt.strftime('%Y-%m-%d %H:00 CET')}.")

    for slot_dt in pending_slots:
        state = load_json(CYCLE_JSON_PATH, {})
        slot_date_str = slot_dt.strftime("%Y-%m-%d")
        if slot_dt.hour == 20 and state.get("top10_published_date") != slot_date_str:
            run_daily_top10_publication(slot_dt)
            if do_git_commit:
                git_commit_slot(slot_dt, is_top10=True)
        else:
            run_hourly_update(slot_dt)
            if do_git_commit:
                git_commit_slot(slot_dt, is_top10=False)


def run_bootstrap(now_rome: dt.datetime) -> None:
    print("[BOOTSTRAP] Avvio giornata odierna con notizie reali dai feed mondiali, europei e italiani...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    current_slot_dt = now_rome.replace(minute=0, second=0, microsecond=0)
    today_str = current_slot_dt.strftime("%Y-%m-%d")
    seen_state = load_seen_state(current_slot_dt)
    cycle_data = _default_cycle_data(current_slot_dt)

    fresh_items = collect_fresh_batch(
        slot_dt=current_slot_dt,
        seen_state=seen_state,
        hour_index=current_slot_dt.hour,
        count=ITEMS_PER_HOUR,
    )
    cycle_data["hourly_batches"] = [
        {
            "hour_label": current_slot_dt.strftime("%H:00 CET"),
            "timestamp_str": current_slot_dt.strftime("%Y-%m-%d %H:00 CET"),
            "items": fresh_items,
        }
    ]
    cycle_data["last_slot_iso"] = current_slot_dt.strftime("%Y-%m-%dT%H:00:00")

    if current_slot_dt.hour >= 20:
        top_5_core, top_5_rotation = select_top_10(fresh_items)
        cycle_data["top10_published_date"] = today_str
        cycle_data["top10_published_at_str"] = current_slot_dt.strftime("%d/%m/%Y alle ore 20:00 CET")
        cycle_data["last_published_edition_date"] = today_str
        cycle_data["top_5_core"] = top_5_core
        cycle_data["top_5_rotation"] = top_5_rotation

    save_json(CYCLE_JSON_PATH, cycle_data)
    save_json(SEEN_JSON_PATH, seen_state)

    main_md = build_main_readme(cycle_data, current_slot_dt)
    README_PATH.write_text(main_md, encoding="utf-8")
    LIVE_PATH.write_text(build_live_in_corso_md(cycle_data, current_slot_dt), encoding="utf-8")
    print("[BOOTSTRAP] Completato!")


def run_render_only(now_rome: dt.datetime) -> None:
    """Rigenera README.md e IN_CORSO.md dallo stato corrente senza nuove chiamate RSS."""
    current_slot_dt = now_rome.replace(minute=0, second=0, microsecond=0)
    cycle_data = load_json(CYCLE_JSON_PATH, _default_cycle_data(current_slot_dt))
    cycle_data = ensure_cycle_state(cycle_data, current_slot_dt)
    seen_state = load_seen_state(current_slot_dt, cycle_data=cycle_data)

    if cycle_data.get("last_slot_iso"):
        try:
            parsed = dt.datetime.fromisoformat(cycle_data["last_slot_iso"])
            cycle_data["last_slot_iso"] = parsed.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00")
        except Exception:
            pass

    save_json(CYCLE_JSON_PATH, cycle_data)
    save_json(SEEN_JSON_PATH, seen_state)

    if current_slot_dt.hour < 20:
        main_md = build_main_readme(cycle_data, current_slot_dt)
        README_PATH.write_text(main_md, encoding="utf-8")
    LIVE_PATH.write_text(build_live_in_corso_md(cycle_data, current_slot_dt), encoding="utf-8")
    print(f"[RENDER] Stato rigenerato per il ciclo {cycle_data['target_edition_date']}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Meridiano 20:00 — News Radar Live & Top 10 Engine")
    parser.add_argument(
        "--mode",
        choices=["auto", "hourly", "daily-top10", "bootstrap", "render-only"],
        default="auto",
        help="Modalità di esecuzione",
    )
    parser.add_argument(
        "--git-commit",
        action="store_true",
        help="Crea automaticamente un commit Git per ogni slot orario processato",
    )
    args = parser.parse_args()

    now_rome = dt.datetime.now(ROME_TZ)
    current_slot_dt = now_rome.replace(minute=0, second=0, microsecond=0)

    if args.mode == "render-only":
        run_render_only(now_rome)
        return

    if args.mode == "bootstrap":
        run_bootstrap(now_rome)
        if args.git_commit:
            git_commit_slot(current_slot_dt, is_top10=(current_slot_dt.hour == 20))
        return

    if args.mode == "daily-top10":
        run_daily_top10_publication(current_slot_dt)
        if args.git_commit:
            git_commit_slot(current_slot_dt, is_top10=True)
        return

    if args.mode == "hourly":
        run_hourly_update(current_slot_dt)
        if args.git_commit:
            git_commit_slot(current_slot_dt, is_top10=False)
        return

    run_auto_with_catchup(now_rome, do_git_commit=args.git_commit)


if __name__ == "__main__":
    main()
