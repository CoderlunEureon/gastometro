"""Download the yearly bulk files and the deputies list from the open data API."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

from . import config

log = logging.getLogger(__name__)

USER_AGENT = "Gastometro/0.1 (+https://github.com/; dados abertos CEAP)"
MANIFEST = "manifest.json"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def load_manifest(raw_dir: Path) -> dict:
    path = raw_dir / MANIFEST
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_manifest(raw_dir: Path, manifest: dict) -> None:
    (raw_dir / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def download_year(year: int, raw_dir: Path, session: requests.Session | None = None,
                  retries: int = 3) -> Path:
    """Download ``Ano-{year}.csv.zip`` unless the server copy is unchanged."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = session or _session()
    url = config.BULK_URL.format(year=year)
    target = raw_dir / f"Ano-{year}.csv.zip"
    manifest = load_manifest(raw_dir)
    entry = manifest.get(str(year), {})
    headers = {}
    if target.exists() and entry.get("last_modified"):
        headers["If-Modified-Since"] = entry["last_modified"]

    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=headers, stream=True, timeout=120)
            if resp.status_code == 304:
                log.info("%s: sem alterações (304)", target.name)
                return target
            resp.raise_for_status()
            tmp = target.with_suffix(".part")
            with tmp.open("wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
            tmp.replace(target)
            manifest[str(year)] = {
                "url": url,
                "last_modified": resp.headers.get("Last-Modified"),
                "etag": resp.headers.get("ETag"),
                "bytes": target.stat().st_size,
                "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            save_manifest(raw_dir, manifest)
            log.info("%s: %.1f MB baixados", target.name, target.stat().st_size / 1e6)
            return target
        except requests.RequestException as exc:
            log.warning("falha ao baixar %s (tentativa %d): %s", url, attempt, exc)
            if attempt == retries:
                if target.exists():
                    log.warning("usando cópia local existente de %s", target.name)
                    return target
                raise
            time.sleep(5 * attempt)
    return target


def download_deputies(raw_dir: Path, legislature: int = config.LEGISLATURE,
                      session: requests.Session | None = None) -> Path | None:
    """Fetch the deputies of a legislature (id, name, party, UF, photo).

    Optional enrichment: if the API is down the pipeline keeps going with the
    data from the CSV and the conventional photo URL.
    """
    session = session or _session()
    target = raw_dir / f"deputados-{legislature}.json"
    url = f"{config.API_URL}/deputados"
    params = {"idLegislatura": legislature, "itens": 100, "ordem": "ASC", "ordenarPor": "nome"}
    items: list[dict] = []
    try:
        page = 1
        while True:
            resp = session.get(url, params={**params, "pagina": page},
                               headers={"Accept": "application/json"}, timeout=60)
            resp.raise_for_status()
            data = resp.json().get("dados", [])
            items.extend(data)
            if len(data) < params["itens"]:
                break
            page += 1
        # Current members (em exercício) to tell who is sitting today.
        resp = session.get(url, params={"itens": 1000}, headers={"Accept": "application/json"},
                           timeout=60)
        resp.raise_for_status()
        current = {d["id"] for d in resp.json().get("dados", [])}
    except requests.RequestException as exc:
        log.warning("API de deputados indisponível (%s); seguindo sem enriquecimento", exc)
        return target if target.exists() else None
    payload = {"deputados": items, "em_exercicio": sorted(current)}
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log.info("API: %d registros de deputados, %d em exercício", len(items), len(current))
    return target
