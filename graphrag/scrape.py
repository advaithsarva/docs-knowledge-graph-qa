"""Crawl Sphinx documentation sites into a flat list of page records.

Replaces the six near-identical Webscrape*.py scripts in the original project,
which each hardcoded one site and wrote to a different JSON path.

A page record is a dict:
    {"url": str, "library": str, "title": str, "text": str, "links": list[str]}

`links` holds every same-site .html URL the page points at. graph.py turns
those into edges; pages that were never crawled are dropped there, not here.
"""

import time
import urllib.error
import urllib.request
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup

USER_AGENT = "graphrag-docs-qa/1.0 (documentation crawler; +https://github.com/advaithsarva)"

# ponytail: two Sphinx sites, not four. ArangoDB's docs return 403 to any
# non-browser client and LangChain's are a client-rendered SPA with no links
# in the served HTML -- neither is scrapeable with requests+bs4, and pretending
# otherwise is what left the original with an empty corpus. See README.
SITES = {
    "networkx": {
        "prefix": "https://networkx.org/documentation/stable/",
        "seeds": [
            "https://networkx.org/documentation/stable/reference/algorithms/index.html",
            "https://networkx.org/documentation/stable/reference/classes/index.html",
            "https://networkx.org/documentation/stable/install.html",
        ],
    },
    "cugraph": {
        "prefix": "https://docs.rapids.ai/api/cugraph/stable/",
        "seeds": [
            "https://docs.rapids.ai/api/cugraph/stable/api_docs/cugraph/",
            "https://docs.rapids.ai/api/cugraph/stable/graph_support/algorithms/",
        ],
    },
}


def fetch(url, timeout=20):
    """GET a URL, returning HTML text or None if it is not fetchable HTML."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if "html" not in resp.headers.get("Content-Type", ""):
                return None
            return resp.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return None


def main_content(soup):
    """The article body, excluding the site-wide nav sidebar and footer.

    Scraping the whole page instead of this region was the corpus's one real
    bug, and it produced two symptoms: every page inherited the same handful of
    nav links, so PageRank returned a five-way tie on the nav bar rather than
    ranking content; and every page's text began with "Section Navigation ...
    Copyright ... Built with Sphinx", which matched search queries about
    navigation and copyright. Both themes here expose <article>.
    """
    for selector in ("article", "[role=main]", "main"):
        found = soup.select_one(selector)
        if found:
            return found
    return soup


def parse_page(html, url, prefix):
    """Extract title, prose text and same-site links from one docs page."""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else url
    title = title.split(" — ")[0].strip()

    body = main_content(soup)

    # Sphinx puts prose in <p> and API descriptions in <dd>; both matter for search.
    blocks = [b.get_text(" ", strip=True) for b in body.find_all(["p", "dd"])]
    text = "\n".join(b for b in blocks if b)

    links = set()
    for a in body.find_all("a", href=True):
        full = urldefrag(urljoin(url, a["href"]))[0]
        if full.startswith(prefix) and full != url:
            links.add(full)

    return {"url": url, "title": title, "text": text, "links": sorted(links)}


def crawl_site(library, prefix, seeds, max_pages=80, delay=0.3):
    """Breadth-first crawl of one docs site, capped at max_pages."""
    seen, queue, pages = set(seeds), list(seeds), []

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        html = fetch(url)
        time.sleep(delay)
        if not html:
            continue

        page = parse_page(html, url, prefix)
        if not page["text"]:
            continue  # index/redirect stubs carry no prose worth searching

        page["library"] = library
        pages.append(page)

        for link in page["links"]:
            if link not in seen:
                seen.add(link)
                queue.append(link)

    return pages


def crawl(sites=None, max_pages=80, delay=0.3):
    """Crawl every configured site and return one flat list of page records."""
    sites = sites or SITES
    pages = []
    for library, cfg in sites.items():
        got = crawl_site(library, cfg["prefix"], cfg["seeds"], max_pages, delay)
        print(f"  {library}: {len(got)} pages")
        pages.extend(got)
    return pages
