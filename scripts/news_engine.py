#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meridiano 20:05 — Osservatorio Mondiale, Impatto Italia/UE & Lunghi Orizzonti (23h + Top 10 @ 20:05 CET)
========================================================================================================
Funzionamento del ciclo di 24 ore (Europe/Rome):
- Ore 21:05 -> 19:05 CET (23 ricerche orarie):
    * Raccoglie e analizza le notizie più importanti dell'ora da fonti mondiali, europee e italiane.
    * Aggiorna il file live `IN_CORSO.md` (consultabile in qualsiasi momento prima delle 20:05).
    * Mantiene intatto il `README.md` principale con l'edizione completa del giorno precedente fino alle 20:04.
- Ore 20:05 CET (24ª ricerca — Pubblicazione Top 10):
    * Archivia il `README.md` precedente in `archivio/YYYY-MM-DD.md`.
    * Elimina automaticamente i file in `archivio/` più vecchi di 7 giorni (rolling backup di 7 giorni).
    * Seleziona la TOP 10 delle ultime 24 ore:
        - Posizioni #1–#5: Focus Geopolitica Mondiale & Impatto Diretto Italia / Europa (CET).
        - Posizioni #6–#10: Rotazione su IA/Tech, Economia/Mercati, Scienza/Spazio/Clima, Filosofia/Società/Lungo Termine.
    * Pubblica il nuovo `README.md` principale con la Top 10 in alto e tutte le 23 ricerche orarie scorrendo in basso.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import urllib.parse
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

import urllib.request
import xml.etree.ElementTree as ET

ROME_TZ = ZoneInfo("Europe/Rome")
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

# Parole chiave ad alto impatto per lo scoring geopolitico / europeo / italiano
HIGH_IMPACT_KEYWORDS_EU_IT = [
    "italia", "italy", "roma", "rome", "meloni", "mattarella", "governo",
    "europa", "europe", "eu", "ue", "bruxelles", "brussels", "bce", "ecb",
    "commissione europea", "eurozona", "pil", "inflazione", "dazi", "tariffs",
    "energia", "gas", "petrolio", "mediterraneo", "nato", "ucraina", "ukraine",
    "russia", "medio oriente", "cina", "china", "usa", "stati uniti", "trump",
    "difesa", "debito", "pnrr", "industria", "manifattura", "automotive",
    "intelligenza artificiale", "ai act", "semiconduttori", "chip", "sciopero",
    "clima", "transizione", "demografia", "migranti", "sicurezza", "cyber",
]

GLOBAL_PARADIGM_KEYWORDS = [
    "quantum", "quantistico", "agi", "llm", "gemini", "openai", "anthropic",
    "fusion", "fusione", "crispr", "longevity", "longevità", "space", "spazio",
    "mars", "moon", "philosophy", "filosofia", "consciousness", "coscienza",
    "ethics", "etica", "democracy", "democrazia", "algorithm", "algoritmo",
    "brain", "cervello", "neuro", "climate", "antropocene", "biotech",
]


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


def translate_to_italian(text: str, source_lang: str = "en") -> str:
    """
    Traduce automaticamente dall'inglese all'italiano usando l'endpoint pubblico
    gratuito di Google Translate (zero chiavi API richieste).
    In caso di assenza di rete o timeout, restituisce il testo originale pulito.
    """
    if not text or source_lang == "it":
        return text
    clean = text.strip()
    if len(clean) < 4:
        return clean

    # Limita lunghezza per singola richiesta
    snippet = clean[:900]
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl={urllib.parse.quote(source_lang)}&tl=it&dt=t&q={urllib.parse.quote(snippet)}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsRadar/1.0"
    }
    try:
        if requests is not None:
            resp = requests.get(url, headers=headers, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                translated = "".join(part[0] for part in data[0] if part and part[0])
                if translated:
                    return translated.strip()
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))
                translated = "".join(part[0] for part in data[0] if part and part[0])
                if translated:
                    return translated.strip()
    except Exception:
        pass
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

    # 1. Analisi Impatto Italia / UE
    if any(k in combined for k in ["bce", "inflazione", "tassi", "debito", "spread", "pil", "banca", "mercati", "borsa"]):
        impacts = [
            "Riflesso diretto sul costo del credito nell'Eurozona e sui margini di manovra della finanza pubblica italiana, con effetti a catena su mutui, investimenti industriali e tenuta del potere d'acquisto domestico.",
            "Per l'Italia e il tessuto produttivo europeo, ogni variazione negli equilibri monetari e finanziari ridefinisce la sostenibilità del debito e la capacità delle PMI di finanziare innovazione e transizione.",
            "Impatto immediato sui mercati regolamentati europei (Piazza Affari, Francoforte, Parigi): la trasmissione della politica economica globale costringe Roma e Bruxelles a ricalibrare le priorità di bilancio.",
        ]
    elif any(k in combined for k in ["dazi", "cina", "usa", "trump", "commercio", "export", "manifattura", "auto", "automotive", "supply chain"]):
        impacts = [
            "L'Italia, seconda manifattura d'Europa e fortemente orientata all'export, è esposta in prima linea a ogni attrito commerciale tra blocchi: dazi o colli di bottiglia logistici toccano direttamente meccanica, moda, agroalimentare e componentistica.",
            "Bruxelles si trova stretta tra assertività americana e sovracapacità asiatica; per il sistema industriale del Nord e Centro Italia significa dover accorciare le filiere e cercare nuovi sbocchi ad alto valore aggiunto.",
            "Riconfigurazione delle catene del valore euro-mediterranee: ciò che appare come uno scontro geoeconomico lontano si traduce in costi di approvvigionamento e nuove barriere normative per gli esportatori italiani.",
        ]
    elif any(k in combined for k in ["energia", "gas", "petrolio", "nucleare", "rinnovabili", "clima", "elettricità", "bollette"]):
        impacts = [
            "Il differenziale del costo dell'energia resta il tallone d'Achille della competitività italiana ed europea: ogni scossa sugli approvvigionamenti o sulle tecnologie energetiche incide direttamente sulle bollette e sulla tenuta delle imprese energivore.",
            "Rafforza la centralità strategica dell'Italia come hub energetico del Mediterraneo (Piano Mattei e interconnessioni Sud-Nord verso il cuore dell'Europa), accelerando il dibattito sul mix tra rinnovabili, stoccaggi e nuovo nucleare.",
            "Impatto strutturale sui target del Green Deal europeo: la sfida per Roma e Bruxelles è coniugare decarbonizzazione e sicurezza energetica senza sacrificare la base industriale continentale.",
        ]
    elif any(k in combined for k in ["ucraina", "russia", "nato", "difesa", "medio oriente", "israele", "iran", "guerra", "armi", "sicurezza", "mediterraneo"]):
        impacts = [
            "Ridefinisce l'architettura di sicurezza del fianco Est e del Mediterraneo Allargato: per l'Italia e l'UE comporta scelte inevitabili su spesa per la difesa comune, tutela delle rotte marittime (Mar Rosso/Suez) e stabilità dei confini esterni.",
            "Aumenta la pressione politica sulle capitali europee affinché passino da una dipendenza strategica a una reale capacità di deterrenza e diplomazia autonoma, con ricadute dirette sugli impegni internazionali di Roma.",
            "Ogni instabilità lungo l'arco di crisi euro-mediterraneo si riflette immediatamente sui flussi energetici, commerciali e migratori gestiti in prima battuta dall'Italia come frontiera meridionale d'Europa.",
        ]
    elif category == "tech_ia" or any(k in combined for k in ["ai", "ia", "intelligenza artificiale", "gemini", "openai", "chip", "cyber", "algoritm", "cloud", "dati"]):
        impacts = [
            "Mentre USA e Cina guidano la corsa alle infrastrutture di calcolo, l'Europa (con l'AI Act e il GDPR) gioca la partita della governance e dell'adozione industriale: per le aziende italiane la sfida è integrare questi strumenti per colmare il divario di produttività.",
            "Pone una questione cruciale di sovranità digitale europea: dipendere da piattaforme e modelli extra-UE trasforma una novità tecnologica in un fattore geopolitico che tocca pubblica amministrazione, lavoro cognitivo e sicurezza nazionale.",
            "Accelerazione nell'automazione dei servizi e della manifattura avanzata in Europa: in un Paese ad alto invecchiamento demografico come l'Italia, l'IA può diventare un moltiplicatore vitale se accompagnata da riqualificazione reale.",
        ]
    elif category == "scienza":
        impacts = [
            "Anche senza un impatto normativo immediato, i salti scientifici ridisegnano le priorità di ricerca europee (Horizon Europe), la sanità pubblica e le filiere biotech e aerospaziali in cui l'Italia vanta eccellenze di primo piano.",
            "Sposta la frontiera tecnologica su cui si misurerà la competitività europea nei prossimi dieci anni, chiamando università, centri di ricerca e poli industriali italiani a non restare semplici utilizzatori finali.",
            "Offre nuovi strumenti conoscitivi per affrontare sfide sistemiche europee — dalla longevità demografica alla resilienza climatica del bacino mediterraneo.",
        ]
    else:
        impacts = [
            "Pur non avendo un impatto normativo istantaneo su Roma o Bruxelles, agisce come indicatore anticipatore dei mutamenti culturali, sociali e istituzionali che attraversano le democrazie occidentali ed europee.",
            "Costringe l'opinione pubblica e i decisori europei a guardare oltre l'emergenza quotidiana, interrogandosi sulla tenuta del modello sociale europeo di fronte a trasformazioni globali silenziose ma profonde.",
            "Riflette tensioni e opportunità che, per osmosi culturale ed economica, raggiungono rapidamente il dibattito pubblico italiano ed europeo.",
        ]

    # 2. Prospettiva a Lungo Termine & Lente Filosofica
    if category == "tech_ia" or any(k in combined for k in ["ai", "ia", "algoritm", "robot", "dati", "schermo", "social"]):
        long_terms = [
            "**Orizzonte 5-15 anni:** Progressiva esternalizzazione dei processi decisionali e cognitivi verso infrastrutture sintetiche; il vantaggio competitivo si sposterà dal *saper fare* al *saper porre le domande giuste* e verificare la realtà.\n"
            "🧠 **Lente Filosofica:** Come analizza Luciano Floridi nell'*Infosfera*, non abitiamo più il mondo usando la tecnologia, ma abitiamo dentro l'informazione stessa. Quando la macchina genera risposte infinite a costo zero, il vero bene scarso diventa l'attenzione umana non frammentata e il discernimento critico.",
            "**Orizzonte 5-15 anni:** Riconfigurazione della divisione tra lavoro umano e calcolo automatico, con la nascita di nuove asimmetrie tra chi possiede l'infrastruttura computazionale e chi la affitta.\n"
            "🧠 **Lente Filosofica:** Da Prometeo al *Golem*, ogni protesi tecnica amplifica il potere d'azione ma riduce la frizione dell'esperienza. Come ammoniva Hans Jonas con il *Principio Responsabilità*, quando la nostra potenza tecnologica supera la nostra capacità di prevederne gli effetti ultimi, la prudenza cessa di essere debolezza e diventa la prima virtù politica.",
            "**Orizzonte 5-15 anni:** Ibridazione strutturale tra intelligenza biologica e silicio; le istituzioni nate nell'era della carta stampata dovranno reinventare i concetti di autorialità, verità probatoria e responsabilità giuridica.\n"
            "🧠 **Lente Filosofica:** Byung-Chul Han osserva che la società dell'iper-comunicazione non soffre di carenza di dati, ma di un eccesso di *rumore* che anestetizza il senso. Recuperare la profondità del tempo lento significa rifiutare il riflesso condizionato dello scrolling per tornare a comprendere le cause.",
        ]
    elif category == "scienza":
        long_terms = [
            "**Orizzonte 10-20 anni:** Ciò che oggi nasce nei laboratori come anomalia sperimentale diventerà infrastruttura invisibile della vita quotidiana, ridefinendo i limiti biologici ed energetici della specie.\n"
            "🧠 **Lente Filosofica:** Karl Popper ricordava che la scienza avanza per congetture e confutazioni, mai per dogmi definitivi. Ogni scoperta che allarga il cerchio della luce ingrandisce contemporaneamente il perimetro dell'ignoto con cui l'umanità deve fare i conti.",
            "**Orizzonte 10-20 anni:** Transizione da una comprensione descrittiva della natura a una capacità progettuale sulla materia vivente e sul cosmo, con profondi interrogativi bioetici e distributivi.\n"
            "🧠 **Lente Filosofica:** Nella tensione tra *hybris* ed episteme, la conoscenza scientifica ci ricorda il paradosso cosmico: siamo una minuscola frazione di materia dell'universo diventata improvvisamente capace di studiare le proprie stesse leggi.",
        ]
    elif category == "economia":
        long_terms = [
            "**Orizzonte 5-10 anni:** Passaggio definitivo dall'era dell'efficienza *just-in-time* (globalizzazione piatta a costo minimo) all'era della resilienza *just-in-case* (blocchi regionali, sicurezza delle scorte e capitalismo strategico di Stato).\n"
            "🧠 **Lente Filosofica:** Come spiega Nassim Nicholas Taleb in *Antifragile*, i sistemi iper-ottimizzati che eliminano ogni ridondanza in nome del profitto trimestrale diventano segretamente fragili ai Cigni Neri. La vera solidità economica non consiste nel prevedere le tempeste, ma nel costruire strutture che si rafforzano attraversandole.",
            "**Orizzonte 5-10 anni:** Tensione strutturale tra dinamiche demografiche in contrazione nel mondo sviluppato, debito pubblico storico e necessità di finanziare contemporaneamente welfare, difesa e transizione tecnologica.\n"
            "🧠 **Lente Filosofica:** Il denaro e i mercati non sono fatti fisici ma *finzioni intersoggettive* basate sulla fiducia nel futuro (Yuval Noah Harari). Quando i mercati tremano o cambiano direzione, non stanno solo prezzando merci: stanno rinegoziando il patto di fiducia tra generazioni.",
        ]
    elif category == "filosofia":
        long_terms = [
            "**Orizzonte generazionale:** Le trasformazioni più radicali della storia non iniziano nei parlamenti o nelle borse, ma nel cambio silenzioso delle categorie mentali con cui una civiltà interpreta ciò che è normale, giusto o desiderabile.\n"
            "🧠 **Lente Filosofica:** Come scriveva Seneca, *«nessun vento è favorevole per il marinaio che non sa a quale porto vuol approdare»*. In un'epoca ossessionata dall'accelerazione dei mezzi, fermarsi a interrogare i fini è l'atto più sovversivo e necessario.",
            "**Orizzonte generazionale:** Erosione dei vecchi confini tra sfera pubblica e solitudine privata, con la necessità di fondare una nuova ecologia dell'attenzione e del senso civico.\n"
            "🧠 **Lente Filosofica:** Hannah Arendt distingueva tra il semplice *lavorare per sopravvivere* e l'*agire* nello spazio pubblico insieme agli altri. Comprendere le correnti profonde del pensiero contemporaneo serve a non ridursi a ingranaggi passivi del presente.",
        ]
    else:
        long_terms = [
            "**Orizzonte 5-15 anni:** Progressiva transizione verso un mondo multipolare competitivo, in cui le regole del secondo dopoguerra vengono rinegoziate attraverso rapporti di forza energetici, tecnologici e demografici.\n"
            "🧠 **Lente Filosofica:** Niccolò Machiavelli ricordava che la *Fortuna* (il caso, gli choc storici) governa metà delle azioni umane, ma lascia l'altra metà alla *Virtù* — cioè alla capacità di preparare argini prima che il fiume esondi. Leggere i segnali geopolitici oggi significa costruire quegli argini.",
            "**Orizzonte 5-15 anni:** Ridefinizione degli equilibri tra sovranità nazionale e interdipendenza globale; i Paesi che sapranno mantenere coesione interna e visione industriale guideranno il prossimo ciclo storico.\n"
            "🧠 **Lente Filosofica:** La storia raramente procede in linea retta: alterna decenni in cui non accade nulla a settimane in cui accadono decenni. Osservare la cronaca con sguardo filosofico permette di distinguere l'increspatura superficiale dell'onda dalla marea profonda.",
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
    combina il peso della fonte, la presenza di keyword ad alto impatto Italia/UE
    e la rilevanza sistemica/globale.
    """
    base = float(item.get("source_weight", 1.0)) * 10.0
    text = f"{item.get('title_it', '')} {item.get('summary_it', '')} {item.get('title_orig', '')}".lower()

    eu_it_hits = sum(1 for kw in HIGH_IMPACT_KEYWORDS_EU_IT if kw in text)
    paradigm_hits = sum(1 for kw in GLOBAL_PARADIGM_KEYWORDS if kw in text)

    score = base + (eu_it_hits * 3.5) + (paradigm_hits * 2.5)

    # Bonus per ricchezza informativa del sommario
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
    """Parser RSS/Atom nativo in caso feedparser non sia disponibile."""
    entries: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return entries

    # RSS 2.0 <item>
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if title and link:
            entries.append({"title": title, "link": link, "summary": desc, "published": pub})

    if entries:
        return entries

    # Atom <entry>
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


def fetch_source_entries(source: Dict[str, Any], max_items: int = 8) -> List[Dict[str, Any]]:
    url = source["url"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DailySignalRadar/2.0"
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
    """Traduce in italiano (se necessario), calcola lo score e aggiunge l'analisi editoriale."""
    lang = item.get("lang", "it")
    title_it = translate_to_italian(item["title_orig"], lang)
    summary_it = translate_to_italian(item["summary_orig"], lang)

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
# Gestione Stato, Deduplicazione e Archivio Rolling di 7 Giorni
# ---------------------------------------------------------------------------
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


def normalize_url_key(url: str, title: str) -> str:
    clean_u = url.split("?")[0].strip().lower()
    clean_t = re.sub(r"\W+", "", title.lower())[:60]
    return hashlib.sha1(f"{clean_u}|{clean_t}".encode("utf-8")).hexdigest()[:16]


def load_seen_keys(now_rome: dt.datetime) -> Dict[str, str]:
    data = load_json(SEEN_JSON_PATH, {})
    if not isinstance(data, dict):
        return {}
    cutoff = (now_rome - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    return {k: v for k, v in data.items() if str(v) >= cutoff}


def rotate_7day_archive(now_rome: dt.datetime, previous_edition_date: Optional[str]) -> List[str]:
    """
    Salva il README precedente in `archivio/YYYY-MM-DD.md` e cancella
    automaticamente qualsiasi file in `archivio/` più vecchio di 7 giorni.
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    if README_PATH.exists() and previous_edition_date:
        archive_target = ARCHIVE_DIR / f"{previous_edition_date}.md"
        content = README_PATH.read_text(encoding="utf-8")
        if content.strip() and not archive_target.exists():
            archive_target.write_text(content, encoding="utf-8")

    # Pulizia rigorosa: mantieni solo gli ultimi 7 giorni
    cutoff_date = (now_rome.date() - dt.timedelta(days=MAX_ARCHIVE_DAYS)).strftime("%Y-%m-%d")
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
        return "_Nessun backup precedente ancora archiviato (il primo verrà salvato al prossimo cambio edizione delle 20:05 CET)._"
    pills = [f"[📅 **{p.stem}**](./archivio/{p.name})" for p in archives]
    return " · ".join(pills)


# ---------------------------------------------------------------------------
# Selezione TOP 10 (5 Core Geopolitica/Italia/UE + 5 Rotazione Globale)
# ---------------------------------------------------------------------------
def select_top_10(all_candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Restituisce (top_5_core, top_5_rotation) secondo la regola dell'utente:
    - Prime 5: Geopolitica mondiale & forte impatto su situazione Italiana / Europea CET.
    - Successive 5: A rotazione su Tecnologia/IA, Economia/Mercati, Scienza/Spazio, Filosofia/Lungo Termine.
    """
    unique_map: Dict[str, Dict[str, Any]] = {}
    for item in all_candidates:
        key = normalize_url_key(item.get("link", ""), item.get("title_orig", ""))
        if key not in unique_map or item.get("score", 0) > unique_map[key].get("score", 0):
            unique_map[key] = item

    pool = sorted(unique_map.values(), key=lambda x: x.get("score", 0), reverse=True)

    # 1. Seleziona Top 5 Core (Geopolitica & Impatto Italia/UE)
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

    # Fallback se servissero altri elementi per arrivare a 5
    for item in pool:
        if len(top_5_core) >= 5:
            break
        key = normalize_url_key(item.get("link", ""), item.get("title_orig", ""))
        if key not in used_keys:
            top_5_core.append(item)
            used_keys.add(key)

    # 2. Seleziona Top 5 a Rotazione (Tech/IA, Scienza, Filosofia, Economia, Mondo)
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

    # Riempi eventuali slot rimasti fino a 5 con i migliori rimasti
    for item in pool:
        if len(top_5_rotation) >= 5:
            break
        key = normalize_url_key(item.get("link", ""), item.get("title_orig", ""))
        if key not in used_keys:
            top_5_rotation.append(item)
            used_keys.add(key)

    return top_5_core, top_5_rotation


# ---------------------------------------------------------------------------
# Generazione Markdown: README.md (Edizione 20:05) & IN_CORSO.md (Live 23h)
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
    title_it = item.get("title_it", item.get("title_orig", "Notizia"))
    source_name = item.get("source_name", "Fonte Internazionale")
    link = item.get("link", "#")
    summary_it = item.get("summary_it", "")
    impact_eu_it = item.get("impact_eu_it", "")
    long_term = item.get("long_term_philosophy", "")
    hour_collected = item.get("hour_slot", "Oggi")

    lines = [
        f"### {rank_label} · `{badge}` [{title_it}]({link})",
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
    for i, it in enumerate(items, start=1):
        badge = it.get("badge", "🌐 News")
        title_it = it.get("title_it", it.get("title_orig", "Notizia"))
        link = it.get("link", "#")
        source_name = it.get("source_name", "Fonte")
        summary_it = it.get("summary_it", "")
        impact_short = it.get("impact_eu_it", "")

        lines.extend(
            [
                f"- **[{i}] `{badge}` [{title_it}]({link})** — *({source_name})*",
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


def format_italian_date(date_str: str) -> str:
    """Converte 'YYYY-MM-DD' in 'Martedì 10 Novembre 2026'."""
    try:
        d = dt.date.fromisoformat(date_str)
        wd = ITALIAN_WEEKDAYS.get(d.weekday(), "")
        mo = ITALIAN_MONTHS.get(d.month, "")
        return f"{wd} {d.day} {mo} {d.year}".strip()
    except Exception:
        return date_str


def _extract_headline_clause(title: str, max_len: int = 72) -> str:
    clean = re.sub(r"\s*\([^)]*\)\s*$", "", title.strip())
    for sep in [";", " — ", " - "]:
        if sep in clean:
            clean = clean.split(sep, 1)[0].strip()
    if len(clean) > max_len:
        clean = clean[:max_len].rsplit(" ", 1)[0].rstrip(",:.")
    return clean


def generate_daily_summary_subtitle(
    top_5_core: List[Dict[str, Any]],
    top_5_rotation: List[Dict[str, Any]],
) -> str:
    """
    Genera per la pubblicazione definitiva delle 20:05 CET un sottotitolo
    editoriale che riassume a grandi linee i temi chiave della giornata.
    """
    clauses: List[str] = []
    if len(top_5_core) >= 1:
        c1 = _extract_headline_clause(top_5_core[0].get("title_it", ""), 70)
        if c1:
            clauses.append(c1)
    if len(top_5_core) >= 2:
        c2 = _extract_headline_clause(top_5_core[1].get("title_it", ""), 65)
        if c2:
            clauses.append(c2[0].lower() + c2[1:] if len(c2) > 1 and not c2[:2].isupper() else c2)
    if len(top_5_rotation) >= 1:
        c3 = _extract_headline_clause(top_5_rotation[0].get("title_it", ""), 65)
        if c3:
            clauses.append(c3[0].lower() + c3[1:] if len(c3) > 1 and not c3[:2].isupper() else c3)

    if not clauses:
        return "Sintesi ragionata delle ultime 24 ore tra geopolitica europea, economia e frontiera tecnologica"
    if len(clauses) == 1:
        return f"«{clauses[0]}»"
    if len(clauses) == 2:
        return f"«{clauses[0]} · {clauses[1]}»"
    return f"«{clauses[0]}; {clauses[1]} · {clauses[2]}»"


def build_main_readme(
    edition_date: str,
    published_at_str: str,
    top_5_core: List[Dict[str, Any]],
    top_5_rotation: List[Dict[str, Any]],
    hourly_batches: List[Dict[str, Any]],
) -> str:
    archive_links = get_archive_links_markdown()
    total_hours = len(hourly_batches)
    total_articles = sum(len(b.get("items", [])) for b in hourly_batches)
    italian_day_label = format_italian_date(edition_date)
    daily_summary_subtitle = generate_daily_summary_subtitle(top_5_core, top_5_rotation)

    md = [
        "<div align=\"center\">",
        "",
        f"# 🧭 MERIDIANO 20:05 · {italian_day_label}",
        f"### {daily_summary_subtitle}",
        "",
        f"![Edizione](https://img.shields.io/badge/Edizione_Consolidata-{edition_date.replace('-', '--')}_20%3A05_CET-1f6feb?style=for-the-badge) "
        f"![Ricerche Orarie](https://img.shields.io/badge/Ricerche_Orarie-{total_hours}%2F23_Completate-2ea043?style=for-the-badge) "
        f"![Notizie Analizzate](https://img.shields.io/badge/Notizie_Nel_Ciclo-{total_articles}-8957e5?style=for-the-badge)",
        "",
        "</div>",
        "",
        "---",
        "",
        "## 🧭 Pannello di Navigazione Rapida",
        "",
        "| 🔴 **DIRETTA OGGI (PRIMA DELLE 20:05)** | 🏆 **EDIZIONE PRINCIPALE (20:05 CET)** | 🗄️ **ARCHIVIO STORICO (MAX 7 GIORNI)** |",
        "| :--- | :--- | :--- |",
        "| 👉 **[APRI `IN_CORSO.md` (Notizie di oggi in tempo reale)](./IN_CORSO.md)**<br>_Se entri prima delle 20:05, clicca qui per leggere le ricerche orarie già uscite oggi._ | **Stai leggendo l'Edizione Ufficiale delle 20:05 CET.**<br>_Rimane visibile in prima pagina fino alle 20:04 del giorno successivo._ | Backup automatico degli ultimi 7 giorni (i più vecchi vengono eliminati in automatico). |",
        "",
        f"📚 **Ultimi 7 Giorni Archiviati:** {archive_links}",
        "",
        "---",
        "",
        f"## 🏆 TOP 10 NOTIZIE DELLE ULTIME 24 ORE",
        f"_Pubblicata il **{published_at_str}** · Selezionata dalle 23 ricerche orarie + scansione finale delle 20:05 CET_",
        "",
        "### 🌍 PARTE I (Posizioni #1 – #5): Impatto Diretto Italia, Europa (CET) & Scacchiere Mondiale",
        "",
    ]

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
            "## ⏱️ LE 23 RICERCHE ORARIE DELLA GIORNATA (Scorri verso il basso)",
            "_Qui sotto trovi tutte le ricerche orarie raccolte durante il ciclo di 24 ore che ha portato alla Top 10._",
            "",
        ]
    )

    # Ordine dalla più recente alla più vecchia per scorrere comodamente
    reversed_batches = list(reversed(hourly_batches))
    for i, batch in enumerate(reversed_batches, start=1):
        chronological_idx = total_hours - i + 1
        md.append(render_hourly_section(batch, chronological_idx, max(23, total_hours)))

    md.extend(
        [
            "---",
            "",
            "## 🙏 Tributo & Ispirazione",
            "> Questo osservatorio nasce prendendo ispirazione dall'idea di raccolta automatizzata su GitHub ideata da [**@Reyzenello (Riccardo Bruzzese)** con il progetto *Signal-vs-InfiniteJest*](https://github.com/Reyzenello/Signal-vs-InfiniteJest). Un ringraziamento speciale al creatore originale per lo spunto sull'automazione oraria, qui ripensata in una chiave editoriale inedita centrata sull'impatto Italia/Europa (CET), sulla visione filosofica a lungo termine e sull'appuntamento serale della **Top 10 delle 20:05**.",
            "",
            "<div align=\"center\">",
            "<sub>🔒 <b>Zero-Data & Privacy Safe:</b> Generato automaticamente tramite GitHub Actions utilizzando esclusivamente feed RSS pubblici e l'indirizzo schermato <code>users.noreply.github.com</code>. Nessun dato personale viene mai letto o condiviso.</sub>",
            "</div>",
            "",
        ]
    )

    return "\n".join(md)


def build_live_in_corso_md(cycle_data: Dict[str, Any], now_rome: dt.datetime) -> str:
    hourly_batches: List[Dict[str, Any]] = cycle_data.get("hourly_batches", [])
    target_edition_date = cycle_data.get("target_edition_date", now_rome.strftime("%Y-%m-%d"))
    italian_day_label = format_italian_date(target_edition_date)
    completed_count = len(hourly_batches)
    archive_links = get_archive_links_markdown()

    progress_filled = min(23, completed_count)
    progress_bar = "🟩" * progress_filled + "⬜" * max(0, 23 - progress_filled)

    md = [
        "<div align=\"center\">",
        "",
        f"# 🔴 MERIDIANO 20:05 · {italian_day_label} (IN CORSO)",
        "### Osservatorio Mondiale, Impatto Italia/UE & Orizzonti Filosofici a Lungo Termine (CET)",
        "",
        f"![Stato Live](https://img.shields.io/badge/Stato-IN_AGGIORNAMENTO_VERSO_LE_20%3A05_CET-e5534b?style=for-the-badge) "
        f"![Progresso](https://img.shields.io/badge/Ricerche_Completate-{completed_count}%2F23-2ea043?style=for-the-badge)",
        "",
        "</div>",
        "",
        "> 💡 **Come funziona questa pagina:**",
        "> - Fino alle **20:04 CET**, la pagina principale ([`README.md`](./README.md)) mostra l'edizione consolidata del giorno precedente con la sua Top 10.",
        "> - Qui in **`IN_CORSO.md`** puoi invece leggere **in tempo reale** tutte le ricerche orarie della giornata odierna man mano che vengono pubblicate ogni ora.",
        "> - Alle **20:05 CET**, questo file verrà consolidato con la **Top 10 delle ultime 24 ore** e diventerà automaticamente il nuovo [`README.md`](./README.md) principale!",
        "",
        f"**Progresso verso la Top 10 delle 20:05 CET ({completed_count}/23 ricerche orarie):**",
        f"`{progress_bar}`",
        "",
        f"🔙 **[Torna al `README.md` Principale (Ultima Top 10 Consolidata)](./README.md)** · 📚 **Archivio 7 Giorni:** {archive_links}",
        "",
        "---",
        "",
    ]

    if not hourly_batches:
        md.extend(
            [
                "### ⏳ Il nuovo ciclo di 24 ore è appena iniziato!",
                "_La Top 10 delle 20:05 CET è appena stata pubblicata nella [pagina principale (`README.md`)](./README.md). La prima ricerca oraria del nuovo ciclo apparirà qui alle **21:05 CET**._",
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
            md.append(render_hourly_section(batch, chronological_idx, 23))

    md.extend(
        [
            "---",
            "",
            "## 🙏 Tributo & Ispirazione",
            "> Ispirato all'idea di automazione oraria su GitHub creata da [**@Reyzenello (Riccardo Bruzzese)**](https://github.com/Reyzenello/Signal-vs-InfiniteJest), sviluppato in un formato editoriale dedicato all'impatto Italia/Europa (CET), alla filosofia del futuro e alla Top 10 serale delle 20:05.",
            "",
        ]
    )

    return "\n".join(md)


# ---------------------------------------------------------------------------
# Raccolta Oraria & Logica Ciclo 23h + 24ª (20:05 CET)
# ---------------------------------------------------------------------------
def collect_fresh_batch(
    now_rome: dt.datetime,
    seen_keys: Dict[str, str],
    hour_index: int,
    count: int = ITEMS_PER_HOUR,
) -> List[Dict[str, Any]]:
    """
    Raccoglie `count` notizie fresche e ad alto segnale ruotando tra i feed RSS,
    garantendo sempre almeno 1-2 notizie Core (Geopolitica/Italia/UE) e 2 a rotazione.
    """
    # Ruota l'ordine delle fonti in base all'ora per massimizzare la varietà
    rotated_sources = RSS_SOURCES[hour_index % len(RSS_SOURCES) :] + RSS_SOURCES[: hour_index % len(RSS_SOURCES)]

    raw_candidates: List[Dict[str, Any]] = []
    for src in rotated_sources:
        entries = fetch_source_entries(src, max_items=6)
        raw_candidates.extend(entries)

    # Filtra articoli non ancora visti (se possibile)
    unseen: List[Dict[str, Any]] = []
    fallback_pool: List[Dict[str, Any]] = []

    for cand in raw_candidates:
        key = normalize_url_key(cand["link"], cand["title_orig"])
        if key not in seen_keys:
            unseen.append(cand)
        else:
            fallback_pool.append(cand)

    working_pool = unseen if len(unseen) >= count else (unseen + fallback_pool)

    # Seleziona un mix bilanciato (Core + Rotazione) evitando duplicati della stessa fonte nello stesso slot orario
    selected_raw: List[Dict[str, Any]] = []
    used_sources = set()
    used_local_keys = set()

    # Prima passa: prendi 2 Core (Geopolitica/Italia/UE) e 2 di Rotazione da fonti diverse
    for want_core in [True, True, False, False]:
        for cand in working_pool:
            if len(selected_raw) >= count:
                break
            key = normalize_url_key(cand["link"], cand["title_orig"])
            if key in used_local_keys:
                continue
            if cand["source_id"] in used_sources:
                continue
            if bool(cand.get("is_core")) == want_core:
                selected_raw.append(cand)
                used_sources.add(cand["source_id"])
                used_local_keys.add(key)
                break

    # Riempi eventuali posti rimanenti
    for cand in working_pool:
        if len(selected_raw) >= count:
            break
        key = normalize_url_key(cand["link"], cand["title_orig"])
        if key not in used_local_keys:
            selected_raw.append(cand)
            used_local_keys.add(key)

    enriched: List[Dict[str, Any]] = []
    today_str = now_rome.strftime("%Y-%m-%d")
    hour_slot_str = now_rome.strftime("%H:%M CET")

    for item in selected_raw:
        key = normalize_url_key(item["link"], item["title_orig"])
        seen_keys[key] = today_str
        item["hour_slot"] = hour_slot_str
        enriched.append(enrich_item(item))

    return enriched


def compute_target_edition_date(now_rome: dt.datetime) -> str:
    """
    Se siamo prima delle 20:00 CET, il ciclo in corso punta all'edizione delle 20:05 di OGGI.
    Se siamo dalle 20:00 CET in poi (dopo la pubblicazione), il nuovo ciclo punta alle 20:05 di DOMANI.
    """
    if now_rome.hour < 20:
        return now_rome.strftime("%Y-%m-%d")
    return (now_rome + dt.timedelta(days=1)).strftime("%Y-%m-%d")


def run_hourly_update(now_rome: dt.datetime) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    seen_keys = load_seen_keys(now_rome)
    cycle_data = load_json(
        CYCLE_JSON_PATH,
        {
            "last_published_edition_date": None,
            "target_edition_date": compute_target_edition_date(now_rome),
            "hourly_batches": [],
        },
    )

    hourly_batches: List[Dict[str, Any]] = cycle_data.get("hourly_batches", [])
    hour_label = now_rome.strftime("%H:05 CET")
    timestamp_str = now_rome.strftime("%Y-%m-%d %H:%M CET")

    fresh_items = collect_fresh_batch(
        now_rome=now_rome,
        seen_keys=seen_keys,
        hour_index=now_rome.hour + len(hourly_batches),
        count=ITEMS_PER_HOUR,
    )

    hourly_batches.append(
        {
            "hour_label": hour_label,
            "timestamp_str": timestamp_str,
            "items": fresh_items,
        }
    )

    # Mantieni al massimo 23 ricerche orarie nel ciclo attivo
    if len(hourly_batches) > 23:
        hourly_batches = hourly_batches[-23:]

    cycle_data["hourly_batches"] = hourly_batches
    if not cycle_data.get("target_edition_date"):
        cycle_data["target_edition_date"] = compute_target_edition_date(now_rome)

    save_json(CYCLE_JSON_PATH, cycle_data)
    save_json(SEEN_JSON_PATH, seen_keys)

    # Aggiorna il file live IN_CORSO.md (lasciando intatto il README.md principale fino alle 20:05!)
    live_md = build_live_in_corso_md(cycle_data, now_rome)
    LIVE_PATH.write_text(live_md, encoding="utf-8")
    print(f"[OK] Ricerca oraria ({hour_label}) completata e salvata in IN_CORSO.md ({len(hourly_batches)}/23).")


def run_daily_top10_publication(now_rome: dt.datetime) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    seen_keys = load_seen_keys(now_rome)
    cycle_data = load_json(
        CYCLE_JSON_PATH,
        {
            "last_published_edition_date": None,
            "target_edition_date": now_rome.strftime("%Y-%m-%d"),
            "hourly_batches": [],
        },
    )

    previous_edition_date = cycle_data.get("last_published_edition_date")
    edition_date = now_rome.strftime("%Y-%m-%d")
    published_at_str = now_rome.strftime("%d/%m/%Y alle ore %H:%M CET")

    # 1. Fai una scansione finale delle 20:05 per non perdere le ultimissime notizie
    closing_items = collect_fresh_batch(
        now_rome=now_rome,
        seen_keys=seen_keys,
        hour_index=20,
        count=ITEMS_PER_HOUR,
    )

    hourly_batches: List[Dict[str, Any]] = cycle_data.get("hourly_batches", [])
    if not hourly_batches:
        hourly_batches.append(
            {
                "hour_label": "19:05 CET",
                "timestamp_str": now_rome.strftime("%Y-%m-%d %H:%M CET"),
                "items": closing_items,
            }
        )

    # 2. Raccogli tutti gli articoli delle 23 ricerche + scansione delle 20:05 per eleggere la Top 10
    all_candidates: List[Dict[str, Any]] = list(closing_items)
    for batch in hourly_batches:
        all_candidates.extend(batch.get("items", []))

    top_5_core, top_5_rotation = select_top_10(all_candidates)

    # 3. Archivia il README precedente in `archivio/YYYY-MM-DD.md` ed elimina i più vecchi di 7 giorni
    rotate_7day_archive(now_rome, previous_edition_date)

    # 4. Scrivi il nuovo README.md principale con Top 10 + le 23 ricerche orarie sotto
    new_readme = build_main_readme(
        edition_date=edition_date,
        published_at_str=published_at_str,
        top_5_core=top_5_core,
        top_5_rotation=top_5_rotation,
        hourly_batches=hourly_batches,
    )
    README_PATH.write_text(new_readme, encoding="utf-8")

    # 5. Azzera le ricerche orarie per il nuovo ciclo che parte alle 21:05 CET
    next_target = (now_rome + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    new_cycle_data = {
        "last_published_edition_date": edition_date,
        "target_edition_date": next_target,
        "hourly_batches": [],
    }
    save_json(CYCLE_JSON_PATH, new_cycle_data)
    save_json(SEEN_JSON_PATH, seen_keys)

    # 6. Aggiorna IN_CORSO.md per il nuovo ciclo
    LIVE_PATH.write_text(build_live_in_corso_md(new_cycle_data, now_rome), encoding="utf-8")
    print(f"[OK] TOP 10 delle 20:05 CET pubblicata in README.md per l'edizione {edition_date}!")


def run_bootstrap(now_rome: dt.datetime) -> None:
    """
    Inizializza l'intero repository al primo avvio con notizie reali da tutti i feed RSS:
    - Costruisce l'edizione consolidata del giorno precedente (visibile subito in README.md prima delle 20:05)
      completa di Top 10 + 23 ricerche orarie.
    - Salva un backup di esempio in `archivio/` per mostrare la struttura dei 7 giorni.
    - Popola `IN_CORSO.md` con le ricerche orarie della giornata odierna fino all'ora attuale!
    """
    print("[BOOTSTRAP] Raccolta notizie reali da tutti i feed mondiali, europei e italiani...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    all_raw: List[Dict[str, Any]] = []
    for src in RSS_SOURCES:
        entries = fetch_source_entries(src, max_items=8)
        all_raw.extend(entries)

    # Deduplica preservando la varietà delle fonti
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for item in all_raw:
        by_source.setdefault(item["source_id"], []).append(item)

    interleaved: List[Dict[str, Any]] = []
    max_len = max((len(v) for v in by_source.values()), default=0)
    for idx in range(max_len):
        for src in RSS_SOURCES:
            src_list = by_source.get(src["id"], [])
            if idx < len(src_list):
                interleaved.append(src_list[idx])

    seen_keys: Dict[str, str] = {}
    today_str = now_rome.strftime("%Y-%m-%d")
    yesterday_dt = now_rome - dt.timedelta(days=1)
    yesterday_str = yesterday_dt.strftime("%Y-%m-%d")
    two_days_ago_str = (now_rome - dt.timedelta(days=2)).strftime("%Y-%m-%d")

    unique_items: List[Dict[str, Any]] = []
    for raw in interleaved:
        key = normalize_url_key(raw["link"], raw["title_orig"])
        if key not in seen_keys:
            seen_keys[key] = today_str
            unique_items.append(raw)
        if len(unique_items) >= 76:
            break

    print(f"[BOOTSTRAP] Traduzione e analisi geopolitica/filosofica di {len(unique_items)} notizie in corso...")
    enriched_pool: List[Dict[str, Any]] = [enrich_item(it) for it in unique_items]

    # Distribuisci nelle 23 ore dell'edizione consolidata (21:05 -> 19:05)
    edition_batches: List[Dict[str, Any]] = []
    hours_sequence = [21, 22, 23] + list(range(0, 20))  # 23 ore esatte: 21..23 e 00..19

    pool_len = max(1, len(enriched_pool))
    cursor = 0
    for h_idx, h_val in enumerate(hours_sequence):
        batch_date = yesterday_dt if h_val >= 21 else now_rome
        hour_label = f"{h_val:02d}:05 CET"
        ts_str = f"{batch_date.strftime('%Y-%m-%d')} {h_val:02d}:05 CET"
        slot_items: List[Dict[str, Any]] = []
        for _ in range(3):
            art = dict(enriched_pool[cursor % pool_len])
            art["hour_slot"] = hour_label
            slot_items.append(art)
            cursor += 1
        edition_batches.append(
            {
                "hour_label": hour_label,
                "timestamp_str": ts_str,
                "items": slot_items,
            }
        )

    top_5_core, top_5_rotation = select_top_10(enriched_pool)

    # 1. Crea un'edizione archiviata in `archivio/` (giorno precedente)
    archived_readme = build_main_readme(
        edition_date=two_days_ago_str,
        published_at_str=f"{(now_rome - dt.timedelta(days=2)).strftime('%d/%m/%Y')} alle ore 20:05 CET",
        top_5_core=top_5_core,
        top_5_rotation=top_5_rotation,
        hourly_batches=edition_batches,
    )
    (ARCHIVE_DIR / f"{two_days_ago_str}.md").write_text(archived_readme, encoding="utf-8")

    # 2. Scrivi il README.md principale (l'ultima edizione delle 20:05 CET visibile fino alle 20:04 di oggi)
    active_edition_date = yesterday_str if now_rome.hour < 20 else today_str
    published_label = f"{yesterday_dt.strftime('%d/%m/%Y') if now_rome.hour < 20 else now_rome.strftime('%d/%m/%Y')} alle ore 20:05 CET"

    main_readme = build_main_readme(
        edition_date=active_edition_date,
        published_at_str=published_label,
        top_5_core=top_5_core,
        top_5_rotation=top_5_rotation,
        hourly_batches=edition_batches,
    )
    README_PATH.write_text(main_readme, encoding="utf-8")

    # 3. Popola `IN_CORSO.md` con le ricerche orarie della giornata odierna fino ad adesso
    if now_rome.hour < 20:
        current_live_batches = edition_batches[: min(22, now_rome.hour + 3)]
    else:
        current_live_batches = edition_batches[:1]

    cycle_data = {
        "last_published_edition_date": active_edition_date,
        "target_edition_date": compute_target_edition_date(now_rome),
        "hourly_batches": current_live_batches,
    }
    save_json(CYCLE_JSON_PATH, cycle_data)
    save_json(SEEN_JSON_PATH, seen_keys)

    live_md = build_live_in_corso_md(cycle_data, now_rome)
    LIVE_PATH.write_text(live_md, encoding="utf-8")
    print("[BOOTSTRAP] Completato! README.md, IN_CORSO.md e archivio/ sono pronti.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Meridiano 20:05 — News Radar & Top 10 Engine")
    parser.add_argument(
        "--mode",
        choices=["auto", "hourly", "daily-top10", "bootstrap"],
        default="auto",
        help="Modalità di esecuzione",
    )
    args = parser.parse_args()

    now_rome = dt.datetime.now(ROME_TZ)

    if args.mode == "bootstrap":
        run_bootstrap(now_rome)
        return

    if args.mode == "daily-top10":
        run_daily_top10_publication(now_rome)
        return

    if args.mode == "hourly":
        run_hourly_update(now_rome)
        return

    # Modalità AUTO (usata da GitHub Actions ogni ora al minuto :05):
    # - Se ancora non esiste il README.md, esegue il bootstrap iniziale.
    # - Se in Italia (Europe/Rome) sono le ore 20:xx (cioè la run delle 20:05 CET),
    #   pubblica la Top 10 giornaliera in README.md e ruota l'archivio di 7 giorni.
    # - In tutte le altre 23 ore (21:05 -> 19:05 CET), esegue la ricerca oraria su IN_CORSO.md.
    if not README_PATH.exists() or not CYCLE_JSON_PATH.exists():
        run_bootstrap(now_rome)
        return

    cycle_data = load_json(CYCLE_JSON_PATH, {})
    today_str = now_rome.strftime("%Y-%m-%d")

    if now_rome.hour == 20 and cycle_data.get("last_published_edition_date") != today_str:
        run_daily_top10_publication(now_rome)
    else:
        run_hourly_update(now_rome)


if __name__ == "__main__":
    main()
