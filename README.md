# 📈 BUR Monitor

Aplikacja (Streamlit) dla dostawcy szkoleń IT w **Bazie Usług Rozwojowych (BUR)**:

- **📊 Rynek w BUR**: pobiera usługi przez API BUR i pokazuje konkurencję w tematach Excel, Power BI,
  bazy danych/SQL, analiza danych i BI. Możesz filtrować po województwach, terminach i formie usługi.
  Zobaczysz mediany cen za godzinę, najaktywniejszych dostawców, porównanie Twojej ceny z rynkiem
  i eksport do CSV.
- **🧭 Jak sprzedawać w BUR**: lista kontrolna (karta dostawcy, karta usługi, timing naborów, sprzedaż zgodna z zasadami).
- **🛠️ Diagnostyka API**: lista endpointów ze schematu, testowe zapytanie i ręczne mapowanie pól,
  gdy API zwraca inne nazwy kolumn niż przewidziane.

## Uruchomienie

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # i wpisz klucz API
streamlit run app.py
```

Klucz API generujesz w profilu BUR, w sekcji „Dostęp do API”.
**Nie commituj go.** Plik `.streamlit/secrets.toml` jest w `.gitignore`.
Bez klucza możesz obejrzeć aplikację na fikcyjnych danych: w panelu bocznym wybierz **Dane demonstracyjne**.

## Pierwsze połączenie z API

Domyślne ścieżki (`/autoryzacja/logowanie`, `/usluga`, parametry `strona`/`iloscNaStronie`) mogą
różnić się od aktualnej dokumentacji (https://uslugirozwojowe.parp.gov.pl/api/). Jeśli pobieranie się nie uda:

1. W zakładce **Diagnostyka API** kliknij „Pobierz schemat API” albo otwórz dokumentację w przeglądarce.
2. Popraw ścieżki w panelu bocznym (sekcja „Zaawansowane”) lub na stałe w `secrets.toml`.
3. Wyślij testowe zapytanie i sprawdź, czy wracają dane.
4. Jeśli jakaś kolumna jest pusta (np. cena albo województwo), wskaż właściwe pole w sekcji „Mapowanie pól”.

## Jak aplikacja pobiera dane z BUR

API BUR (`GET /usluga`) zwraca usługi **od najstarszych**, zawsze po 25 na stronę, bez filtra
statusu, daty ani sortowania. Obsługuje za to filtry `idWojewodztwa`, `idKategoriiUslugi`,
`idPodkategoriiUslugi` (oraz m.in. `id`, `idProjektu`, `nipDostawcyUslug`). Dlatego:

1. W panelu bocznym wybierz **województwa** i ustaw **ID kategorii/podkategorii**. Najprościej:
   „Odczytaj kategorię z mojej usługi”, wpisz ID swojej usługi IT z BUR i kliknij „Użyj podkategorii”.
2. Aplikacja pobiera każde województwo osobno. Ostatnią stronę znajduje wyszukiwaniem binarnym
   i czyta strony wstecz, czyli od najnowszych usług.
3. Ceny z API są w groszach i są przeliczane na złote.

## Testy

```bash
pip install pytest && python -m pytest -q
```
