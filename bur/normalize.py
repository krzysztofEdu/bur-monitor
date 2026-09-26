"""Sprowadzenie surowych rekordów z API BUR do jednolitej tabeli i filtrowanie."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date

import pandas as pd

CARD_URL = "https://uslugirozwojowe.parp.gov.pl/wyszukiwarka/uslugi/podglad?id={id}"

WOJEWODZTWA = [
    "dolnośląskie", "kujawsko-pomorskie", "lubelskie", "lubuskie", "łódzkie",
    "małopolskie", "mazowieckie", "opolskie", "podkarpackie", "podlaskie",
    "pomorskie", "śląskie", "świętokrzyskie", "warmińsko-mazurskie",
    "wielkopolskie", "zachodniopomorskie",
]

# Tematy szkoleń IT: nazwa tematu → frazy wyszukiwane w tytule/kategorii.
TEMATY = {
    "Excel": ["excel", "arkusz kalkulacyjny", "arkusze kalkulacyjne", "vba", "power query", "power pivot"],
    "Power BI": ["power bi", "powerbi", "dax", "pl-300"],
    "Bazy danych / SQL": ["sql", "baz danych", "bazy danych", "bazach danych", "access", "t-sql", "mysql", "postgres"],
    "Analiza danych": ["analiza danych", "analizy danych", "analityk", "data analyst", "python", "statystyk"],
    "Business Intelligence": ["business intelligence", " bi ", "tableau", "qlik", "hurtowni", "raportowani", "dashboard"],
}

# Pole kanoniczne → wzorce nazw kolumn (po spłaszczeniu JSON, małe litery, bez ogonków).
FIELD_PATTERNS = {
    "id": [r"^id$", r"^idusługi$", r"^idUslugi$", r"^numer$", r"(^|\.)id$"],
    "tytul": [r"^tytul$", r"tytul", r"^nazwa$", r"nazwauslugi", r"^title$"],
    "dostawca": [r"dostawca.*nazwa", r"nazwadostawcy", r"^dostawca$", r"dostawca"],
    "wojewodztwo": [r"wojewodztwo"],
    "miejscowosc": [r"miejscowosc", r"miasto"],
    "cena": [r"cena.*brutto(?!.*godz)", r"^cena$", r"cena(?!.*godz)", r"koszt(?!.*godz)"],
    "cena_h": [r"cena.*godz", r"godz.*cena", r"koszt.*godz"],
    "godziny": [r"liczbagodzin", r"iloscgodzin", r"godzin"],
    "data_od": [r"datarozpoczecia", r"data.*od$", r"dataod", r"termin.*od", r"rozpoczecie"],
    "data_do": [r"datazakonczenia", r"data.*do$", r"datado", r"termin.*do", r"zakonczenie"],
    "forma": [r"formaswiadczenia", r"forma", r"tryb", r"sposobrealizacji"],
    "kategoria": [r"podkategoria", r"kategoria"],
    "dofinansowanie": [r"dofinansowan", r"idwsparcia", r"projekt"],
}

CANONICAL = list(FIELD_PATTERNS)


def fold(text: object) -> str:
    """Małe litery bez polskich znaków – do porównań odpornych na zapis."""
    s = unicodedata.normalize("NFKD", str(text)).replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _scalar(value: object) -> object:
    """Listy/słowniki (np. kilka lokalizacji) zamienia na czytelny tekst."""
    if isinstance(value, list):
        parts = [_scalar(v) for v in value]
        return ", ".join(str(p) for p in parts if p not in (None, ""))
    if isinstance(value, dict):
        for key in ("nazwa", "name", "wartosc", "value"):
            if key in value:
                return value[key]
        return json.dumps(value, ensure_ascii=False)
    return value


def flatten(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.json_normalize(records, sep=".")
    return df.apply(lambda col: col.map(_scalar))


def guess_mapping(columns: list[str]) -> dict[str, str | None]:
    """Dopasowuje kolumny z API do pól kanonicznych na podstawie nazw."""
    folded = {c: fold(c).replace("_", "") for c in columns}
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for canon, patterns in FIELD_PATTERNS.items():
        mapping[canon] = None
        for pattern in patterns:
            # Najpierw dopasowanie ostatniego członu (np. "dostawca.nazwa" → "nazwa"), potem całej ścieżki.
            for col, f in folded.items():
                if col in used:
                    continue
                if re.search(fold(pattern), f.split(".")[-1]) or re.search(fold(pattern), f):
                    mapping[canon] = col
                    used.add(col)
                    break
            if mapping[canon]:
                break
    return mapping


def _to_number(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"[^\d,.\-]", "", regex=True)
        .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def voivodeship_key(name: str) -> str:
    """„Województwo Śląskie” / „slaskie” → „slaskie” (dokładne dopasowanie, bez mylenia z dolnośląskim)."""
    return re.sub(r"^(woj(ewodztwo)?\.?\s+)", "", fold(name).strip()).strip()


def assign_topic(text: str) -> str:
    t = f" {fold(text)} "
    for topic, phrases in TEMATY.items():
        if any(fold(p) in t for p in phrases):
            return topic
    return "Inne"


def build_frame(raw: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Tworzy tabelę z kolumnami kanonicznymi."""
    out = pd.DataFrame(index=raw.index)
    for canon in CANONICAL:
        col = mapping.get(canon)
        out[canon] = raw[col] if col and col in raw.columns else None

    for col in ("cena", "cena_h", "godziny"):
        out[col] = _to_number(out[col]) if out[col].notna().any() else pd.NA
    for col in ("data_od", "data_do"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    missing_h = out["cena_h"].isna() & out["cena"].notna() & (out["godziny"] > 0)
    out.loc[missing_h, "cena_h"] = out.loc[missing_h, "cena"] / out.loc[missing_h, "godziny"]
    out[["cena", "cena_h", "godziny"]] = out[["cena", "cena_h", "godziny"]].astype("Float64")

    for col in ("tytul", "dostawca", "wojewodztwo", "miejscowosc", "forma", "kategoria"):
        out[col] = out[col].fillna("").astype(str).str.strip()

    out["temat"] = (out["tytul"] + " " + out["kategoria"]).map(assign_topic)
    out["link"] = out["id"].map(lambda i: CARD_URL.format(id=i) if pd.notna(i) and str(i) else None)
    return out


def filter_frame(
    df: pd.DataFrame,
    tematy: list[str] | None = None,
    fraza: str = "",
    wojewodztwa: list[str] | None = None,
    od: date | None = None,
    do: date | None = None,
    formy: list[str] | None = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if tematy:
        mask &= df["temat"].isin(tematy)
    if fraza.strip():
        needle = fold(fraza.strip())
        mask &= (df["tytul"] + " " + df["kategoria"]).map(fold).str.contains(needle, regex=False)
    if wojewodztwa:
        wanted = {voivodeship_key(w) for w in wojewodztwa}
        mask &= df["wojewodztwo"].map(
            lambda v: bool(wanted & {voivodeship_key(p) for p in re.split(r"[,;/]", v)})
        )
    if od is not None:
        mask &= df["data_od"].isna() | (df["data_od"] >= pd.Timestamp(od))
    if do is not None:
        mask &= df["data_od"].isna() | (df["data_od"] <= pd.Timestamp(do))
    if formy:
        mask &= df["forma"].isin(formy)
    return df[mask]


def price_percentile(prices: pd.Series, my_price: float) -> float | None:
    """Jaki odsetek ofert jest tańszy od mojej ceny."""
    p = prices.dropna()
    if p.empty:
        return None
    return float((p < my_price).mean() * 100)
