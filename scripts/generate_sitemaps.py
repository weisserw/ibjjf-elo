#!/usr/bin/env python3
import os
import sys
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

# Ensure app modules are importable
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app, db  # noqa: E402
from models import Athlete  # noqa: E402

BASE_URL = os.getenv("SITE_BASE_URL", "https://ibjjfrankings.com").rstrip("/")
OUTPUT_DIR = os.getenv(
    "SITEMAP_OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "..", "sitemaps")
)
CHUNK_SIZE = int(os.getenv("SITEMAP_MAX_URLS", "49000"))  # below 50k limit
LASTMOD = datetime.utcnow().date().isoformat()

STATIC_PATHS = [
    "/",
    "/about",
    "/calculator",
    "/database",
    "/tournaments",
    "/tournaments/registrations",
    "/tournaments/archive",
    "/news",
]


def build_url(loc: str):
    url = Element("url")
    SubElement(url, "loc").text = loc
    SubElement(url, "lastmod").text = LASTMOD
    return url


def write_urlset(urls, filename):
    urlset = Element(
        "urlset", attrib={"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    )
    for loc in urls:
        urlset.append(build_url(loc))
    xml_bytes = tostring(urlset, encoding="utf-8", xml_declaration=True)
    output_path = os.path.join(OUTPUT_DIR, filename)
    with open(output_path, "wb") as f:
        f.write(xml_bytes)
    return output_path


def write_index(sitemap_files):
    index = Element(
        "sitemapindex", attrib={"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    )
    for fname in sitemap_files:
        sm = SubElement(index, "sitemap")
        SubElement(sm, "loc").text = f"{BASE_URL}/sitemaps/{fname}"
        SubElement(sm, "lastmod").text = LASTMOD
    xml_bytes = tostring(index, encoding="utf-8", xml_declaration=True)
    output_path = os.path.join(OUTPUT_DIR, "sitemap_index.xml")
    with open(output_path, "wb") as f:
        f.write(xml_bytes)
    return output_path


def chunked(iterable, size):
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    sitemap_files = []

    # Static pages
    static_urls = [f"{BASE_URL}{path}" for path in STATIC_PATHS]
    write_urlset(static_urls, "sitemap-static.xml")
    sitemap_files.append("sitemap-static.xml")

    with app.app_context():
        slugs = [
            slug
            for (slug,) in db.session.query(Athlete.slug).order_by(Athlete.slug).all()
        ]

    for idx, slug_chunk in enumerate(chunked(slugs, CHUNK_SIZE), start=1):
        urls = [f"{BASE_URL}/athlete/{slug}" for slug in slug_chunk if slug]
        filename = f"sitemap-athletes-{idx}.xml"
        write_urlset(urls, filename)
        sitemap_files.append(filename)

    index_path = write_index(sitemap_files)
    print(f"Wrote sitemap index: {index_path}")
    for fname in sitemap_files:
        print(f" - {fname}")


if __name__ == "__main__":
    main()
