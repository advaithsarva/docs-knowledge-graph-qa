# docs-knowledge-graph-qa

Ask a documentation corpus a question in plain English. The question is routed
either to a **text lookup** over page content, or to a **graph algorithm** over
the link structure between pages — and the graph algorithm actually runs.

```
$ python -m graphrag.cli ask "how do I install networkx"
[route: lookup]

5 page(s) match. Best: Install (networkx)
        15.0  Install
...instructions for installing the full scientific Python stack. Below we
assume you have the default Python environment already configured...

$ python -m graphrag.cli ask "which page is most central"
[route: graph/pagerank]

Top 10 pages by PageRank (160 pages, 239 links):
      0.0290  DiGraph.edges
      0.0282  DiGraph.add_edges_from
      0.0277  DiGraph.in_edges

$ python -m graphrag.cli ask "are there separate clusters in the docs"
[route: graph/connected_components]

The docs graph splits into 4 connected components:
  component 1: 78 pages (networkx 78)
  component 2: 75 pages (cugraph 75)
  component 3: 5 pages (cugraph 5)
  component 4: 2 pages (networkx 2)
```

**Router accuracy: 37/40 (0.925) on route kind, 25/25 on algorithm choice.**
The three failures are documented and left unfixed on purpose — see
[RESULTS.md](RESULTS.md).

---

## Run it

Needs Python 3.11+. The corpus is committed, so nothing below hits the network.

```bash
pip install -r requirements.txt

python tests/test_graphrag.py              # 10/10
python -m graphrag.cli eval                # router accuracy + every failure
python -m graphrag.cli ask "which page is most linked to"
python -m graphrag.cli serve               # web UI on http://127.0.0.1:5000
```

To rebuild the corpus from the live docs sites (~2 minutes, polite 0.3s delay):

```bash
python -m graphrag.cli build --max-pages 80
```

The optional LLM router needs `pip install openai` and `OPENAI_API_KEY`:

```bash
python -m graphrag.cli ask --llm "explain what pagerank computes"
```

It falls back to the rules if the key is missing rather than crashing. No
number for the LLM router is claimed anywhere — it has not been measured.

---

## How it works

```
question
   │
   ▼
router.route()            rules over a closed set; --llm swaps in a model
   │
   ├── lookup ──────────► execute.search()      score pages by term overlap
   │                                            (title matches weigh 10x body)
   └── graph ───────────► execute.ALGORITHMS[name](G)
                          pagerank · in/out_degree_centrality ·
                          betweenness_centrality · connected_components ·
                          shortest_path · summary
   │
   ▼
Answer(summary, rows, detail)  →  CLI text or JSON for the web UI
```

| Module | Job |
|---|---|
| `graphrag/scrape.py` | crawl Sphinx docs sites → page records |
| `graphrag/graph.py` | page records ↔ `nx.DiGraph`; **states the invariant** |
| `graphrag/router.py` | question → `Route(kind, algorithm, terms)` |
| `graphrag/execute.py` | run a route against the graph → `Answer` |
| `graphrag/cli.py` | `build` · `ask` · `eval` · `serve` |
| `graphrag/web.py` | Flask UI over the same router and executor |

### The invariant

> The graph is a plain in-memory `nx.DiGraph`, built from a local JSON file and
> passed to every stage as an ordinary argument. **No module connects to
> anything, reads an environment variable, or exits at import time.**

That one rule is the whole rewrite. See below.

### The corpus

160 pages: 80 from the NetworkX docs, 80 from the cuGraph docs, with the 239
links between them.

The original also targeted the ArangoDB and LangChain docs. Neither is
scrapeable with `urllib` + BeautifulSoup: ArangoDB's docs return `403` to any
non-browser client, and LangChain's are client-rendered, serving 974 KB of HTML
containing 8 paragraphs and no usable links. They are left out rather than
shipped as empty collections.

---

## What this used to be, and what went wrong

This was an NVIDIA hackathon project: scrape four libraries' docs into an
ArangoDB graph, then use an LLM to route questions to either AQL, NetworkX, or
GPU-accelerated cuGraph. Roughly 700 lines across four parallel half-finished
backends.

It could not be run at all. Not "it had bugs" — the Python could not be
imported.

**The root cause.** `db_arangodb.py` opened a connection to a hosted ArangoDB
instance at module scope and called `exit(1)` if it failed. Every other module
imported it. When the hackathon's trial instance expired, the entire project
became unimportable in one stroke. Its hostname no longer resolves:

```
$ python -c "import socket; socket.gethostbyname('14c3433deb43.arangodb.cloud')"
socket.gaierror: [Errno 11001] getaddrinfo failed
```

**The symptoms that root cause hid.** Because nothing could run, none of these
were ever observed:

1. **The router never routed.** The prompt said *"Respond with one of: 'AQL',
   'Nx', or 'Nx-Cu'"*, and the model obligingly replied `'AQL'` **with the
   quotes**. The code tested `if category == "AQL"`. That comparison could never
   be true, so every query fell through to the code-generation branch.
2. **No graph algorithm was ever executed.** That branch called `generate_code`,
   which returned the model's *source code as a string*, and the Flask handler
   returned that string to the browser. The project appeared to answer graph
   questions having run nothing.
3. **`getattr(nx, algorithm_name)(G, **kwargs)`** — arbitrary NetworkX attribute
   access driven by LLM output.
4. **`get_networkx_graph()` could never work.** It called `nx_db.get_graph()`;
   `nx_arangodb` has no module-level `get_graph`. Its guard,
   `if "nx_db" in globals()`, was always true, so it always took the broken path.
5. **`plt.show()` inside a Flask request handler**, blocking the server thread.
6. **`app.run(debug=True)`** — the Werkzeug console, exposed.
7. **`pip install -r requirements.txt` could not work**: `arango` is the wrong
   package name, `cugraph` is not on PyPI, `deepseek` was unused, and `flask`
   and `beautifulsoup4` were used but undeclared.

**A separate bug in the new code, worth recording.** The first working crawl
produced 8,785 edges and a PageRank that returned a five-way tie on *Install,
Gallery, Backends, Developer* and the home page. It was ranking the navigation
sidebar, which is identical on all 160 Sphinx pages. Scoping extraction to
`<article>` cut it to 239 edges and produced real answers. A number came out
either way; only one of them meant anything.

### What was cut, and why

| Dropped | Why |
|---|---|
| ArangoDB / AQL path | The hosted instance is gone and its docs block scraping. Kept as an untestable path, it would be a claim with nothing behind it. Text lookup replaces it. |
| cuGraph execution | Never implemented past a stub; needs a CUDA GPU, so no result could be produced or checked. cuGraph's *docs* remain half the corpus. |
| LangGraph workflow | A fourth parallel backend whose entry point printed `"Error: Response is not in the expected dictionary format"` on every run, because `handle_user_query` returns a string and it indexed `response["category"]`. |
| matplotlib visualisation | `plt.show()` from a web request handler. |
| 3 duplicate backends | `app_main.py`, `apppp2.py`, `g.py` and `src/` were four takes on the same idea; `src/` was seven empty files. |

The original code is **not** in this repository. It contained a live ArangoDB
password and an API key in plain text; committing it, even as history, would
republish them.

### Security

The original hardcoded an ArangoDB root password in four files and an API key in
a `.env`, and was pushed public in March 2025. **Both credentials are burned and
must be rotated at the provider** — they were readable on GitHub for seventeen
months, and deleting a file does not unpublish a secret.

This rewrite reads no credential at all on its default path. The only secret it
can use is `OPENAI_API_KEY`, read inside the function that calls the API, never
at import, with no fallback default.

---

## Results

Full numbers, commands and error analysis: **[RESULTS.md](RESULTS.md)**.
