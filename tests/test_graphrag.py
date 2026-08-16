"""One test per bug actually found in the original. No pytest, no network.

Run:  python tests/test_graphrag.py
Each test names the original defect it guards against. tests/verify_tests.py
runs these same assertions against the original implementations to prove the
suite is not decorative.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx

from graphrag import execute, graph, router, scrape

# --- fixture: three pages, one link target deliberately never crawled ---------
PAGES = [
    {"url": "http://d/a.html", "library": "nx", "title": "Install",
     "text": "Install NetworkX with pip. Requires Python 3.11.",
     "links": ["http://d/b.html", "http://d/missing.html"]},
    {"url": "http://d/b.html", "library": "nx", "title": "DiGraph",
     "text": "A DiGraph stores directed edges between nodes.",
     "links": ["http://d/c.html"]},
    {"url": "http://d/c.html", "library": "cu", "title": "GPU Setup",
     "text": "cuGraph needs a CUDA capable GPU.",
     "links": []},
]

NAV_HTML = """
<html><head><title>DiGraph &#8212; NetworkX</title></head><body>
  <nav class="bd-sidebar">
    <a href="http://d/install.html">Install</a>
    <a href="http://d/gallery.html">Gallery</a>
    <p>Section Navigation</p>
  </nav>
  <article role="main">
    <p>A DiGraph stores directed edges.</p>
    <a href="http://d/real.html">real target</a>
  </article>
  <footer><p>Copyright 2004-2025. Built with Sphinx.</p></footer>
</body></html>
"""

failures = []


def check(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
    except AssertionError as exc:
        print(f"  FAIL  {name}: {exc}")
        failures.append(name)
    except Exception as exc:
        print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
        failures.append(name)


# --- 1 -----------------------------------------------------------------------
def test_import_has_no_side_effects():
    """THE bug. db_arangodb.py connected to a hosted DB at import and called
    exit(1) on failure, so when the trial instance expired every importing
    module died. Importing must never connect, read env, or exit."""
    import importlib

    for name in ("graphrag.graph", "graphrag.router", "graphrag.execute",
                 "graphrag.scrape", "graphrag.web"):
        importlib.reload(importlib.import_module(name))


# --- 2 -----------------------------------------------------------------------
def test_scrape_ignores_navigation():
    """The corpus bug. Scraping whole pages gave every page the same nav links,
    so PageRank returned a five-way tie on the nav bar, and put 'Section
    Navigation ... Copyright ... Built with Sphinx' into every page's text."""
    page = scrape.parse_page(NAV_HTML, "http://d/b.html", "http://d/")

    assert page["links"] == ["http://d/real.html"], f"nav links leaked: {page['links']}"
    assert "Navigation" not in page["text"], "sidebar text leaked into the corpus"
    assert "Copyright" not in page["text"], "footer text leaked into the corpus"
    assert "directed edges" in page["text"], "article body was lost"


# --- 3 -----------------------------------------------------------------------
def test_graph_never_invents_nodes():
    """a.html links to missing.html, which was never crawled. An edge must not
    conjure a node that has no title and no text for search to read."""
    G = graph.build_graph(PAGES)

    assert G.number_of_nodes() == 3, f"expected 3 nodes, got {G.number_of_nodes()}"
    assert "http://d/missing.html" not in G, "uncrawled link became a node"
    assert all(G.nodes[n]["text"] for n in G), "a node has no text"


# --- 4 -----------------------------------------------------------------------
def test_route_kind_is_a_closed_set():
    """The original asked an LLM to 'Respond with one of: AQL, Nx, Nx-Cu' and
    tested `== "AQL"`. The model echoed the prompt's quotes, so that test never
    passed and every query fell through to code generation."""
    for question in ["how do I install networkx", "which page is most central",
                     "'AQL'", "", "!!!"]:
        assert router.route(question).kind in ("lookup", "graph"), question

    try:
        router.Route("AQL")
        raise AssertionError("Route accepted a kind outside the closed set")
    except ValueError:
        pass


# --- 5 -----------------------------------------------------------------------
def test_graph_questions_are_actually_executed():
    """The original returned the LLM's *source code* as the answer and never
    ran it, so it appeared to answer graph questions having run no algorithm.
    A graph route must produce computed numbers."""
    G = graph.build_graph(PAGES)
    answer = execute.run(router.route("which page is most important"), G)

    assert answer.rows, "pagerank produced no rows"
    scores = [v for _, v in answer.rows]
    assert all(isinstance(v, float) for v in scores), f"not computed values: {scores}"
    assert abs(sum(scores) - 1.0) < 1e-6, f"pagerank does not sum to 1: {sum(scores)}"


# --- 6 -----------------------------------------------------------------------
def test_algorithm_allowlist_blocks_arbitrary_names():
    """The original ran getattr(nx, name)(G, **kwargs) on a name produced by an
    LLM. Anything outside the allowlist must raise, not resolve."""
    G = graph.build_graph(PAGES)

    for bad in ("write_gml", "__class__", "nonexistent_algorithm"):
        route = router.Route("graph", algorithm=bad, raw="x")
        try:
            execute.run(route, G)
            raise AssertionError(f"{bad!r} was executed despite not being allowed")
        except KeyError:
            pass

    assert set(execute.ALGORITHMS) <= {
        "pagerank", "in_degree_centrality", "out_degree_centrality",
        "betweenness_centrality", "connected_components", "shortest_path", "summary",
    }, "allowlist grew without review"


# --- 7 -----------------------------------------------------------------------
def test_impossible_request_raises_instead_of_guessing():
    """The original clamped and swallowed: parse_algorithm_code crashed on any
    code without key=value args. A shortest path with no endpoints must say so,
    not silently pick a node."""
    G = graph.build_graph(PAGES)

    route = router.Route("graph", algorithm="shortest_path", raw="find a shortest path")
    try:
        execute.run(route, G)
        raise AssertionError("shortest_path invented endpoints")
    except ValueError as exc:
        assert "endpoint" in str(exc).lower(), f"unhelpful message: {exc}"


# --- 8 -----------------------------------------------------------------------
def test_search_is_case_insensitive():
    """_resolve() passes raw words out of the question, so a capitalised page
    name like 'Install' matched nothing until search() folded case itself."""
    G = graph.build_graph(PAGES)

    assert execute.search(G, ["Install"]), "capitalised term matched nothing"
    assert execute.search(G, ["Install"])[0][0] == execute.search(G, ["install"])[0][0]


# --- 9 -----------------------------------------------------------------------
def test_missing_corpus_raises_not_stubs():
    """A missing corpus must stop the program, not yield an empty graph that
    answers every question with 'no results'."""
    try:
        graph.load_pages(os.path.join(os.path.dirname(__file__), "no_such_corpus.json"))
        raise AssertionError("missing corpus did not raise")
    except FileNotFoundError as exc:
        assert "build" in str(exc), "error does not say how to fix it"


# --- 10 ----------------------------------------------------------------------
def test_components_recover_the_library_split():
    """The measured claim in RESULTS.md: link structure separates the two
    libraries. On the fixture, a->b->c bridges them, so it must NOT split --
    this guards the claim against being true by accident."""
    G = graph.build_graph(PAGES)
    components = list(nx.connected_components(G.to_undirected()))

    assert len(components) == 1, f"fixture is linked end to end, got {len(components)}"
    answer = execute.run(router.route("are there separate clusters"), G)
    assert "1 connected component" in answer.summary, answer.summary


TESTS = [
    ("import has no side effects", test_import_has_no_side_effects),
    ("scrape ignores navigation", test_scrape_ignores_navigation),
    ("graph never invents nodes", test_graph_never_invents_nodes),
    ("route kind is a closed set", test_route_kind_is_a_closed_set),
    ("graph questions are executed", test_graph_questions_are_actually_executed),
    ("allowlist blocks arbitrary names", test_algorithm_allowlist_blocks_arbitrary_names),
    ("impossible request raises", test_impossible_request_raises_instead_of_guessing),
    ("search is case insensitive", test_search_is_case_insensitive),
    ("missing corpus raises", test_missing_corpus_raises_not_stubs),
    ("components recover library split", test_components_recover_the_library_split),
]


if __name__ == "__main__":
    print(f"Running {len(TESTS)} tests\n")
    for name, fn in TESTS:
        check(name, fn)
    print(f"\n{len(TESTS) - len(failures)}/{len(TESTS)} passed")
    sys.exit(1 if failures else 0)
