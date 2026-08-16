"""Turn scraped page records into a NetworkX graph, and load/save the corpus.

THE INVARIANT
=============
    The graph is a plain in-memory nx.DiGraph, built from a local JSON file and
    passed to every other stage as an ordinary argument.

No module in this package opens a network connection, reads an environment
variable, or touches a database at import time. That is precisely what broke
the original project: db_arangodb.py connected to a hosted ArangoDB instance at
import and called exit(1) on failure, so when that trial instance expired every
module importing it -- the Flask app, the NetworkX stage, the visualiser --
became unimportable at once. A stage takes data and returns data.
"""

import json
import os

import networkx as nx

DEFAULT_CORPUS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "docs.json")


def save_pages(pages, path=DEFAULT_CORPUS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pages, f, indent=1, ensure_ascii=False)


def load_pages(path=DEFAULT_CORPUS):
    """Load the page corpus. Raises if it is missing -- never returns a stub."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No corpus at {path}. Build one first:  python -m graphrag.cli build"
        )
    with open(path, encoding="utf-8") as f:
        pages = json.load(f)
    if not pages:
        raise ValueError(f"Corpus at {path} is empty.")
    return pages


def build_graph(pages):
    """Build a DiGraph: one node per page, one edge per link between two pages.

    Links to pages that were never crawled are dropped, so the node set is
    exactly the page set -- an edge can never invent a node with no text.
    """
    G = nx.DiGraph()
    for page in pages:
        G.add_node(
            page["url"],
            title=page["title"],
            text=page["text"],
            library=page["library"],
        )

    known = set(G.nodes)
    for page in pages:
        for target in page["links"]:
            if target in known:
                G.add_edge(page["url"], target)

    assert G.number_of_nodes() == len({p["url"] for p in pages}), "graph lost pages"
    return G


def load_graph(path=DEFAULT_CORPUS):
    """Convenience: corpus file -> DiGraph."""
    return build_graph(load_pages(path))


def label(G, url):
    """Human-readable name for a node, for use in answers."""
    return G.nodes[url].get("title") or url
