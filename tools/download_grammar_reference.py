#!/usr/bin/env python3
"""Download an offline copy of the Bashkir grammar references.

The crawler is intentionally restricted to the two grammar directories.  It
keeps the remote directory layout, so the original relative links also work in
the downloaded copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "grammar-reference"
HOST = "212.193.134.139"
REMOTE_BASE_PATH = "/mfbl/res/bashdb/"
START_URLS = (
    "http://212.193.134.139/mfbl/res/bashdb/gram/gram.html",
    "http://212.193.134.139/mfbl/res/bashdb/algram/algram.htm",
)
ALLOWED_PREFIXES = (
    "/mfbl/res/bashdb/gram/",
    "/mfbl/res/bashdb/algram/",
)
PAGE_SUFFIXES = {".htm", ".html", ".shtm", ".shtml"}
USER_AGENT = "bashspell-grammar-archiver/1.0"
CHARSET_RE = re.compile(
    rb"charset\s*=\s*['\"]?\s*([a-zA-Z0-9._-]+)", re.IGNORECASE
)
CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^)'\"]+)", re.IGNORECASE)


@dataclass(frozen=True)
class DownloadedFile:
    url: str
    path: str
    content_type: str
    size: int
    sha256: str


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    content: bytes
    content_type: str
    charset: str | None


class ReferenceParser(HTMLParser):
    """Collect navigation links and page assets from old, Word-generated HTML."""

    PAGE_ATTRIBUTES = {"a": "href", "area": "href", "frame": "src", "iframe": "src"}
    ASSET_ATTRIBUTES = {
        "audio": "src",
        "embed": "src",
        "img": "src",
        "input": "src",
        "link": "href",
        "object": "data",
        "script": "src",
        "source": "src",
        "track": "src",
        "video": "src",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base_href: str | None = None
        self.page_links: list[str] = []
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        tag = tag.lower()
        if tag == "base" and values.get("href"):
            self.base_href = values["href"]
        if tag in self.PAGE_ATTRIBUTES:
            value = values.get(self.PAGE_ATTRIBUTES[tag])
            if value:
                self.page_links.append(value)
        if tag in self.ASSET_ATTRIBUTES:
            value = values.get(self.ASSET_ATTRIBUTES[tag])
            # Word 2002 generated one of these references for nearly every
            # page, but the files were never published on the source server.
            is_missing_word_manifest = (
                tag == "link" and values.get("rel", "").lower() == "file-list"
            )
            if value and not is_missing_word_manifest:
                self.assets.append(value)
        if values.get("background"):
            self.assets.append(values["background"])
        if values.get("style"):
            self.assets.extend(CSS_URL_RE.findall(values["style"]))

    handle_startendtag = handle_starttag


def canonical_url(url: str) -> str:
    return urldefrag(url)[0]


def is_allowed(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme in {"http", "https"}
        and parts.hostname == HOST
        and any(parts.path.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    )


def is_page(url: str) -> bool:
    suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
    return not suffix or suffix in PAGE_SUFFIXES


def decode_html(content: bytes, declared_charset: str | None) -> str:
    encodings: list[str] = []
    if declared_charset:
        encodings.append(declared_charset)
    match = CHARSET_RE.search(content[:8192])
    if match:
        encodings.append(match.group(1).decode("ascii", errors="ignore"))
    encodings.extend(["utf-8", "windows-1251", "latin-1"])
    for encoding in dict.fromkeys(encodings):
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("latin-1", errors="replace")


def fetch(url: str, attempts: int = 3) -> FetchResult:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=30) as response:
                content = response.read()
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset()
                return FetchResult(
                    requested_url=url,
                    final_url=canonical_url(response.geturl()),
                    content=content,
                    content_type=content_type,
                    charset=charset,
                )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25 * (attempt + 1))
    assert last_error is not None
    raise last_error


def destination_for(output: Path, url: str) -> Path:
    remote_path = unquote(urlsplit(url).path)
    if not remote_path.startswith(REMOTE_BASE_PATH):
        raise ValueError(f"URL is outside the archive root: {url}")
    relative = PurePosixPath(remote_path[len(REMOTE_BASE_PATH) :])
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"Unsafe archive path: {remote_path}")
    destination = output.joinpath(*relative.parts)
    resolved_output = output.resolve()
    if resolved_output not in destination.resolve().parents:
        raise ValueError(f"Archive path escapes output directory: {destination}")
    return destination


def save_file(output: Path, result: FetchResult) -> DownloadedFile:
    destination = destination_for(output, result.requested_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    temporary.write_bytes(result.content)
    temporary.replace(destination)
    return DownloadedFile(
        url=result.requested_url,
        path=destination.relative_to(output).as_posix(),
        content_type=result.content_type,
        size=len(result.content),
        sha256=hashlib.sha256(result.content).hexdigest(),
    )


def resolved_urls(values: Iterable[str], base_url: str) -> list[str]:
    urls: list[str] = []
    for value in values:
        # The original Word-generated pages use Windows path separators.
        # Browsers normalize them before navigation; urllib.urljoin does not.
        value = value.strip().replace("\\", "/")
        if not value or value.startswith(("#", "data:", "javascript:", "mailto:")):
            continue
        candidate = canonical_url(urljoin(base_url, value))
        if is_allowed(candidate):
            urls.append(candidate)
    return list(dict.fromkeys(urls))


def parse_page(result: FetchResult) -> tuple[list[str], list[str]]:
    parser = ReferenceParser()
    parser.feed(decode_html(result.content, result.charset))
    base_url = urljoin(result.final_url, parser.base_href) if parser.base_href else result.final_url
    links = resolved_urls(parser.page_links, base_url)
    pages = [url for url in links if is_page(url)]
    linked_files = [url for url in links if not is_page(url)]
    assets = resolved_urls(parser.assets, base_url)
    return pages, list(dict.fromkeys([*linked_files, *assets]))


def download_reference(output: Path, workers: int) -> tuple[list[DownloadedFile], list[dict[str, str]]]:
    output.mkdir(parents=True, exist_ok=True)
    downloaded: list[DownloadedFile] = []
    failures: list[dict[str, str]] = []
    seen_pages: set[str] = set()
    seen_assets: set[str] = set()
    queued_pages: set[str] = set(START_URLS)
    page_futures: dict[Future[FetchResult], str] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for url in START_URLS:
            page_futures[executor.submit(fetch, url)] = url

        while page_futures:
            done, _ = wait(page_futures, return_when=FIRST_COMPLETED)
            for future in done:
                url = page_futures.pop(future)
                try:
                    result = future.result()
                    downloaded.append(save_file(output, result))
                    seen_pages.add(url)
                    pages, assets = parse_page(result)
                    seen_assets.update(assets)
                    for page_url in pages:
                        if page_url not in queued_pages:
                            queued_pages.add(page_url)
                            page_futures[executor.submit(fetch, page_url)] = page_url
                except Exception as exc:  # Keep a complete failure manifest.
                    failures.append({"url": url, "error": str(exc)})

        asset_futures = {
            executor.submit(fetch, url): url for url in sorted(seen_assets - seen_pages)
        }
        for future in asset_futures:
            url = asset_futures[future]
            try:
                downloaded.append(save_file(output, future.result()))
            except Exception as exc:
                failures.append({"url": url, "error": str(exc)})

    return sorted(downloaded, key=lambda item: item.path), failures


def write_manifest(
    output: Path,
    downloaded: list[DownloadedFile],
    failures: list[dict[str, str]],
) -> Path:
    pages = [item for item in downloaded if is_page(item.url)]
    assets = [item for item in downloaded if not is_page(item.url)]
    unavailable = [item for item in failures if item["error"].startswith("HTTP Error 404")]
    fatal_failures = [item for item in failures if item not in unavailable]
    manifest = {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "start_urls": list(START_URLS),
        "summary": {
            "pages": len(pages),
            "assets": len(assets),
            "files": len(downloaded),
            "unavailable": len(unavailable),
            "failures": len(fatal_failures),
        },
        "files": [asdict(item) for item in downloaded],
        "unavailable": unavailable,
        "failures": fatal_failures,
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=12)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.workers < 1 or args.workers > 32:
        print("--workers must be between 1 and 32", file=sys.stderr)
        return 2
    downloaded, failures = download_reference(args.output.resolve(), args.workers)
    manifest = write_manifest(args.output.resolve(), downloaded, failures)
    pages = sum(is_page(item.url) for item in downloaded)
    assets = len(downloaded) - pages
    print(f"Downloaded {pages} pages and {assets} assets to {args.output.resolve()}")
    print(f"Manifest: {manifest}")
    unavailable = [item for item in failures if item["error"].startswith("HTTP Error 404")]
    fatal_failures = [item for item in failures if item not in unavailable]
    if unavailable:
        print(f"Unavailable upstream: {len(unavailable)}")
    if fatal_failures:
        print(f"Failures: {len(fatal_failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
