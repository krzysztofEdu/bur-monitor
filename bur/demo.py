"""Fikcyjne dane demonstracyjne – żeby obejrzeć aplikację bez klucza API.

Nazwy dostawców i ceny są WYMYŚLONE i nie opisują rzeczywistego rynku.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from .normalize import WOJEWODZTWA

_TYTULY = [
    ("Excel od podstaw", 16), ("Excel dla średniozaawansowanych", 16), ("Excel zaawansowany z VBA", 24),
    ("Power Query i Power Pivot w Excelu", 16), ("Power BI – raportowanie i dashboardy", 24),
    ("Power BI z językiem DAX", 24), ("Przygotowanie do egzaminu PL-300 (Power BI)", 32),
    ("SQL – zapytania do baz danych", 24), ("Projektowanie relacyjnych baz danych", 32),
    ("Analiza danych w Pythonie", 40), ("Analityk danych – kurs kompleksowy", 80),
    ("Business Intelligence w firmie", 16), ("Tableau – wizualizacja danych", 16),
]
_FORMY = ["stacjonarna", "zdalna w czasie rzeczywistym", "mieszana"]


def demo_records(n: int = 180, seed: int = 7) -> list[dict]:
    rng = np.random.default_rng(seed)
    today = date.today()
    records = []
    for i in range(n):
        tytul, godziny = _TYTULY[rng.integers(len(_TYTULY))]
        stawka = float(rng.normal(95, 30))
        stawka = max(40.0, min(stawka, 220.0))
        forma = _FORMY[rng.integers(len(_FORMY))]
        start = today + timedelta(days=int(rng.integers(3, 150)))
        records.append({
            "id": 900000 + i,
            "tytul": tytul,
            "dostawca": {"nazwa": f"Dostawca Demo {int(rng.integers(1, 40))}"},
            "wojewodztwo": WOJEWODZTWA[rng.integers(len(WOJEWODZTWA))],
            "formaSwiadczenia": forma,
            "liczbaGodzin": godziny,
            "cenaBrutto": round(stawka * godziny, 2),
            "dataRozpoczecia": start.isoformat(),
            "dataZakonczenia": (start + timedelta(days=max(1, godziny // 8))).isoformat(),
            "kategoria": "Informatyka i telekomunikacja",
        })
    return records
