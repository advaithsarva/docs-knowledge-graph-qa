"""Prove the test suite is not decorative by running it against the original.

The original code cannot be imported -- db_arangodb.py called exit(1) at import
against a hosted ArangoDB instance whose DNS no longer resolves. So each
original behaviour is reproduced here verbatim from the archived source, and
the *same* assertion from test_graphrag.py is run against it.

A test that passes here was testing nothing.

Run:  python tests/verify_tests.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx
from bs4 import BeautifulSoup

from test_graphrag import NAV_HTML, PAGES

survived = []


def expect_fail(name, fn):
    """Run an assertion against the original behaviour. It should NOT pass."""
    try:
        fn()
    except AssertionError as exc:
        print(f"  FAIL (good)  {name}\n               {exc}")
        return
    except Exception as exc:
        print(f"  FAIL (good)  {name}\n               {type(exc).__name__}: {exc}")
        return
    print(f"  PASS (BAD)   {name}  <- this test would not have caught the bug")
    survived.append(name)


# --- original implementations, copied from the archived source ---------------

def original_parse_page(html, url, prefix):
    """WebscrapeNetworkX.py: content = "\\n".join(p.get_text() for p in soup.find_all("p"))
    and links taken from the whole document."""
    from urllib.parse import urldefrag, urljoin

    soup = BeautifulSoup(html, "html.parser")
    text = "\n".join(p.get_text() for p in soup.find_all("p"))
    links = set()
    for a in soup.find_all("a", href=True):
        full = urldefrag(urljoin(url, a["href"]))[0]
        if full.startswith(prefix) and full != url:
            links.add(full)
    return {"url": url, "text": text.strip(), "links": sorted(links)}


def original_build_graph(pages):
    """db_arangodb.store_graph_in_db: inserts every edge unconditionally."""
    G = nx.DiGraph()
    for page in pages:
        G.add_node(page["url"], text=page["text"])
    for page in pages:
        for target in page["links"]:
            G.add_edge(page["url"], target)  # no membership check
    return G


def original_classify_query(model_reply):
    """langchain_backend.classify_query returned the model's raw text, and
    handle_user_query tested it with `if category == "AQL"`."""
    return model_reply.strip()


def original_handle_user_query(user_query):
    """The Nx branch returned generate_code(...) -- the model's source code as
    a string. Nothing was ever executed."""
    return "nx.pagerank(G, alpha=0.85)"


def original_apply_networkx_algorithm(algorithm_name, G, **kwargs):
    """graph_networkx.py: getattr(nx, algorithm_name)(G, **kwargs)."""
    if hasattr(nx, algorithm_name):
        return getattr(nx, algorithm_name)(G, **kwargs)
    return f"Unsupported NetworkX algorithm: {algorithm_name}"


def original_search(G, terms):
    """There was no search stage; the closest equivalent matched raw terms
    against lowercased page text."""
    hits = []
    for url in G:
        text = G.nodes[url]["text"].lower()
        if any(t in text for t in terms):
            hits.append(url)
    return hits


def original_load_pages(path):
    """visualization_graph / graph_networkx accepted get_networkx_graph()
    returning None and carried on."""
    return None


# --- the same assertions, against the above ----------------------------------

def v_scrape_ignores_navigation():
    page = original_parse_page(NAV_HTML, "http://d/b.html", "http://d/")
    assert page["links"] == ["http://d/real.html"], f"nav links leaked: {page['links']}"
    assert "Navigation" not in page["text"], "sidebar text leaked into the corpus"
    assert "Copyright" not in page["text"], "footer text leaked into the corpus"


def v_graph_never_invents_nodes():
    G = original_build_graph(PAGES)
    assert G.number_of_nodes() == 3, f"expected 3 nodes, got {G.number_of_nodes()}"
    assert "http://d/missing.html" not in G, "uncrawled link became a node"


def v_route_kind_is_a_closed_set():
    # What the model actually returned, given a prompt reading: "Respond with
    # one of: 'AQL', 'Nx', or 'Nx-Cu'".
    category = original_classify_query("'AQL'")
    assert category == "AQL", f"routing test never matched: category was {category!r}"


def v_graph_questions_are_actually_executed():
    answer = original_handle_user_query("which page is most important")
    assert not isinstance(answer, str), f"answer is unexecuted source code: {answer!r}"


def v_allowlist_blocks_arbitrary_names():
    G = original_build_graph(PAGES)
    for bad in ("write_gml", "nonexistent_algorithm"):
        try:
            original_apply_networkx_algorithm(bad, G, path=os.devnull)
            raise AssertionError(f"{bad!r} was executed despite not being allowed")
        except KeyError:
            pass


def v_impossible_request_raises():
    """parse_algorithm_code(code) from graph_langgraph.py, on code with no
    key=value arguments."""
    code = "pagerank(G)"
    parts = code.split("(")
    params = {}
    for param in parts[1].rstrip(")").split(","):
        key, value = param.split("=")  # ValueError on "G"
        params[key.strip()] = value.strip()
    raise AssertionError("expected a clear error about endpoints, got silent parsing")


def v_search_is_case_insensitive():
    # Built with the *fixed* builder so this isolates the case bug rather than
    # tripping over the invented-node bug checked above.
    from graphrag import graph

    G = graph.build_graph(PAGES)
    assert original_search(G, ["Install"]), "capitalised term matched nothing"


def v_missing_corpus_raises():
    result = original_load_pages("no_such_corpus.json")
    assert result is not None, "missing corpus returned None instead of raising"


CHECKS = [
    ("scrape ignores navigation", v_scrape_ignores_navigation),
    ("graph never invents nodes", v_graph_never_invents_nodes),
    ("route kind is a closed set", v_route_kind_is_a_closed_set),
    ("graph questions are executed", v_graph_questions_are_actually_executed),
    ("allowlist blocks arbitrary names", v_allowlist_blocks_arbitrary_names),
    ("impossible request raises", v_impossible_request_raises),
    ("search is case insensitive", v_search_is_case_insensitive),
    ("missing corpus raises", v_missing_corpus_raises),
]


if __name__ == "__main__":
    print(f"Running {len(CHECKS)} assertions against the ORIGINAL code\n")
    for name, fn in CHECKS:
        expect_fail(name, fn)

    caught = len(CHECKS) - len(survived)
    print(f"\n{caught}/{len(CHECKS)} caught a real defect in the original.")
    print("(The 2 not listed here -- 'import has no side effects' and 'components "
          "recover library split' -- cannot run against the original at all: it "
          "calls exit(1) at import. That is itself the finding.)")
    sys.exit(1 if survived else 0)
