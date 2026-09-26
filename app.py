"""
📈 BUR Monitor – rynek szkoleń IT w Bazie Usług Rozwojowych
Uruchomienie:  streamlit run app.py
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from bur import api, demo, normalize, poradnik

st.set_page_config(page_title="BUR Monitor", page_icon="📈", layout="wide")

ACCENT = "#2e75b6"

st.markdown("""
<style>
  .main-header {
    background: linear-gradient(135deg, #1a3c5e 0%, #2e75b6 100%);
    color: white; padding: 18px 26px; border-radius: 12px; margin-bottom: 16px;
  }
  .main-header h1 { margin: 0 0 4px; font-size: 1.6rem; }
  .main-header p  { margin: 0; opacity: 0.85; font-size: 0.95rem; }
  div[data-testid="stTabs"] button { font-weight: bold !important; }
</style>
<div class="main-header">
  <h1>📈 BUR Monitor</h1>
  <p>Rynek szkoleń IT (Excel, bazy danych, analiza danych, BI, Power BI) w Bazie Usług Rozwojowych</p>
</div>
""", unsafe_allow_html=True)


# ── KONFIGURACJA ─────────────────────────────────────────────
def setting(name: str, default: str = "") -> str:
    """Kolejność: .streamlit/secrets.toml → zmienna środowiskowa → domyślna."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_services(cfg_json: str) -> list[dict]:
    cfg = json.loads(cfg_json)
    client = api.BurClient(
        api_key=cfg["key"], email=cfg["email"], base_url=cfg["base"], auth_path=cfg["auth_path"],
        auth_body=cfg["auth_body"],
    )
    return client.fetch_all(
        cfg["path"], params=cfg["params"], page_param=cfg["page_param"], size_param=cfg["size_param"],
        page_size=cfg["page_size"], start_page=cfg["start_page"], max_pages=cfg["max_pages"],
    )


with st.sidebar:
    st.header("⚙️ Źródło danych")
    zrodlo = st.radio("Skąd brać dane?", ["API BUR", "Plik CSV/JSON", "Dane demonstracyjne"],
                      help="Dane demonstracyjne są fikcyjne – służą tylko do obejrzenia aplikacji.")

    if zrodlo == "API BUR":
        secret_key = setting("BUR_API_KEY")
        if secret_key:
            st.success("Klucz API wczytany z konfiguracji.")
            key = secret_key
        else:
            key = st.text_input("Klucz API", type="password",
                                help="Lepiej wpisać go w .streamlit/secrets.toml (BUR_API_KEY).")
        email = st.text_input("E-mail konta BUR", value=setting("BUR_API_EMAIL"))
        with st.expander("Zaawansowane (endpointy)"):
            base = st.text_input("Adres API", setting("BUR_API_URL", api.DEFAULT_BASE_URL))
            auth_path = st.text_input("Ścieżka logowania (pusta = klucz jako Bearer)",
                                      setting("BUR_AUTH_PATH", api.DEFAULT_AUTH_PATH))
            auth_body = st.text_input(
                "Szablon logowania (JSON, opcjonalnie)", setting("BUR_AUTH_BODY"),
                placeholder='{"nazwaUzytkownika": "{email}", "kluczAutoryzacyjny": "{key}"}',
                help="Puste = aplikacja próbuje kilku typowych wariantów. {email} i {key} są podstawiane automatycznie.",
            )
            path = st.text_input("Ścieżka listy usług", setting("BUR_USLUGI_PATH", api.DEFAULT_SERVICES_PATH))
            params_txt = st.text_area("Dodatkowe parametry (JSON)", setting("BUR_USLUGI_PARAMS", "{}"),
                                      help='Np. {"status": "opublikowana"} – nazwy sprawdź w Diagnostyce API.')
            c1, c2 = st.columns(2)
            page_param = c1.text_input("Parametr strony", setting("BUR_PAGE_PARAM", "strona"))
            size_param = c2.text_input("Parametr rozmiaru", setting("BUR_SIZE_PARAM", "iloscNaStronie"))
            c3, c4, c5 = st.columns(3)
            start_page = c3.number_input("1. strona", 0, 1, 1)
            page_size = c4.number_input("Na stronę", 10, 1000, 100, step=10)
            max_pages = c5.number_input("Maks. stron", 1, 500, 20)

        if st.button("🔄 Pobierz usługi z BUR", type="primary", use_container_width=True):
            try:
                params = json.loads(params_txt or "{}")
            except json.JSONDecodeError:
                st.error("Dodatkowe parametry to niepoprawny JSON.")
                params = None
            if params is not None:
                cfg = dict(key=key, email=email, base=base, auth_path=auth_path, auth_body=auth_body, path=path, params=params,
                           page_param=page_param, size_param=size_param, page_size=int(page_size),
                           start_page=int(start_page), max_pages=int(max_pages))
                with st.spinner("Pobieram dane z API BUR…"):
                    try:
                        st.session_state["records"] = fetch_services(json.dumps(cfg, sort_keys=True))
                        st.session_state["source"] = "API BUR"
                    except (api.BurApiError, OSError) as exc:
                        st.error(f"Błąd API: {exc}")
                        st.info("Sprawdź ścieżki w zakładce „🛠️ Diagnostyka API”.")
        st.session_state["api_cfg"] = dict(key=key, email=email, base=base, auth_path=auth_path, auth_body=auth_body)

    elif zrodlo == "Plik CSV/JSON":
        up = st.file_uploader("Eksport z BUR lub zapisana odpowiedź API", type=["csv", "json"])
        if up is not None:
            if up.name.endswith(".json"):
                st.session_state["records"] = api.extract_records(json.load(up))
            else:
                raw_csv = pd.read_csv(up, sep=None, engine="python")
                st.session_state["records"] = raw_csv.to_dict("records")
            st.session_state["source"] = f"plik {up.name}"

    else:
        if st.session_state.get("source") != "demo":
            st.session_state["records"] = demo.demo_records()
            st.session_state["source"] = "demo"

records: list[dict] = st.session_state.get("records", [])
raw = normalize.flatten(records)

# Mapowanie pól resetuje się, gdy zmieni się zestaw kolumn.
cols_sig = tuple(raw.columns)
if st.session_state.get("mapping_sig") != cols_sig:
    st.session_state["mapping"] = normalize.guess_mapping(list(raw.columns))
    st.session_state["mapping_sig"] = cols_sig
mapping = st.session_state["mapping"]

df = normalize.build_frame(raw, mapping) if not raw.empty else pd.DataFrame()

tab_rynek, tab_sprzedaz, tab_diag = st.tabs(["📊 Rynek w BUR", "🧭 Jak sprzedawać w BUR", "🛠️ Diagnostyka API"])

# ── RYNEK ────────────────────────────────────────────────────
with tab_rynek:
    if df.empty:
        st.info("Brak danych. Wybierz źródło w panelu bocznym i pobierz usługi "
                "(albo włącz „Dane demonstracyjne”, żeby zobaczyć, jak to działa).")
    else:
        if st.session_state.get("source") == "demo":
            st.warning("Oglądasz **fikcyjne dane demonstracyjne** – nie opisują rzeczywistego rynku.")
        else:
            st.caption(f"Źródło: {st.session_state.get('source')} · rekordów: {len(df)}")

        f1, f2, f3 = st.columns([2, 3, 2])
        tematy = f1.multiselect("Temat", list(normalize.TEMATY) + ["Inne"], default=list(normalize.TEMATY),
                                placeholder="Wszystkie tematy")
        woj_opts = sorted(set(normalize.WOJEWODZTWA) | {w for w in df["wojewodztwo"].unique() if w and "," not in w})
        wojewodztwa = f2.multiselect("Województwa (puste = cała Polska)", woj_opts, placeholder="Wybierz województwa…")
        fraza = f3.text_input("Fraza w tytule", placeholder="np. DAX, VBA, PL-300")

        f4, f5 = st.columns([2, 3])
        has_dates = df["data_od"].notna().any()
        zakres = f4.date_input("Start usługi między", (date.today(), date.today() + timedelta(days=180)),
                               disabled=not has_dates)
        formy_opts = sorted(x for x in df["forma"].unique() if x)
        formy = f5.multiselect("Forma", formy_opts, disabled=not formy_opts, placeholder="Wszystkie formy")

        od, do = (zakres if isinstance(zakres, tuple) and len(zakres) == 2 else (None, None)) if has_dates else (None, None)
        view = normalize.filter_frame(df, tematy, fraza, wojewodztwa, od, do, formy)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Usługi", len(view))
        m2.metric("Dostawcy", view["dostawca"].replace("", pd.NA).nunique())
        med_h = view["cena_h"].median()
        m3.metric("Mediana ceny / godz.", f"{med_h:,.0f} zł".replace(",", " ") if pd.notna(med_h) else "–")
        med = view["cena"].median()
        m4.metric("Mediana ceny usługi", f"{med:,.0f} zł".replace(",", " ") if pd.notna(med) else "–")

        if view.empty:
            st.warning("Żadna usługa nie spełnia filtrów.")
        else:
            def hbar(series: pd.Series, title: str, xlabel: str, fmt: str = ",.0f"):
                data = series.sort_values().tail(15).reset_index()
                data.columns = ["nazwa", "wartosc"]
                fig = px.bar(data, x="wartosc", y="nazwa", orientation="h", title=title,
                             labels={"wartosc": xlabel, "nazwa": ""}, text="wartosc")
                fig.update_traces(marker_color=ACCENT, texttemplate=f"%{{text:{fmt}}}", textposition="outside", cliponaxis=False,
                                  hovertemplate=f"%{{y}}: %{{x:{fmt}}}<extra></extra>")
                fig.update_layout(height=max(260, 34 * len(data) + 90), margin=dict(l=10, r=50, t=50, b=10),
                                  bargap=0.35, xaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)"))
                st.plotly_chart(fig, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                woj = view.loc[view["wojewodztwo"] != "", "wojewodztwo"].value_counts()
                if not woj.empty:
                    hbar(woj, "Liczba usług wg województwa", "usługi", ",d")
                else:
                    st.caption("Brak danych o województwie – ustaw mapowanie w Diagnostyce API.")
            with c2:
                by_topic = view.groupby("temat")["cena_h"].median().dropna()
                if not by_topic.empty:
                    hbar(by_topic, "Mediana ceny za godzinę wg tematu", "zł / godz.")
                else:
                    st.caption("Brak cen – ustaw mapowanie pól cena / godziny w Diagnostyce API.")

            c3, c4 = st.columns(2)
            with c3:
                top = view.loc[view["dostawca"] != "", "dostawca"].value_counts()
                if not top.empty:
                    hbar(top, "Najaktywniejsi dostawcy (liczba usług)", "usługi", ",d")
            with c4:
                prices = view["cena_h"].dropna()
                if not prices.empty:
                    fig = px.histogram(prices.astype(float), nbins=25, title="Rozkład ceny za godzinę",
                                       labels={"value": "zł / godz."})
                    fig.update_traces(marker_color=ACCENT, marker_line_width=2, marker_line_color="white",
                                      hovertemplate="%{x} zł/h: %{y} usług<extra></extra>")
                    fig.update_layout(showlegend=False, yaxis_title="liczba usług", height=380,
                                      margin=dict(l=10, r=10, t=50, b=10))
                    st.plotly_chart(fig, use_container_width=True)

            st.subheader("💰 Porównaj swoją cenę")
            p1, p2 = st.columns([1, 3])
            moja = p1.number_input("Twoja cena za godzinę (zł)", 0.0, 2000.0, 100.0, step=5.0)
            pct = normalize.price_percentile(view["cena_h"], moja)
            if pct is None:
                p2.info("Brak cen w wybranym zakresie.")
            else:
                p2.markdown(
                    f"Przy **{moja:.0f} zł/h** jesteś droższy niż **{pct:.0f}%** ofert w wybranym zakresie "
                    f"(mediana: {med_h:.0f} zł/h, kwartyle: {view['cena_h'].quantile(.25):.0f}–"
                    f"{view['cena_h'].quantile(.75):.0f} zł/h)."
                )

            st.subheader("📋 Usługi")
            show = view[["tytul", "dostawca", "wojewodztwo", "forma", "data_od", "godziny", "cena", "cena_h",
                         "temat", "link"]].sort_values("data_od")
            st.dataframe(
                show, use_container_width=True, hide_index=True,
                column_config={
                    "tytul": "Tytuł", "dostawca": "Dostawca", "wojewodztwo": "Województwo", "forma": "Forma",
                    "data_od": st.column_config.DateColumn("Start", format="YYYY-MM-DD"),
                    "godziny": st.column_config.NumberColumn("Godz.", format="%d"),
                    "cena": st.column_config.NumberColumn("Cena (zł)", format="%.0f"),
                    "cena_h": st.column_config.NumberColumn("zł/godz.", format="%.0f"),
                    "temat": "Temat",
                    "link": st.column_config.LinkColumn("Karta usługi", display_text="otwórz"),
                },
            )
            st.download_button("⬇️ Pobierz CSV", show.to_csv(index=False, sep=";").encode("utf-8-sig"),
                               "bur_uslugi.csv", "text/csv")

# ── JAK SPRZEDAWAĆ ───────────────────────────────────────────
with tab_sprzedaz:
    st.markdown("Lista kontrolna dla dostawcy szkoleń IT. Zaznaczaj, co już masz – "
                "postęp zapisuje się do końca sesji. **Zasady BUR i operatorów się zmieniają:** "
                "przed decyzją sprawdź aktualny Regulamin BUR i regulamin naboru operatora.")
    total = sum(len(s["punkty"]) for s in poradnik.SEKCJE)
    done = sum(bool(st.session_state.get(f"chk_{i}_{j}"))
               for i, s in enumerate(poradnik.SEKCJE) for j in range(len(s["punkty"])))
    st.progress(done / total, text=f"Gotowe: {done} z {total}")
    for i, sekcja in enumerate(poradnik.SEKCJE):
        with st.expander(sekcja["tytul"], expanded=(i == 0)):
            for j, (punkt, wskazowka) in enumerate(sekcja["punkty"]):
                st.checkbox(punkt, key=f"chk_{i}_{j}")
                if wskazowka:
                    st.caption(f"↳ {wskazowka}")
    st.subheader("🔗 Przydatne linki")
    for nazwa, url in poradnik.LINKI:
        st.markdown(f"- [{nazwa}]({url})")

# ── DIAGNOSTYKA ──────────────────────────────────────────────
with tab_diag:
    st.markdown("Jeśli pobieranie nie działa albo kolumny są puste, tu sprawdzisz schemat API, "
                "przetestujesz zapytanie i ręcznie wskażesz, która kolumna jest czym.")

    cfg = st.session_state.get("api_cfg")
    if cfg:
        d1, d2 = st.columns(2)
        if d1.button("📜 Pobierz schemat API (lista endpointów)"):
            schema = api.BurClient(api_key=cfg["key"], base_url=cfg["base"]).schema()
            if schema:
                st.session_state["schema"] = schema
            else:
                st.error("Nie udało się pobrać schematu – otwórz dokumentację w przeglądarce: "
                         "https://uslugirozwojowe.parp.gov.pl/api/")
        if st.session_state.get("schema"):
            st.dataframe(pd.DataFrame(api.schema_paths(st.session_state["schema"])),
                         use_container_width=True, hide_index=True)

        if st.button("🔑 Testuj logowanie"):
            client = api.BurClient(api_key=cfg["key"], email=cfg["email"], base_url=cfg["base"],
                                   auth_path=cfg["auth_path"], auth_body=cfg["auth_body"])
            try:
                client.authenticate()
                st.success(client.auth_log or "Token uzyskany.")
            except (api.BurApiError, OSError) as exc:
                st.error(str(exc))

        st.markdown("**Testowe zapytanie GET**")
        t1, t2 = st.columns([2, 3])
        test_path = t1.text_input("Ścieżka", api.DEFAULT_SERVICES_PATH, key="test_path")
        test_params = t2.text_input("Parametry (JSON)", '{"strona": 1, "iloscNaStronie": 5}', key="test_params")
        if st.button("▶️ Wyślij"):
            try:
                client = api.BurClient(api_key=cfg["key"], email=cfg["email"], base_url=cfg["base"],
                                       auth_path=cfg["auth_path"], auth_body=cfg["auth_body"])
                st.json(client.get(test_path, json.loads(test_params or "{}")))
            except (api.BurApiError, OSError, json.JSONDecodeError) as exc:
                st.error(str(exc))
    else:
        st.caption("Wybierz „API BUR” w panelu bocznym, aby testować zapytania.")

    st.markdown("**Mapowanie pól**")
    if raw.empty:
        st.caption("Najpierw wczytaj dane.")
    else:
        opts = ["—"] + list(raw.columns)
        labels = {"id": "ID usługi", "tytul": "Tytuł", "dostawca": "Dostawca", "wojewodztwo": "Województwo",
                  "miejscowosc": "Miejscowość", "cena": "Cena całkowita", "cena_h": "Cena za godzinę",
                  "godziny": "Liczba godzin", "data_od": "Data rozpoczęcia", "data_do": "Data zakończenia",
                  "forma": "Forma", "kategoria": "Kategoria", "dofinansowanie": "Dofinansowanie / projekt"}
        grid = st.columns(3)
        new_mapping = {}
        for n, canon in enumerate(normalize.CANONICAL):
            current = mapping.get(canon)
            choice = grid[n % 3].selectbox(labels[canon], opts,
                                           index=opts.index(current) if current in opts else 0,
                                           key=f"map_{canon}_{hash(cols_sig)}")
            new_mapping[canon] = None if choice == "—" else choice
        if new_mapping != mapping:
            st.session_state["mapping"] = new_mapping
            st.rerun()
        with st.expander("Podgląd surowych danych (5 rekordów)"):
            st.dataframe(raw.head(), use_container_width=True)

st.divider()
st.caption("BUR Monitor · dane: API Bazy Usług Rozwojowych (PARP) · aplikacja nie jest produktem PARP")
