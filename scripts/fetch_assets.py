#!/usr/bin/env python
"""Download existing Glaceon assets without generating or modifying artwork."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "external"
CATALOG_PATH = ASSETS / "asset_catalog.json"
USER_AGENT = "GlaceonCompanion/0.1 (personal non-commercial asset catalog)"
GITHUB_API = "https://api.github.com/repos/PMDCollab/SpriteCollab/contents/"
PMD_RAW_ROOT = "https://raw.githubusercontent.com/PMDCollab/SpriteCollab/master/"


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def request_bytes(url: str, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urlopen(request, timeout=40) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {last_error}")


def request_json(url: str) -> Any:
    return json.loads(request_bytes(url).decode("utf-8"))


def safe_relative(value: str) -> Path:
    parts = [part for part in Path(unquote(value)).parts if part not in {"", ".", "..", "/"}]
    return Path(*parts)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Catalog:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.errors: list[dict[str, str]] = []
        self._seen_urls: set[str] = set()

    def save(
        self,
        url: str,
        relative_path: Path,
        source: str,
        variant: str,
        source_page: str,
        license_note: str,
        credit: str = "",
    ) -> None:
        if url in self._seen_urls:
            return
        self._seen_urls.add(url)
        try:
            output = ASSETS / relative_path
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists() and output.stat().st_size:
                data = output.read_bytes()
            else:
                data = request_bytes(url)
                output.write_bytes(data)
            self.items.append(
                {
                    "source": source,
                    "variant": variant,
                    "file": output.relative_to(ROOT).as_posix(),
                    "url": url,
                    "source_page": source_page,
                    "license_note": license_note,
                    "credit": credit,
                    "bytes": len(data),
                    "sha256": sha256(data),
                }
            )
            print(f"[{source}] {relative_path}")
        except Exception as exc:
            self.errors.append({"url": url, "error": str(exc)})
            print(f"ERROR {url}: {exc}", file=sys.stderr)

    def write(self) -> None:
        ASSETS.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_art": False,
            "scope": "Existing Glaceon and interaction assets discovered from public repositories/sites.",
            "items": sorted(self.items, key=lambda item: (item["source"], item["file"])),
            "errors": self.errors,
            "source_notes": {
                "PMDCollab": "Community additions are CC BY-NC 4.0; official Chunsoft sprites retain their original rights. Credits are included beside every downloaded set.",
                "PokeAPI": "Repository aggregator. Pokémon images, names and cries remain property of their respective rights holders; see upstream sprite/cries notices.",
                "PokemonShowdown": "Mixture of official and Smogon-community battle sprites; provenance varies by directory.",
                "SpritersResource": "Original game rips and custom submissions. Personal project use only; do not redistribute without checking each submitter/source.",
                "WikimediaCommons": "CC0 pixel-art lemon by 7Soul1 from the 420 Pixel Art Icons for RPG collection.",
                "OpenGameArt": "CC0 pixel-art bed by ArlanTR.",
            },
        }
        CATALOG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nCatálogo: {CATALOG_PATH}")
        print(f"Archivos: {len(self.items)} | Errores: {len(self.errors)}")


def flatten_urls(value: Any, prefix: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from flatten_urls(item, f"{prefix}/{key}" if prefix else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from flatten_urls(item, f"{prefix}/{index}")
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        yield prefix, value


def fetch_pokeapi(catalog: Catalog) -> None:
    endpoint = "https://pokeapi.co/api/v2/pokemon/glaceon"
    data = request_json(endpoint)
    for label, url in flatten_urls(data.get("sprites", {})):
        parsed = urlparse(url)
        marker = "/sprites/"
        path_text = parsed.path.split(marker, 1)[-1] if marker in parsed.path else parsed.path.lstrip("/")
        relative = Path("pokeapi") / safe_relative(path_text)
        catalog.save(
            url,
            relative,
            "PokeAPI",
            label,
            "https://github.com/PokeAPI/sprites",
            "Aggregator; rights remain with Pokémon/Nintendo/Game Freak/Creatures and listed fan artists.",
        )
    for label, url in flatten_urls(data.get("cries", {})):
        suffix = Path(urlparse(url).path).suffix or ".ogg"
        catalog.save(
            url,
            Path("pokeapi") / "cries" / f"glaceon-{label}{suffix}",
            "PokeAPI",
            f"cry-{label}",
            "https://github.com/PokeAPI/cries",
            "Existing Pokémon cry; audio remains copyright The Pokémon Company. Personal local use only.",
        )


def fetch_interaction_props(catalog: Catalog) -> None:
    catalog.save(
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/oran-berry.png",
        Path("props") / "oran-berry.png",
        "PokeAPI",
        "item-oran-berry",
        "https://github.com/PokeAPI/sprites/blob/master/sprites/items/oran-berry.png",
        "Pokémon item artwork; copyright The Pokémon Company. Personal local use only.",
    )
    catalog.save(
        "https://upload.wikimedia.org/wikipedia/commons/b/b2/I_C_Lemon.png",
        Path("props") / "lemon.png",
        "WikimediaCommons",
        "lemon-pixel-art",
        "https://commons.wikimedia.org/wiki/File:I_C_Lemon.png",
        "CC0 1.0 Universal.",
        "7Soul1, 420 Pixel Art Icons for RPG.",
    )
    catalog.save(
        "https://opengameart.org/sites/default/files/bed_4.png",
        Path("props") / "bed.png",
        "OpenGameArt",
        "bed-pixel-art",
        "https://opengameart.org/content/bed-pixel-art",
        "CC0 1.0 Universal.",
        "ArlanTR.",
    )


def github_files(path: str) -> list[dict[str, Any]]:
    try:
        payload = request_json(GITHUB_API + path)
    except RuntimeError:
        return []
    if isinstance(payload, dict) and payload.get("type") == "file":
        return [payload]
    files: list[dict[str, Any]] = []
    for item in payload:
        if item.get("type") == "file":
            files.append(item)
        elif item.get("type") == "dir":
            files.extend(github_files(item["path"]))
    return files


def fetch_pmd(catalog: Catalog) -> None:
    groups = {
        "default": "sprite/0471",
        "shiny": "sprite/0471/0000/0001",
        "altcolor": "sprite/0471/0001",
        "portraits-default": "portrait/0471",
        "portraits-shiny": "portrait/0471/0000/0001",
        "portraits-altcolor": "portrait/0471/0001",
        "portraits-alternate": "portrait/0471/0002",
        "portraits-alternate-shiny": "portrait/0471/0002/0001",
    }
    for variant, path in groups.items():
        # Avoid recursively re-downloading nested variants from the parent folder.
        api_url = GITHUB_API + path
        try:
            payload = request_json(api_url)
        except RuntimeError:
            continue
        files = [item for item in payload if item.get("type") == "file"]
        for item in files:
            url = item.get("download_url") or (PMD_RAW_ROOT + item["path"])
            relative = Path("pmd") / variant / item["name"]
            catalog.save(
                url,
                relative,
                "PMDCollab",
                variant,
                "https://github.com/PMDCollab/SpriteCollab/tree/master/" + path,
                "CC BY-NC 4.0 for community additions; official Chunsoft assets retain original rights.",
                "See credits.txt in the same variant directory.",
            )


def parse_links(url: str) -> list[str]:
    parser = LinkParser()
    parser.feed(request_bytes(url).decode("utf-8", errors="replace"))
    return parser.links


def links_from_html(html: str) -> list[str]:
    parser = LinkParser()
    parser.feed(html)
    return parser.links


def fetch_showdown(catalog: Catalog) -> None:
    root = "https://play.pokemonshowdown.com/sprites/"
    directories = []
    for href in parse_links(root):
        full = urljoin(root, href)
        parsed = urlparse(full)
        name = parsed.path.rstrip("/").split("/")[-1]
        is_directory = href.startswith("./") and not href.startswith("./?") and not Path(name).suffix
        if full.startswith(root) and is_directory and name not in {"sprites", ""}:
            directories.append((name, full.rstrip("/") + "/"))

    def discover(item: tuple[str, str]) -> tuple[str, str, list[str]]:
        name, url = item
        try:
            matches = [
                urljoin(url, href)
                for href in parse_links(url)
                if "glaceon" in Path(unquote(urlparse(href).path)).name.lower()
                and urlparse(href).path.lower().endswith((".gif", ".png", ".webp"))
            ]
            return name, url, matches
        except Exception:
            return name, url, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(discover, item) for item in sorted(set(directories))]
        for future in as_completed(futures):
            directory, page, matches = future.result()
            for url in matches:
                filename = Path(unquote(urlparse(url).path)).name
                catalog.save(
                    url,
                    Path("showdown") / directory / filename,
                    "PokemonShowdown",
                    directory,
                    page,
                    "Upstream mix of official and Smogon community sprites; verify provenance before redistribution.",
                )


def fetch_spriters_resource(catalog: Catalog) -> None:
    browse = "https://www.spriters-resource.com/browse/?tags%5B3%5D%5B0%5D=21181"
    asset_links = sorted(
        {
            urljoin(browse, href)
            for href in parse_links(browse)
            if re.fullmatch(r"/[a-z0-9_]+/[a-z0-9_]+/asset/\d+/", urlparse(href).path)
        }
    )
    for page in asset_links:
        asset_id = urlparse(page).path.rstrip("/").split("/")[-1]
        try:
            html = request_bytes(page).decode("utf-8", errors="replace")
            if "21181" not in html or "Glaceon" not in html:
                continue
            media = [
                urljoin(page, href)
                for href in links_from_html(html)
                if urlparse(href).path.startswith("/media/assets/")
            ]
        except Exception as exc:
            catalog.errors.append({"url": page, "error": str(exc)})
            continue
        for index, url in enumerate(sorted(set(media))):
            suffix = Path(urlparse(url).path).suffix or ".bin"
            catalog.save(
                url,
                Path("spriters-resource") / f"asset-{asset_id}-{index}{suffix}",
                "SpritersResource",
                f"asset-{asset_id}",
                page,
                "Personal use only in this project; consult the asset page and original rights holder before redistribution.",
            )


def main() -> int:
    catalog = Catalog()
    ASSETS.mkdir(parents=True, exist_ok=True)
    for step in (
        fetch_pmd,
        fetch_pokeapi,
        fetch_interaction_props,
        fetch_showdown,
        fetch_spriters_resource,
    ):
        print(f"\n== {step.__name__} ==")
        try:
            step(catalog)
        except Exception as exc:
            catalog.errors.append({"url": step.__name__, "error": str(exc)})
            print(f"ERROR en {step.__name__}: {exc}", file=sys.stderr)
    catalog.write()
    return 0 if not catalog.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
