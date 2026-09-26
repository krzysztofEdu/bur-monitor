from datetime import date

import pandas as pd

from bur import api, demo, normalize


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.ok = status < 400
        self.text = str(payload)
        self.url = "http://test"
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, pages, token_payload=None):
        self.pages = pages
        self.token_payload = token_payload or {"token": "abc"}
        self.gets = []
        self.posts = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return FakeResponse(self.token_payload)

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append((url, dict(params or {}), headers))
        page = (params or {}).get("strona", 1)
        return FakeResponse(self.pages.get(page, {"data": []}))


def test_extract_records_variants():
    assert api.extract_records([{"a": 1}]) == [{"a": 1}]
    assert api.extract_records({"data": [{"a": 1}]}) == [{"a": 1}]
    assert api.extract_records({"wynik": {"lista": [{"a": 1}]}}) == [{"a": 1}]
    assert api.extract_records({"cokolwiek": [{"a": 1}], "total": 1}) == [{"a": 1}]
    assert api.extract_records({"total": 0}) == []


def test_find_token_nested():
    assert api.find_token({"data": {"access_token": "xyz"}}) == "xyz"
    assert api.find_token('"raw-token"') == "raw-token"
    assert api.find_token({"nic": 1}) is None


def test_fetch_all_paginates_and_uses_bearer():
    pages = {1: {"data": [{"id": 1}, {"id": 2}]}, 2: {"data": [{"id": 3}]}}
    session = FakeSession(pages)
    client = api.BurClient(api_key="k", email="e@x.pl", session=session)
    rows = client.fetch_all("/usluga", page_param="strona", size_param="iloscNaStronie", page_size=2,
                            newest_first=False)
    assert [r["id"] for r in rows] == [1, 2, 3]
    assert session.posts[0][1]["kluczAutoryzacyjny"] == "k"
    assert session.gets[0][2]["Authorization"] == "Bearer abc"


def test_fetch_all_stops_when_page_param_ignored():
    session = FakeSession({})
    session.get = lambda url, params=None, headers=None, timeout=None: FakeResponse([{"id": 1}, {"id": 2}])
    client = api.BurClient(api_key="k", auth_path="", session=session)
    rows = client.fetch_all("/usluga", page_size=2, max_pages=10)
    assert len(rows) == 2


def test_guess_mapping_on_nested_api_like_fields():
    raw = normalize.flatten([{
        "id": 5, "tytul": "Power BI i DAX", "dostawca": {"nazwa": "Firma X"},
        "cenaBrutto": "2 400,00", "liczbaGodzin": 24, "dataRozpoczecia": "2026-10-01",
        "adres": {"wojewodztwo": "Małopolskie"}, "formaSwiadczenia": "zdalna",
    }])
    m = normalize.guess_mapping(list(raw.columns))
    assert m["tytul"] == "tytul"
    assert m["dostawca"] == "dostawca.nazwa"
    assert m["cena"] == "cenaBrutto"
    assert m["godziny"] == "liczbaGodzin"
    assert m["wojewodztwo"] == "adres.wojewodztwo"
    df = normalize.build_frame(raw, m)
    assert df.loc[0, "cena"] == 2400
    assert df.loc[0, "cena_h"] == 100
    assert df.loc[0, "temat"] == "Power BI"
    assert df.loc[0, "data_od"] == pd.Timestamp("2026-10-01")  # data bez strefy zostaje bez zmian
    assert df.loc[0, "link"].endswith("id=5")


def test_topics():
    assert normalize.assign_topic("Excel zaawansowany z VBA") == "Excel"
    assert normalize.assign_topic("Kurs SQL dla analityków") == "Bazy danych / SQL"
    assert normalize.assign_topic("Szkolenie z BHP") == "Inne"


def test_filters_on_demo_data():
    raw = normalize.flatten(demo.demo_records())
    df = normalize.build_frame(raw, normalize.guess_mapping(list(raw.columns)))
    assert df["cena_h"].notna().all()
    only = normalize.filter_frame(df, wojewodztwa=["slaskie"])  # bez ogonków też działa
    assert set(only["wojewodztwo"]) <= {"śląskie"}
    assert not only.empty
    pb = normalize.filter_frame(df, tematy=["Power BI"], fraza="dax")
    assert pb["tytul"].str.contains("DAX").all()
    future = normalize.filter_frame(df, od=date(2100, 1, 1))
    assert future.empty


def test_price_percentile():
    assert normalize.price_percentile(pd.Series([50, 100, 150, 200]), 120) == 50
    assert normalize.price_percentile(pd.Series([], dtype=float), 100) is None


class PickySession(FakeSession):
    """Serwer akceptuje tylko jeden wariant pól logowania, resztę odrzuca błędem 500."""

    def __init__(self, accepted_fields):
        super().__init__({1: {"data": [{"id": 1}]}})
        self.accepted = set(accepted_fields)

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        if set(json) == self.accepted:
            return FakeResponse({"token": "ok"})
        return FakeResponse({"tytul": "Wewnętrzny błąd serwera."}, status=500)


def test_login_falls_back_to_next_body_variant():
    session = PickySession({"email", "kluczAutoryzacyjny"})
    client = api.BurClient(api_key="k", email="e@x.pl", session=session)
    assert client.authenticate() == "ok"
    assert len(session.posts) == 2
    assert "email" in client.auth_log


def test_login_uses_custom_template():
    session = PickySession({"user", "secret"})
    client = api.BurClient(api_key="k", email="e@x.pl", session=session,
                           auth_body='{"user": "{email}", "secret": "{key}"}')
    assert client.authenticate() == "ok"
    assert session.posts == [(session.posts[0][0], {"user": "e@x.pl", "secret": "k"})]


def test_login_reports_every_attempt_when_all_fail():
    session = PickySession({"nic"})
    client = api.BurClient(api_key="k", email="", session=session)
    try:
        client.authenticate()
    except api.BurApiError as exc:
        msg = str(exc)
    else:
        raise AssertionError("powinien być błąd")
    assert "BUR_API_EMAIL" in msg
    assert msg.count("→ 500") == len(session.posts) == 3  # bez e-maila tylko warianty z samym kluczem


def test_numeric_columns_survive_missing_and_integer_values():
    # Na pandas 3 kombinacja: cena/godz. jako int + brak liczby godzin kończyła się TypeError.
    cases = [
        [{"id": 1, "tytul": "Excel", "cena": 2400, "cenaZaGodzine": 100}],
        [{"id": 1, "tytul": "Excel", "cena": 2400, "liczbaGodzin": None}],
        [{"id": 1, "tytul": "Excel", "cena": 2400, "liczbaGodzin": 24, "cenaZaGodzine": None},
         {"id": 2, "tytul": "SQL", "cena": 1600, "liczbaGodzin": 16, "cenaZaGodzine": 90}],
        [{"id": 1, "tytul": "Excel"}],
    ]
    for recs in cases:
        raw = normalize.flatten(recs)
        df = normalize.build_frame(raw, normalize.guess_mapping(list(raw.columns)))
        assert all(str(df[c].dtype) == "float64" for c in ("cena", "cena_h", "godziny"))
    assert list(df.columns)  # ostatni przypadek: brak cen w ogóle nie wywraca aplikacji
    raw = normalize.flatten(cases[2])
    df = normalize.build_frame(raw, normalize.guess_mapping(list(raw.columns)))
    assert df["cena_h"].tolist() == [100, 90]


# Rekord o strukturze prawdziwej odpowiedzi API BUR (nazwy pól z eksportu, wartości fikcyjne).
BUR_RECORD = {
    "id": 3000001, "idKategoriiUslugi": 469, "idPodkategoriiUslugi": 475, "idFormySwiadczenia": 1,
    "liczbaGodzinPraktycznychIndywidualnych": None, "sumaGodzinZegarowychUslugi": 16,
    "status": "OPUBLIKOWANA", "numer": "2026/09/01/1/3000001", "tytul": "Power BI z DAX",
    "dataRozpoczeciaUslugi": "2026-11-02T00:00:00+01:00", "dataZakonczeniaUslugi": "2026-11-03T00:00:00+01:00",
    "dataZakonczeniaRekrutacji": "2026-10-30T00:00:00+01:00", "czyUslugaDofinansowana": True,
    "cenaNettoZaUczestnika": 200000, "cenaBruttoZaUczestnika": 246000,
    "cenaNettoZaGodzine": 12500, "cenaBruttoZaGodzine": 15375, "liczbaGodzin": 16,
    "dostawcaUslug": {"id": 1, "logo": {"url": "https://x/logo", "nazwa": "logo.png"}, "nazwa": "Firma Testowa"},
    "osobaKontaktowa": {"imieNazwisko": "Jan Test", "email": "jan@test.pl"},
    "adres": {"idWojewodztwa": 12, "nazwaWojewodztwa": "śląskie", "idMiejscowosci": 1,
              "nazwaMiejscowosci": "Katowice"},
}


def test_real_bur_field_names_are_mapped():
    old = dict(BUR_RECORD, id=248, status="ZREALIZOWANA", dataRozpoczeciaUslugi="2017-11-13T00:00:00+01:00")
    raw = normalize.flatten([BUR_RECORD, old])
    m = normalize.guess_mapping(list(raw.columns))
    assert m["dostawca"] == "dostawcaUslug.nazwa"
    assert m["wojewodztwo"] == "adres.nazwaWojewodztwa"
    assert m["miejscowosc"] == "adres.nazwaMiejscowosci"
    assert m["godziny"] == "liczbaGodzin"
    assert m["cena"] == "cenaBruttoZaUczestnika"
    assert m["cena_h"] == "cenaBruttoZaGodzine"
    assert m["data_od"] == "dataRozpoczeciaUslugi"
    assert m["rekrutacja_do"] == "dataZakonczeniaRekrutacji"
    assert m["status"] == "status"
    assert not any("osobaKontaktowa" in (v or "") or "logo" in (v or "") for v in m.values())

    df = normalize.build_frame(raw, m)
    assert df.attrs["grosze"] is True
    assert df.loc[0, "cena"] == 2460 and df.loc[0, "cena_h"] == 153.75
    assert df.loc[0, "dofinansowanie"] == "tak"
    assert df.loc[0, "data_od"] == pd.Timestamp("2026-11-02")  # +01:00 bez przesunięcia na poprzedni dzień
    assert df.loc[0, "temat"] == "Power BI"

    active = [s for s in df["status"].unique() if normalize.is_active_status(s)]
    assert active == ["OPUBLIKOWANA"]
    assert list(normalize.filter_frame(df, statusy=active)["id"]) == [3000001]
    assert normalize.build_frame(raw, m, grosze=False).loc[0, "cena"] == 246000


def test_page_meta_variants():
    assert api.page_meta({"data": [], "liczbaStron": 42}, 100)["pages"] == 42
    assert api.page_meta({"items": [], "meta": {"totalCount": 250}}, 100)["pages"] == 3
    assert api.page_meta({"lista": [], "liczbaWszystkichElementow": 1001}, 100)["pages"] == 11
    assert api.page_meta([{"id": 1}], 100) == {}


def test_fetch_newest_first_reads_last_pages_backwards():
    pages = {p: {"data": [{"id": p * 10 + i} for i in range(2)], "liczbaStron": 5} for p in range(1, 6)}
    session = FakeSession(pages)
    client = api.BurClient(api_key="k", email="e@x.pl", session=session)
    rows = client.fetch_all("/usluga", page_size=2, max_pages=2, newest_first=True)
    assert [r["id"] for r in rows] == [50, 51, 40, 41]
    assert client.fetch_info["newest_first"] is True
    assert client.fetch_info["pages"] == [5, 4]


def test_zero_hours_and_prices_are_treated_as_missing():
    raw = normalize.flatten([{"id": 1, "tytul": "Excel e-learning", "cena": 220, "liczbaGodzin": 0,
                              "cenaZaGodzine": 0}])
    df = normalize.build_frame(raw, normalize.guess_mapping(list(raw.columns)), grosze=False)
    assert pd.isna(df.loc[0, "cena_h"]) and pd.isna(df.loc[0, "godziny"])
    assert df.loc[0, "cena"] == 220


class BurLikeSession(FakeSession):
    """Zachowuje się jak prawdziwe API BUR: stałe 25 rekordów na stronę, parametr rozmiaru
    ignorowany, strony od 1, brak liczby stron w odpowiedzi, rekordy od najstarszych."""

    def __init__(self, last_page=5000, per_page=25):
        super().__init__({})
        self.last_page, self.per_page = last_page, per_page

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append((url, dict(params or {}), headers))
        page = int((params or {}).get("strona", 1))
        if page < 1 or page > self.last_page:
            return FakeResponse({"data": []})
        first = (page - 1) * self.per_page
        return FakeResponse({"data": [{"id": first + i} for i in range(self.per_page)]})


def test_auto_paging_finds_newest_pages_without_metadata():
    session = BurLikeSession(last_page=5000)
    client = api.BurClient(api_key="k", email="e@x.pl", session=session)
    rows = client.fetch_all("/usluga", page_size=100, max_pages=3)
    info = client.fetch_info
    assert info["detected"]["page_param"] == "strona"
    assert info["detected"]["size_param"] == ""       # API ignoruje rozmiar strony
    assert info["last_page"] == 5000
    assert info["pages"] == [5000, 4999, 4998]
    assert rows[0]["id"] == 4999 * 25                  # najnowsze usługi na początku
    assert len(rows) == 75
    assert info["requests"] < 60                       # wyszukiwanie, a nie przeglądanie 5000 stron


def test_auto_paging_when_page_param_is_ignored():
    session = FakeSession({})
    session.get = lambda url, params=None, headers=None, timeout=None: FakeResponse([{"id": 1}, {"id": 2}])
    client = api.BurClient(api_key="k", auth_path="", session=session)
    rows = client.fetch_all("/usluga", page_size=100, max_pages=5)
    assert len(rows) == 2
    assert client.fetch_info["detected"]["page_param"] == ""
    assert client.fetch_info["newest_first"] is False


class StrictBurSession(BurLikeSession):
    """Jak BUR: nieznany parametr zapytania → 500 (zamiast go zignorować)."""

    def get(self, url, params=None, headers=None, timeout=None):
        unknown = set(params or {}) - {"strona"}
        if unknown:
            self.gets.append((url, dict(params or {}), headers))
            return FakeResponse({"tytul": "Wewnętrzny błąd serwera."}, status=500)
        return super().get(url, params, headers, timeout)


def test_auto_paging_survives_500_for_unknown_params():
    session = StrictBurSession(last_page=800)
    client = api.BurClient(api_key="k", email="e@x.pl", session=session)
    rows = client.fetch_all("/usluga", page_size=100, max_pages=2)
    assert client.fetch_info["detected"]["page_param"] == "strona"
    assert client.fetch_info["detected"]["size_param"] == ""
    assert client.fetch_info["pages"] == [800, 799]
    assert len(rows) == 50
    # Główne zapytania (bez próbnych nazw) nie wysyłają już nieobsługiwanych parametrów.
    last_calls = [params for _, params, _ in session.gets[-2:]]
    assert all(set(p) == {"strona"} for p in last_calls)


class FlakySession(BurLikeSession):
    """Strona 1 czasem zwraca 500 (chwilowy błąd) – nie może to zmienić numeracji ani zatrzymać pobierania."""

    def __init__(self, fail_times=1, **kw):
        super().__init__(**kw)
        self.fail_left = fail_times

    def get(self, url, params=None, headers=None, timeout=None):
        if (params or {}).get("strona") == 1 and self.fail_left > 0:
            self.fail_left -= 1
            self.gets.append((url, dict(params or {}), headers))
            return FakeResponse({"tytul": "Wewnętrzny błąd serwera."}, status=500)
        return super().get(url, params, headers, timeout)


def test_transient_error_on_page_one_is_retried_not_misread_as_zero_based():
    session = FlakySession(fail_times=1, last_page=40)
    client = api.BurClient(api_key="k", email="e@x.pl", session=session, sleep=lambda s: None)
    rows = client.fetch_all("/usluga", page_size=100, max_pages=3, newest_first=False)
    assert client.fetch_info["detected"]["start"] == 1
    assert client.fetch_info["pages"] == [1, 2, 3]
    assert len(rows) == 75


def test_odwolana_is_inactive():
    assert not normalize.is_active_status("ODWOLANA")
    assert not normalize.is_active_status("ODWOŁANA")
    assert normalize.is_active_status("OPUBLIKOWANA")
