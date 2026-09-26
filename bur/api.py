"""Klient API Bazy Usług Rozwojowych (BUR) – PARP.

Dokumentacja (Swagger): https://uslugirozwojowe.parp.gov.pl/api/
Klucz autoryzacyjny generuje się w profilu BUR, w sekcji „Dostęp do API”.

Dokładne ścieżki endpointów i sposób logowania mogą się zmieniać, dlatego
wszystko jest konfigurowalne (secrets.toml / zmienne środowiskowe / panel boczny),
a zakładka „Diagnostyka API” pozwala podejrzeć schemat i przetestować zapytanie.
"""

from __future__ import annotations

import json
import time
import math
import re
from dataclasses import dataclass, field
from typing import Any

import requests
from urllib.parse import urljoin

DEFAULT_BASE_URL = "https://uslugirozwojowe.parp.gov.pl/api"
DEFAULT_AUTH_PATH = "/autoryzacja/logowanie"
DEFAULT_SERVICES_PATH = "/usluga"
SCHEMA_CANDIDATES = ("/schemat.json", "/schema.json", "/openapi.json", "/swagger.json", "/doc.json",
                     "/docs.json", "/api-docs", "/v3/api-docs", "/swagger/v1/swagger.json", "/doc/schemat.json")

# Klucze, pod którymi API zwykle zwraca listę rekordów w odpowiedzi stronicowanej.
LIST_KEYS = ("data", "items", "lista", "wyniki", "rekordy", "content", "results", "uslugi", "elementy")
TOKEN_KEYS = ("token", "access_token", "accessToken", "jwt", "id_token")


class BurApiError(RuntimeError):
    pass


def extract_records(payload: Any) -> list[dict]:
    """Wyciąga listę rekordów z odpowiedzi API niezależnie od jej opakowania."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for key in LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
        if isinstance(value, dict):
            nested = extract_records(value)
            if nested:
                return nested
    # Pierwsza wartość będąca listą słowników.
    for value in payload.values():
        if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
            return value
    for value in payload.values():
        if isinstance(value, dict):
            nested = extract_records(value)
            if nested:
                return nested
    return []


_PAGES_KEY = re.compile(r"(liczba|ilosc|total|count).*(stron|pages)|^(stron|pages)$|lastpage|ostatniastrona")
_TOTAL_KEY = re.compile(r"(liczba|ilosc|total|count).*(wszyst|element|rekord|wynik|uslug|items|records|elements)"
                        r"|^(total|count|totalcount)$")


# Numery województw w API BUR (parametr idWojewodztwa) – kolejność alfabetyczna; potwierdzone na danych:
# lubuskie=4, mazowieckie=7, śląskie=12.
WOJEWODZTWO_ID = {
    "dolnośląskie": 1, "kujawsko-pomorskie": 2, "lubelskie": 3, "lubuskie": 4, "łódzkie": 5,
    "małopolskie": 6, "mazowieckie": 7, "opolskie": 8, "podkarpackie": 9, "podlaskie": 10,
    "pomorskie": 11, "śląskie": 12, "świętokrzyskie": 13, "warmińsko-mazurskie": 14,
    "wielkopolskie": 15, "zachodniopomorskie": 16,
}

PAGE_PARAM_CANDIDATES = ["strona", "numerStrony", "nrStrony", "page", "pageNumber", "p"]
SIZE_PARAM_CANDIDATES = ["iloscNaStronie", "liczbaNaStronie", "rozmiarStrony", "liczbaElementow",
                         "limit", "size", "pageSize", "perPage", "per_page"]


def _fp(batch: list[dict]) -> str:
    """Odcisk strony – do wykrywania, czy dwie odpowiedzi to ta sama strona."""
    return json.dumps(batch[0], sort_keys=True, default=str) if batch else ""


def page_meta(payload: Any, page_size: int) -> dict:
    """Szuka w odpowiedzi informacji o stronicowaniu: liczby stron lub wszystkich rekordów."""
    meta: dict = {}

    def walk(obj: Any, depth: int = 0) -> None:
        if not isinstance(obj, dict) or depth > 2:
            return
        for key, value in obj.items():
            k = re.sub(r"[^a-z]", "", key.lower())
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value >= 0:
                if "pages" not in meta and _PAGES_KEY.search(k):
                    meta["pages"] = int(value)
                    meta["pages_key"] = key
                elif "total" not in meta and _TOTAL_KEY.search(k):
                    meta["total"] = int(value)
                    meta["total_key"] = key
            elif isinstance(value, dict):
                walk(value, depth + 1)

    walk(payload)
    if "pages" not in meta and meta.get("total") and page_size:
        meta["pages"] = math.ceil(meta["total"] / page_size)
    return meta


def find_token(payload: Any) -> str | None:
    """Szuka tokenu w (zagnieżdżonej) odpowiedzi logowania."""
    if isinstance(payload, str) and payload.strip():
        return payload.strip().strip('"')
    if isinstance(payload, dict):
        for key in TOKEN_KEYS:
            if isinstance(payload.get(key), str) and payload[key]:
                return payload[key]
        for value in payload.values():
            token = find_token(value) if isinstance(value, dict) else None
            if token:
                return token
    return None


@dataclass
class BurClient:
    api_key: str
    email: str = ""
    base_url: str = DEFAULT_BASE_URL
    auth_path: str = DEFAULT_AUTH_PATH
    auth_body: str = ""  # szablon JSON, np. '{"nazwaUzytkownika": "{email}", "kluczAutoryzacyjny": "{key}"}'
    timeout: int = 30
    session: requests.Session = field(default_factory=requests.Session)
    _token: str | None = None
    auth_log: str = ""
    fetch_info: dict = field(default_factory=dict)
    sleep: Any = field(default=time.sleep, repr=False)

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    def _auth_bodies(self) -> list[dict]:
        """Warianty treści logowania – własny szablon (auth_body) ma pierwszeństwo."""
        if self.auth_body:
            filled = self.auth_body.replace("{email}", self.email).replace("{key}", self.api_key)
            try:
                return [json.loads(filled)]
            except json.JSONDecodeError as exc:
                raise BurApiError(f"BUR_AUTH_BODY nie jest poprawnym JSON: {exc}") from exc
        key, email = self.api_key, self.email
        bodies = [
            {"nazwaUzytkownika": email, "kluczAutoryzacyjny": key},
            {"email": email, "kluczAutoryzacyjny": key},
            {"login": email, "kluczAutoryzacyjny": key},
            {"kluczAutoryzacyjny": key},
            {"klucz": key},
            {"apiKey": key},
        ]
        return [b for b in bodies if email or len(b) == 1]

    def authenticate(self) -> str:
        """Zwraca token Bearer. Bez ścieżki logowania używa klucza wprost.

        Próbuje kolejnych wariantów treści logowania; jeśli żaden nie zadziała,
        zgłasza błąd z odpowiedzią serwera dla każdej próby.
        """
        if self._token:
            return self._token
        if not self.api_key:
            raise BurApiError("Brak klucza API – uzupełnij BUR_API_KEY.")
        if not self.auth_path:
            self._token = self.api_key
            return self._token
        url = self._url(self.auth_path)
        attempts = []
        for body in self._auth_bodies():
            resp = self.session.post(url, json=body, timeout=self.timeout)
            fields = ", ".join(body)
            if resp.status_code >= 400:
                attempts.append(f"• pola [{fields}] → {resp.status_code}: {resp.text[:160]}")
                continue
            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text
            token = find_token(payload)
            if token:
                self._token = token
                self.auth_log = f"Zalogowano (pola: {fields})."
                return token
            attempts.append(f"• pola [{fields}] → {resp.status_code}, brak tokenu: {str(payload)[:160]}")
        hint = "" if self.email else " Uzupełnij też e-mail konta BUR (BUR_API_EMAIL)."
        raise BurApiError(
            f"Logowanie nie powiodło się pod {url}.{hint}\n"
            + "\n".join(attempts)
            + "\nSprawdź w dokumentacji (https://uslugirozwojowe.parp.gov.pl/api/) pola endpointu logowania "
              "i wpisz je jako szablon BUR_AUTH_BODY."
        )

    def get(self, path: str, params: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.authenticate()}", "Accept": "application/json"}
        try:
            resp = self.session.get(self._url(path), params=params or {}, headers=headers, timeout=self.timeout)
        except requests.Timeout as exc:
            self.fetch_info["timeouts"] = self.fetch_info.get("timeouts", 0) + 1
            raise BurApiError(f"GET {self._url(path)} {params or ''} → brak odpowiedzi w {self.timeout} s") from exc
        except requests.RequestException as exc:
            raise BurApiError(f"GET {self._url(path)} → błąd połączenia: {exc}") from exc
        if resp.status_code >= 400:
            raise BurApiError(f"GET {resp.url} → {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise BurApiError(f"GET {resp.url} nie zwrócił JSON: {resp.text[:200]}") from exc

    # ── stronicowanie ─────────────────────────────────────────
    def _page(self, path: str, params: dict, tolerant: bool = True, retries: int = 0,
              probe: bool = False) -> list[dict] | None:
        """Jedna strona: lista rekordów, [] gdy strona pusta, None gdy API zwróciło błąd.

        Przy tolerant błąd nie przerywa pobierania (BUR odpowiada 500 m.in. na nieznany parametr).
        retries > 0 ponawia zapytanie po krótkiej przerwie – na chwilowe błędy / limit zapytań.
        probe = próba nazwy parametru: błąd jest spodziewany, więc nie trafia do listy błędów.
        """
        for attempt in range(retries + 1):
            self.fetch_info["requests"] = self.fetch_info.get("requests", 0) + 1
            try:
                return extract_records(self.get(path, params))
            except BurApiError as exc:
                if not tolerant:
                    raise
                if attempt == retries:
                    if probe:
                        self.fetch_info["probe_errors"] = self.fetch_info.get("probe_errors", 0) + 1
                        return None
                    errors = self.fetch_info.setdefault("errors", [])
                    if len(errors) < 50:
                        errors.append(str(exc)[:240])
                    return None
                self.sleep(1.5 * (attempt + 1))
        return None

    def detect_paging(self, path: str, params: dict, page_candidates: list[str],
                      size_candidates: list[str], page_size: int) -> dict:
        """Sprawdza, które nazwy parametrów strony i rozmiaru API faktycznie respektuje."""
        base = self._page(path, params, tolerant=False)
        info = {"page_param": "", "size_param": "", "size": len(base), "start": 1, "base_fp": _fp(base)}
        if not base:
            return info
        for cand in size_candidates:
            want = page_size if page_size != len(base) else page_size + 7
            got = self._page(path, {**params, cand: want}, probe=True)
            if got and len(got) != len(base):
                info["size_param"], info["size"] = cand, len(got)
                break
        sized = {**params, info["size_param"]: info["size"]} if info["size_param"] else dict(params)
        first = self._page(path, sized) if info["size_param"] else base
        for cand in page_candidates:
            p2 = self._page(path, {**sized, cand: 2}, probe=True)
            if p2 and _fp(p2) != _fp(first):
                info["page_param"] = cand
                # Numeracja od 0 tylko wtedy, gdy strona 1 to NA PEWNO coś innego niż pierwsza strona;
                # błąd przy stronie 1 nie może tego przesądzić.
                p1 = self._page(path, {**sized, cand: 1}, retries=2)
                p0 = self._page(path, {**sized, cand: 0}, retries=1) if p1 and _fp(p1) != _fp(first) else None
                info["start"] = 0 if p0 and _fp(p0) == _fp(first) else 1
                break
        return info

    def find_last_page(self, path: str, query, start: int, limit: int = 1 << 22) -> int:
        """Ostatnia niepusta strona: podwajanie numeru, potem wyszukiwanie binarne (~2·log2(N) zapytań)."""
        def exists(page: int) -> bool:
            batch = self._page(path, query(page))
            if self.fetch_info.get("timeouts", 0) >= 2:
                raise BurApiError(
                    f"BUR nie odpowiada w {self.timeout} s dla dalekich stron (np. strona {page}), więc nie da się "
                    "przewinąć do najnowszych usług. Potrzebny jest filtr lub sortowanie po stronie API: "
                    "w zakładce „🛠️ Diagnostyka API” kliknij „Pobierz schemat API” i pokaż parametry /usluga. "
                    "Na razie możesz odznaczyć „Najpierw najnowsze usługi”."
                )
            return bool(batch)

        lo, hi = start, start + 1
        while hi < limit and exists(hi):
            lo, hi = hi, hi * 2
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if exists(mid):
                lo = mid
            else:
                hi = mid
        return lo

    def fetch_all(
        self,
        path: str,
        params: dict | None = None,
        page_param: str = "auto",
        size_param: str = "auto",
        page_size: int = 100,
        start_page: int = 1,
        max_pages: int = 20,
        newest_first: bool = True,
        progress=None,
    ) -> list[dict]:
        """Pobiera usługi strona po stronie.

        page_param / size_param = "auto" → nazwy wykrywane spośród PAGE_PARAM_CANDIDATES /
        SIZE_PARAM_CANDIDATES. API BUR zwraca usługi od najstarszych, więc przy newest_first
        ustalana jest ostatnia strona (z metadanych albo wyszukiwaniem) i pobieranie idzie wstecz.
        Podsumowanie trafia do ``self.fetch_info``.
        """
        params = dict(params or {})
        self.fetch_info = {"newest_first": False, "pages": [], "requests": 0}

        if page_param == "auto" or size_param == "auto":
            detected = self.detect_paging(
                path, params,
                PAGE_PARAM_CANDIDATES if page_param == "auto" else [page_param] if page_param else [],
                SIZE_PARAM_CANDIDATES if size_param == "auto" else [size_param] if size_param else [],
                page_size,
            )
            page_param, size_param = detected["page_param"], detected["size_param"]
            page_size = detected["size"] or page_size
            if page_param:
                start_page = detected["start"]
            self.fetch_info["detected"] = {k: detected[k] for k in ("page_param", "size_param", "size", "start")}

        def query(page: int) -> dict:
            q = dict(params)
            if page_param:
                q[page_param] = page
            if size_param:
                q[size_param] = page_size
            return q

        first_payload = self.get(path, query(start_page))
        self.fetch_info["requests"] += 1
        meta = page_meta(first_payload, page_size)
        self.fetch_info["meta"] = meta

        if newest_first and page_param:
            if meta.get("pages", 0) > 1:
                last = start_page + meta["pages"] - 1
            else:
                last = self.find_last_page(path, query, start_page)
            self.fetch_info["last_page"] = last
            pages = range(last, max(start_page, last - max_pages + 1) - 1, -1)
            self.fetch_info["newest_first"] = last > start_page
        else:
            pages = range(start_page, start_page + max_pages)

        records: list[dict] = []
        seen_first: set[str] = set()
        failures = 0
        for i, page in enumerate(pages):
            batch = (extract_records(first_payload) if page == start_page
                     else self._page(path, query(page), retries=2))
            if batch is None:  # błąd API – pomiń stronę, ale nie w nieskończoność
                failures += 1
                if failures >= 5:
                    break
                continue
            if not batch:
                if self.fetch_info["newest_first"]:
                    continue  # ostatnia strona bywa pusta – idź dalej wstecz
                break
            # Zabezpieczenie: API ignoruje parametr strony → ta sama strona w kółko.
            fingerprint = _fp(batch)
            if fingerprint in seen_first:
                break
            seen_first.add(fingerprint)
            records.extend(batch)
            self.fetch_info["pages"].append(page)
            if progress:
                progress(i + 1, len(records))
            if not page_param:
                break
        return records

    def service_by_id(self, service_id: int, path: str = DEFAULT_SERVICES_PATH) -> dict | None:
        """Jedna usługa po ID (filtr ``id`` w /usluga) – np. żeby odczytać jej kategorię."""
        records = extract_records(self.get(path, {"id": int(service_id)}))
        return records[0] if records else None

    def schema(self) -> dict | None:
        """Pobiera schemat OpenAPI (bez tokenu): adres odczytany ze strony Swagger UI albo znane adresy."""
        urls: list[str] = []
        for page in ("/", "/swagger-initializer.js"):
            page_url = self._url(page)
            try:
                resp = self.session.get(page_url, timeout=self.timeout)
            except requests.RequestException:
                continue
            if resp.ok:
                found = re.findall(r"""url["']?\s*[:=]\s*["']([^"'\s]+\.json)["']""", resp.text)
                urls += [urljoin(page_url if page_url.endswith("/") else page_url + "/", u) for u in found]
        urls += [self._url(c) for c in SCHEMA_CANDIDATES]
        for url in dict.fromkeys(urls):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                data = resp.json() if resp.ok else None
            except (requests.RequestException, ValueError):
                continue
            if isinstance(data, dict) and "paths" in data:
                data["_zrodlo"] = url
                return data
        return None


def schema_paths(schema: dict) -> list[dict]:
    """Lista endpointów (metoda, ścieżka, opis, parametry) ze schematu OpenAPI."""
    rows = []
    for path, methods in (schema or {}).get("paths", {}).items():
        for method, spec in methods.items():
            if not isinstance(spec, dict):
                continue
            rows.append({
                "metoda": method.upper(),
                "ścieżka": path,
                "opis": spec.get("summary") or spec.get("description", ""),
                "parametry": ", ".join(p.get("name", "") for p in spec.get("parameters", []) if isinstance(p, dict)),
            })
    return rows


def schema_params(schema: dict, path_filter: str = "usluga") -> list[dict]:
    """Parametry zapytań GET dla ścieżek zawierających path_filter – z typem i opisem."""
    rows = []
    for path, methods in (schema or {}).get("paths", {}).items():
        if path_filter and path_filter not in path.lower():
            continue
        spec = methods.get("get") if isinstance(methods, dict) else None
        if not isinstance(spec, dict):
            continue
        for p in list(methods.get("parameters", [])) + list(spec.get("parameters", [])):
            if not isinstance(p, dict):
                continue
            if "$ref" in p:  # parametr zdefiniowany w components/parameters
                ref = p["$ref"].split("/")[-1]
                p = (schema.get("components", {}).get("parameters", {}).get(ref)
                     or schema.get("parameters", {}).get(ref) or {"name": ref})
            typ = (p.get("schema") or {}).get("type") or p.get("type", "")
            enum = (p.get("schema") or {}).get("enum") or p.get("enum")
            rows.append({
                "ścieżka": path, "parametr": p.get("name", ""), "gdzie": p.get("in", ""),
                "typ": typ + (f" {enum}" if enum else ""), "wymagany": bool(p.get("required")),
                "opis": (p.get("description") or "")[:300],
            })
    return rows
