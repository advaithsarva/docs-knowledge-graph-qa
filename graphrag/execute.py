"""Run a Route against the graph and return a structured Answer.

Two rules from the original's failures govern this module.

1. Algorithms are an explicit allowlist, never getattr(nx, name). The original
   did `getattr(nx, algorithm_name)(G, **kwargs)` on a name that came out of an
   LLM, which is arbitrary-attribute execution driven by model output.

2. An impossible request raises instead of being quietly made possible. The
   original's `parse_algorithm_code` crashed on any code without `key=value`
   arguments, and its Nx branch returned the LLM's *source code* as the answer
   without ever executing it -- so the project appeared to answer graph
   questions while having run no graph algorithm at all.
"""

import re

import networkx as nx

from .graph import label

TOP_N = 10


class Answer:
    """What a question resolved to. `rows` is (label, value) pairs, may be empty."""

    def __init__(self, summary, rows=None, detail=""):
        self.summary = summary
        self.rows = rows or []
        self.detail = detail

    def as_dict(self):
        return {"summary": self.summary, "rows": self.rows, "detail": self.detail}

    def __str__(self):
        out = [self.summary]
        for name, value in self.rows:
            out.append(f"  {value:>10}  {name}" if isinstance(value, str) else f"  {value:10.4f}  {name}")
        if self.detail:
            out.append(self.detail)
        return "\n".join(out)


def _ranking(G, scores, what):
    top = sorted(scores.items(), key=lambda kv: -kv[1])[:TOP_N]
    return Answer(
        f"Top {len(top)} pages by {what} ({G.number_of_nodes()} pages, {G.number_of_edges()} links):",
        [(label(G, url), score) for url, score in top],
    )


def _pagerank(G, route):
    return _ranking(G, nx.pagerank(G), "PageRank")


def _in_degree(G, route):
    return _ranking(G, nx.in_degree_centrality(G), "incoming links (in-degree centrality)")


def _out_degree(G, route):
    return _ranking(G, nx.out_degree_centrality(G), "outgoing links (out-degree centrality)")


def _betweenness(G, route):
    return _ranking(G, nx.betweenness_centrality(G), "betweenness centrality")


def _components(G, route):
    from collections import Counter

    groups = sorted(nx.connected_components(G.to_undirected()), key=len, reverse=True)
    rows = []
    for i, group in enumerate(groups[:TOP_N], 1):
        libs = Counter(G.nodes[n]["library"] for n in group)
        mix = ", ".join(f"{lib} {n}" for lib, n in libs.most_common())
        rows.append((f"component {i}: {len(group)} pages ({mix})", ""))
    return Answer(f"The docs graph splits into {len(groups)} connected components:", rows)


def _summary(G, route):
    from collections import Counter

    libs = Counter(G.nodes[n]["library"] for n in G)
    rows = [(f"{lib} pages", str(n)) for lib, n in libs.most_common()]
    rows.append(("links between pages", str(G.number_of_edges())))
    rows.append(("density", f"{nx.density(G):.4f}"))
    return Answer(f"Corpus: {G.number_of_nodes()} pages from {len(libs)} libraries.", rows)


def _shortest_path(G, route):
    """Needs two endpoints. Raises when it cannot find them -- never guesses one."""
    match = re.search(r"from (.+?) to (.+?)[?.]?$", route.raw or "", re.I)
    if not match:
        raise ValueError(
            "A shortest-path question needs two endpoints, phrased "
            "'... from <page> to <page>'."
        )

    source, target = (_resolve(G, part.strip()) for part in match.groups())
    try:
        path = nx.shortest_path(G.to_undirected(), source, target)
    except nx.NetworkXNoPath:
        return Answer(
            f"No link path connects {label(G, source)} to {label(G, target)}."
        )
    return Answer(
        f"{len(path) - 1} link(s) from {label(G, source)} to {label(G, target)}:",
        [(label(G, n), str(i)) for i, n in enumerate(path)],
    )


def _resolve(G, phrase):
    """Find the one page a phrase names, or raise saying it could not be found."""
    hits = search(G, phrase.split())
    if not hits:
        raise ValueError(f"No page in the corpus matches {phrase!r}.")
    return hits[0][0]


ALGORITHMS = {
    "pagerank": _pagerank,
    "in_degree_centrality": _in_degree,
    "out_degree_centrality": _out_degree,
    "betweenness_centrality": _betweenness,
    "connected_components": _components,
    "shortest_path": _shortest_path,
    "summary": _summary,
}


def search(G, terms, limit=5):
    """Score pages by term overlap. Returns [(url, score)], best first.

    Title matches count more than body matches: a page *called* "Install" is a
    better answer to "how do I install networkx" than one that mentions
    installing once in passing.
    """
    # Lowercased here, not by callers: router.keywords() already folds case but
    # _resolve() passes raw words out of the question, and a capitalised page
    # name like "Install" would otherwise match nothing at all.
    terms = [t.lower() for t in terms]

    scored = []
    for url in G:
        title = G.nodes[url]["title"].lower()
        text = G.nodes[url]["text"].lower()
        score = 0.0
        for term in terms:
            if term in title:
                score += 5.0
            score += min(text.count(term), 10) * 0.5
        if score:
            scored.append((url, score))
    return sorted(scored, key=lambda kv: -kv[1])[:limit]


def _snippet(text, terms, width=180):
    """A window of text around the first matching term."""
    low = text.lower()
    for term in terms:
        i = low.find(term)
        if i >= 0:
            start = max(0, i - width // 3)
            return ("..." if start else "") + text[start:start + width].strip() + "..."
    return text[:width].strip() + "..."


def _lookup(G, route):
    hits = search(G, route.terms)
    if not hits:
        return Answer(
            "No page mentions " + ", ".join(route.terms) + ".",
            detail="Try different wording, or rebuild the corpus with more pages.",
        )
    best = hits[0][0]
    return Answer(
        f"{len(hits)} page(s) match. Best: {label(G, best)} ({G.nodes[best]['library']})",
        [(label(G, url), f"{score:.1f}") for url, score in hits],
        detail=_snippet(G.nodes[best]["text"], route.terms),
    )


def run(route, G):
    """Execute a route. Raises KeyError on an algorithm outside the allowlist."""
    if route.kind == "lookup":
        return _lookup(G, route)
    if route.algorithm not in ALGORITHMS:
        raise KeyError(
            f"{route.algorithm!r} is not an allowed algorithm. "
            f"Allowed: {', '.join(sorted(ALGORITHMS))}"
        )
    return ALGORITHMS[route.algorithm](G, route)
