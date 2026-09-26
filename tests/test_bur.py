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
    rows = client.fetch_all("/usluga", page_size=2)
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
