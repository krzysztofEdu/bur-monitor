"""Klient API Bazy Usług Rozwojowych (BUR) – PARP.

Dokumentacja (Swagger): https://uslugirozwojowe.parp.gov.pl/api/
Klucz autoryzacyjny generuje się w profilu BUR, w sekcji „Dostęp do API”.

Dokładne ścieżki endpointów i sposób logowania mogą się zmieniać, dlatego
wszystko jest konfigurowalne (secrets.toml / zmienne środowiskowe / panel boczny),
a zakładka „Diagnostyka API” pozwala podejrzeć schemat i przetestować zapytanie.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_BASE_URL = "https://uslugirozwojowe.parp.gov.pl/api"
DEFAULT_AUTH_PATH = "/autoryzacja/logowanie"
DEFAULT_SERVICES_PATH = "/usluga"
SCHEMA_CANDIDATES = ("/schemat.json", "/schema.json", "/openapi.json", "/swagger.json", "/doc.json")

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
    timeout: int = 30
    session: requests.Session = field(default_factory=requests.Session)
    _token: str | None = None

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    def authenticate(self) -> str:
        """Zwraca token Bearer. Bez ścieżki logowania używa klucza wprost."""
        if self._token:
            return self._token
        if not self.api_key:
            raise BurApiError("Brak klucza API – uzupełnij BUR_API_KEY.")
        if not self.auth_path:
            self._token = self.api_key
            return self._token
        body = {
            "email": self.email,
            "nazwaUzytkownika": self.email,
            "kluczAutoryzacyjny": self.api_key,
        }
        resp = self.session.post(self._url(self.auth_path), json=body, timeout=self.timeout)
        if resp.status_code >= 400:
            raise BurApiError(
                f"Logowanie nie powiodło się ({resp.status_code}) pod {self._url(self.auth_path)}: "
                f"{resp.text[:300]}"
            )
        try:
            payload = resp.json()
        except ValueError:
            payload = resp.text
        token = find_token(payload)
        if not token:
            raise BurApiError(f"Odpowiedź logowania nie zawiera tokenu: {str(payload)[:300]}")
        self._token = token
        return token

    def get(self, path: str, params: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.authenticate()}", "Accept": "application/json"}
        resp = self.session.get(self._url(path), params=params or {}, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise BurApiError(f"GET {resp.url} → {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise BurApiError(f"GET {resp.url} nie zwrócił JSON: {resp.text[:200]}") from exc

    def fetch_all(
        self,
        path: str,
        params: dict | None = None,
        page_param: str = "strona",
        size_param: str = "iloscNaStronie",
        page_size: int = 100,
        start_page: int = 1,
        max_pages: int = 20,
        progress=None,
    ) -> list[dict]:
        """Pobiera kolejne strony, aż zabraknie danych lub osiągnięty zostanie limit."""
        records: list[dict] = []
        seen_first: set[str] = set()
        for i in range(max_pages):
            query = dict(params or {})
            if page_param:
                query[page_param] = start_page + i
            if size_param:
                query[size_param] = page_size
            batch = extract_records(self.get(path, query))
            if not batch:
                break
            # Zabezpieczenie: API ignoruje parametr strony → ta sama strona w kółko.
            fingerprint = json.dumps(batch[0], sort_keys=True, default=str)
            if fingerprint in seen_first:
                break
            seen_first.add(fingerprint)
            records.extend(batch)
            if progress:
                progress(i + 1, len(records))
            if not page_param or len(batch) < page_size:
                break
        return records

    def schema(self) -> dict | None:
        """Próbuje pobrać schemat OpenAPI (nie wymaga tokenu)."""
        for candidate in SCHEMA_CANDIDATES:
            try:
                resp = self.session.get(self._url(candidate), timeout=self.timeout)
                if resp.ok and "json" in resp.headers.get("content-type", ""):
                    return resp.json()
            except requests.RequestException:
                continue
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
