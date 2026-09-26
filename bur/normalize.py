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
# Pierwsze wzorce to rzeczywiste nazwy pól API BUR (np. adres.nazwaWojewodztwa), dalsze to zapas.
FIELD_PATTERNS = {
    "id": [r"^id$", r"^idUslugi$", r"^numer$"],
    "tytul": [r"^tytul$", r"tytul", r"^nazwa$", r"nazwauslugi", r"^title$"],
    "dostawca": [r"^dostawcauslug\.nazwa$", r"^dostawca\.nazwa$", r"nazwadostawcy", r"^dostawca$"],
    "wojewodztwo": [r"nazwawojewodztwa", r"^wojewodztwo$", r"wojewodztw"],
    "miejscowosc": [r"nazwamiejscowosci", r"^miejscowosc$", r"miejscowosc", r"miasto"],
    "cena": [r"^cenabruttozauczestnika$", r"^cenabruttozausluge$", r"cena.*brutto(?!.*godz)", r"^cena$",
             r"cena(?!.*godz)"],
    "cena_h": [r"^cenabruttozagodzine$", r"cena.*brutto.*godz", r"cena.*godz", r"koszt.*godz"],
    "godziny": [r"^liczbagodzin$", r"^liczbagodzinzegarowych$", r"^sumagodzinzegarowychuslugi$", r"^iloscgodzin$"],
    "data_od": [r"^datarozpoczeciauslugi$", r"datarozpoczecia", r"^dataod$", r"termin.*od"],
    "data_do": [r"^datazakonczeniauslugi$", r"datazakonczenia(?!rekrutacji)", r"^datado$", r"termin.*do"],
    "rekrutacja_do": [r"^datazakonczeniarekrutacji$"],
    "status": [r"^status$", r"statususlugi"],
    "forma": [r"^formaswiadczenia$", r"^forma$", r"^idformyswiadczenia$", r"tryb"],
    "kategoria": [r"^podkategoria$", r"^kategoria$", r"^idpodkategoriiuslugi$", r"^idkategoriiuslugi$"],
    "dofinansowanie": [r"^czyuslugadofinansowana$", r"dofinansowan"],
}

# Kolumny, których nigdy nie zgadujemy (logo, zdjęcia, osoba kontaktowa – dane osobowe).
_SKIP_COLUMNS = re.compile(r"logo|zdjecie|osobakontaktowa|url")

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
    """Dopasowuje kolumny z API do pól kanonicznych na podstawie nazw.

    Wzorce sprawdzane są po kolei na ostatnim członie nazwy (``adres.nazwaWojewodztwa`` →
    ``nazwawojewodztwa``), a wzorce z kropką na całej ścieżce. Kolumny-identyfikatory
    (``idWojewodztwa``) pasują tylko do wzorców, które jawnie zaczynają się od „id”.
    """
    folded = {c: fold(c).replace("_", "") for c in columns if not _SKIP_COLUMNS.search(fold(c))}
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for canon, patterns in FIELD_PATTERNS.items():
        mapping[canon] = None
        for pattern in patterns:
            pat = fold(pattern)
            for col, f in folded.items():
                if col in used:
                    continue
                last = f.split(".")[-1]
                target = f if "\\." in pattern else last
                if last.startswith("id") and not pat.lstrip("^").startswith("id") and pat != "^id$":
                    continue
                if re.search(pat, target):
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
    return pd.to_numeric(cleaned, errors="coerce").astype("float64")


def _to_local_datetime(series: pd.Series) -> pd.Series:
    """Daty ze strefą (…+01:00, …Z) → czas polski; daty bez strefy zostają bez zmian."""
    text = series.astype(str).str.strip()
    aware = text.str.contains(r"(?:[+-]\d\d:?\d\d|Z)$", regex=True)
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if aware.any():
        parsed = pd.to_datetime(text[aware], errors="coerce", utc=True, format="mixed")
        result[aware] = parsed.dt.tz_convert("Europe/Warsaw").dt.tz_localize(None).astype("datetime64[ns]")
    naive = ~aware & series.notna() & (text != "")
    if naive.any():
        result[naive] = pd.to_datetime(text[naive], errors="coerce", format="mixed").astype("datetime64[ns]")
    return result


def voivodeship_key(name: str) -> str:
    """„Województwo Śląskie” / „slaskie” → „slaskie” (dokładne dopasowanie, bez mylenia z dolnośląskim)."""
    return re.sub(r"^(woj(ewodztwo)?\.?\s+)", "", fold(name).strip()).strip()


def assign_topic(text: str) -> str:
    t = f" {fold(text)} "
    for topic, phrases in TEMATY.items():
        if any(fold(p) in t for p in phrases):
            return topic
    return "Inne"


# Statusy usług, których nie da się już kupić – domyślnie ukrywane.
_INACTIVE_STATUS = re.compile(r"zrealizow|anulow|odwol|wycofan|zawiesz|usuni|zakoncz|archiw|odrzuc|nieaktyw")


def is_active_status(status: str) -> bool:
    return bool(status) and not _INACTIVE_STATUS.search(fold(status))


def prices_look_like_grosze(df: pd.DataFrame) -> bool:
    """API BUR podaje ceny w groszach (np. 20500 = 205 zł/h). Stawka > 1000 zł/h jest nierealna."""
    per_hour = df["cena_h"].dropna()
    if per_hour.empty:
        per_hour = (df["cena"] / df["godziny"].where(df["godziny"] > 0)).dropna()
    return bool(len(per_hour) and per_hour.median() > 1000)


def build_frame(raw: pd.DataFrame, mapping: dict[str, str | None], grosze: bool | None = None) -> pd.DataFrame:
    """Tworzy tabelę z kolumnami kanonicznymi.

    grosze: True/False wymusza przeliczenie cen z groszy na złote; None = wykryj automatycznie.
    """
    out = pd.DataFrame(index=raw.index)
    for canon in CANONICAL:
        col = mapping.get(canon)
        out[canon] = raw[col] if col and col in raw.columns else None

    # Zawsze float64 – pandas 3 nie zmienia już typu kolumny przy przypisaniu (int64 + NaN = TypeError).
    # Zero traktujemy jako brak danych (np. e-learning z 0 godzin i stawką 0 zł/h zaniżałby medianę).
    for col in ("cena", "cena_h", "godziny"):
        num = _to_number(out[col])
        out[col] = num.where(num > 0)
    # Daty z API mają strefę (+01:00) – liczymy w czasie polskim, żeby 13.11 00:00 nie stało się 12.11.
    for col in ("data_od", "data_do", "rekrutacja_do"):
        out[col] = _to_local_datetime(out[col])

    if grosze is None:
        grosze = prices_look_like_grosze(out)
    if grosze:
        out["cena"] = out["cena"] / 100
        out["cena_h"] = out["cena_h"] / 100
    out.attrs["grosze"] = grosze

    computed_h = out["cena"] / out["godziny"]
    out["cena_h"] = out["cena_h"].fillna(computed_h)

    for col in ("tytul", "dostawca", "wojewodztwo", "miejscowosc", "forma", "kategoria", "status"):
        out[col] = out[col].fillna("").astype(str).str.strip()
    out["dofinansowanie"] = out["dofinansowanie"].map(
        lambda v: "tak" if str(v).strip().lower() in ("true", "1", "tak") else
        ("nie" if str(v).strip().lower() in ("false", "0", "nie") else "")
    )

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
    statusy: list[str] | None = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if statusy:
        mask &= df["status"].isin(statusy)
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
