# docs-knowledge-graph-qa

Ask questions about a documentation corpus in plain English.

Questions are routed either to:

* **Text lookup** over page content, or
* **Graph algorithms** over the documentation link structure.

The graph algorithms are not simulated or LLM-generated; they run directly on a real `networkx` graph built from the corpus.

```bash
$ python -m graphrag.cli ask "how do I install networkx"

[route: lookup]

5 page(s) match. Best: Install (networkx)

        15.0  Install

...instructions for installing the full scientific Python stack. Below we
assume you have the default Python environment already configured...
```

```bash
$ python -m graphrag.cli ask "which page is most central"

[route: graph/pagerank]

Top 10 pages by PageRank (160 pages, 239 links):

      0.0290  DiGraph.edges
      0.0282  DiGraph.add_edges_from
      0.0277  DiGraph.in_edges
```

```bash
$ python -m graphrag.cli ask "are there separate clusters in the docs"

[route: graph/connected_components]

The docs graph splits into 4 connected components:

  component 1: 78 pages (networkx)
  component 2: 75 pages (cugraph)
  component 3: 5 pages (cugraph)
  component 4: 2 pages (networkx)
```

**Router performance:** 37/40 (92.5%) on route classification and 25/25 on graph algorithm selection.

The three failures are documented intentionally; see `RESULTS.md`.

---

## Run it

Requires Python 3.11 or newer. The corpus is committed to the repository, so none of the commands below access the network.

```bash
pip install -r requirements.txt

python tests/test_graphrag.py
python -m graphrag.cli eval

python -m graphrag.cli ask "which page is most linked to"

python -m graphrag.cli serve
# http://127.0.0.1:5000
```

To rebuild the corpus from the live documentation sites:

```bash
python -m graphrag.cli build --max-pages 80
```

A full rebuild takes about two minutes and uses a polite 0.3-second delay between requests.

The optional LLM router requires:

```bash
pip install openai
export OPENAI_API_KEY=...
```

Example:

```bash
python -m graphrag.cli ask --llm "explain what pagerank computes"
```

If no API key is present, the system falls back to the rule-based router rather than failing.

No accuracy number is reported for the LLM router because it has not been evaluated.

---

## How it works

```
question
   │
   ▼

router.route()
   │
   ├── lookup ─────────► execute.search()
   │                     score pages by term overlap
   │                     (title matches count 10×)
   │
   └── graph ──────────► execute.ALGORITHMS[name](G)
                         pagerank
                         in_degree_centrality
                         out_degree_centrality
                         betweenness_centrality
                         connected_components
                         shortest_path
                         summary
   │
   ▼

Answer(summary, rows, detail)
   → CLI output or JSON for the web UI
```

| Module                | Responsibility                                                             |
| --------------------- | -------------------------------------------------------------------------- |
| `graphrag/scrape.py`  | Crawl Sphinx documentation into page records                               |
| `graphrag/graph.py`   | Convert page records to and from `nx.DiGraph`; defines the graph invariant |
| `graphrag/router.py`  | Map questions to `Route(kind, algorithm, terms)`                           |
| `graphrag/execute.py` | Execute routes against the graph                                           |
| `graphrag/cli.py`     | `build`, `ask`, `eval`, `serve`                                            |
| `graphrag/web.py`     | Flask interface over the same router and executor                          |

### The invariant

> The graph is a plain in-memory `nx.DiGraph`, built from a local JSON file and passed explicitly between components.
>
> No module opens network connections, reads credentials, or exits at import time.

That constraint drove the entire rewrite.

---

## The corpus

The corpus contains 160 pages:

* 80 from the NetworkX documentation
* 80 from the cuGraph documentation

These pages form a graph with 239 links.

The original project also targeted ArangoDB and LangChain documentation.

Those sources were excluded because they could not be scraped reliably with simple tools:

* ArangoDB returns `403` responses to non-browser clients.
* LangChain is client-rendered and delivers mostly JavaScript rather than usable content.

Rather than ship empty collections, they were omitted.

---

## What this project used to be

This began as an NVIDIA hackathon project.

The original design was:

* Scrape documentation from four libraries
* Store it in ArangoDB
* Use an LLM to route questions to:

  * AQL
  * NetworkX
  * cuGraph

In practice, the code could not be imported.

### Root cause

`db_arangodb.py` opened a remote ArangoDB connection at module import time and called `exit(1)` if the connection failed.

Every other module imported it.

When the hosted database expired, the entire project became unimportable.

```bash
$ python -c "import socket; socket.gethostbyname('14c3433deb43.arangodb.cloud')"

socket.gaierror: [Errno 11001] getaddrinfo failed
```

### Bugs hidden by that failure

Because the project never ran successfully, several additional problems remained unnoticed:

1. **The router never matched categories**

   The prompt asked the model to return:

   ```
   "AQL"
   ```

   The model returned:

   ```
   'AQL'
   ```

   including quotes.

   The comparison:

   ```python
   if category == "AQL":
   ```

   could never succeed.

2. **No graph algorithm ever executed**

   The fallback branch generated Python source code as text and returned it directly to the browser.

3. **Unrestricted attribute access**

   ```python
   getattr(nx, algorithm_name)(G, **kwargs)
   ```

   allowed arbitrary NetworkX function selection.

4. **`get_networkx_graph()` could not work**

   It called a non-existent API:

   ```python
   nx_db.get_graph()
   ```

5. **`plt.show()` inside Flask requests**

   This blocked the request thread.

6. **`debug=True` in production**

   Exposed the Werkzeug debugger.

7. **Broken dependencies**

   `requirements.txt` referred to packages that were incorrect, unavailable, unused, or missing.

---

### A bug discovered during the rewrite

The first successful crawl produced:

* 8,785 edges
* meaningless PageRank results

The reason was that the crawler indexed navigation sidebars, which appear identically on every Sphinx page.

Restricting extraction to `<article>` content reduced the graph to:

* 239 edges
* meaningful rankings

Both graphs produced numbers. Only one represented the documentation structure.

---

## What was removed

| Removed                  | Reason                                      |
| ------------------------ | ------------------------------------------- |
| ArangoDB / AQL           | No live backend and no reproducible results |
| cuGraph execution        | Never implemented and requires CUDA         |
| LangGraph workflow       | Could not execute successfully              |
| matplotlib visualisation | Incompatible with web requests              |
| Duplicate backends       | Consolidated into one implementation        |

The original repository is not included.

It contained live credentials, including:

* ArangoDB passwords
* API keys

Publishing the history would republish those secrets.

---

## Security

The original project embedded credentials directly in source files.

Those secrets were publicly accessible and should be considered permanently exposed.

The rewrite does not require credentials on its default path.

The only optional secret is:

```bash
OPENAI_API_KEY
```

It is read only inside the function that performs API calls, never during import, and has no default fallback.

---

## Results

Detailed evaluation, commands, and error analysis are available in `RESULTS.md`.
