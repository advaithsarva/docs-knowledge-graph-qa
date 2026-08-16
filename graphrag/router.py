"""Classify a natural-language question into a route the executor can run.

A route is either:
    lookup  -- answer from page text (search the corpus)
    graph   -- answer from link structure (run a named graph algorithm)

The original routed by asking an LLM to "Respond with one of: 'AQL', 'Nx', or
'Nx-Cu'" and then comparing the raw reply to == "AQL". The prompt's own quoting
meant the model usually replied 'AQL' *with* the quotes, so that test never
passed and every query silently fell through to the code-generation branch.
Two lessons are baked in here: the classifier returns a value from a closed set
rather than free text, and the rule-based path is the default so the project has
a routing number that reproduces without a paid API key.
"""

import re
from dataclasses import dataclass, field

# Ordered most-specific first: the first pattern that matches wins, so
# "how many pages link to X" resolves to in_degree before the looser
# "most important" pagerank trigger can claim it.
GRAPH_RULES = [
    ("summary", r"\b(how many pages|how many nodes|how many edges|how big|corpus size|graph size|overview of the (graph|corpus)|summar)"),
    ("shortest_path", r"\b(shortest path|path from|route from|how .* get from|steps from|connect .* to)\b"),
    ("connected_components", r"\b(components?|clusters?|communities|groups|islands|disconnected|separate parts|split into)\b"),
    ("in_degree_centrality", r"\b(most (linked|referenced|cited)|linked to (the )?most|incoming links|most inbound|referred to most|most pointed)\b"),
    ("betweenness_centrality", r"\b(betweenness|bridge|bridges|connector|go-between|in between|links two|joins the)\b"),
    ("pagerank", r"\b(most (important|influential|central|significant)|pagerank|page rank|centrality|rank the pages|influence)\b"),
    ("out_degree_centrality", r"\b(links out|outgoing links|most outbound|links to the most|points to the most)\b"),
]

STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
    "docs", "documentation", "explain", "find", "for", "from", "get", "give", "how",
    "i", "in", "is", "it", "me", "of", "on", "or", "page", "pages", "return", "show",
    "tell", "that", "the", "there", "to", "use", "used", "using", "what", "when",
    "where", "which", "who", "why", "with", "work", "works", "you",
}


@dataclass
class Route:
    """Where a question should be answered from. `kind` is a closed set."""

    kind: str  # "lookup" | "graph"
    algorithm: str = ""
    terms: list = field(default_factory=list)
    raw: str = ""  # the original question; shortest_path needs its endpoints

    def __post_init__(self):
        if self.kind not in ("lookup", "graph"):
            raise ValueError(f"unknown route kind: {self.kind!r}")
        if self.kind == "graph" and not self.algorithm:
            raise ValueError("graph route needs an algorithm")


def keywords(question):
    """Content words from a question, for text search."""
    words = re.findall(r"[a-z0-9_.]+", question.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def route(question):
    """Rule-based classification. Always returns a Route; never guesses free text."""
    q = question.lower()
    for algorithm, pattern in GRAPH_RULES:
        if re.search(pattern, q):
            return Route("graph", algorithm=algorithm, terms=keywords(question), raw=question)
    return Route("lookup", terms=keywords(question), raw=question)


def route_llm(question, model="gpt-4o-mini"):
    """Optional LLM classifier, chosen by --llm.

    Imports openai and reads the key inside the call, never at import time --
    see the invariant in graph.py. Falls back to the rules on any failure so a
    missing key degrades instead of crashing.
    """
    allowed = [name for name, _ in GRAPH_RULES]
    try:
        import os

        from openai import OpenAI

        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")

        prompt = (
            "Classify the question about a documentation corpus.\n"
            "Reply with exactly one token and nothing else.\n"
            f"Use 'lookup' if it is answered by reading page text. Otherwise use one of: {', '.join(allowed)}.\n"
            f"Question: {question}"
        )
        reply = (
            OpenAI()
            .chat.completions.create(
                model=model,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            .choices[0]
            .message.content
        )
        # Strip the quoting/punctuation that defeated the original's == "AQL" test.
        token = reply.strip().strip("'\"`. \n").lower()
        if token in allowed:
            return Route("graph", algorithm=token, terms=keywords(question), raw=question)
        if token == "lookup":
            return Route("lookup", terms=keywords(question), raw=question)
        raise ValueError(f"model returned {reply!r}, not in the allowed set")
    except Exception as exc:
        print(f"[llm router unavailable: {exc}; using rules]")
        return route(question)
