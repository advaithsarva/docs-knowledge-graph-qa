# Results

Every number below comes from the command shown immediately above it, run against the committed corpus (`data/docs.json`, crawled 2026-08-16). None of these results requires an API key.

---

## Corpus

```bash
python -m graphrag.cli ask "how many pages are in the corpus"
```

| Metric               |                        Result |
| -------------------- | ----------------------------: |
| Pages                | 160 (80 NetworkX, 80 cuGraph) |
| Links between pages  |                           239 |
| Density              |                        0.0094 |
| Connected components |                             4 |

---

## 1. Router accuracy

```bash
python -m graphrag.cli eval
```

| Metric                                   |            Result |
| ---------------------------------------- | ----------------: |
| Route kind (lookup vs graph)             | **37/40 = 0.925** |
| Algorithm choice, given a graph question | **25/25 = 1.000** |

### The three failures

All three failures have the same cause: the question names a graph algorithm but asks for **documentation about it**, rather than asking the system to **run it**.

| Question                                                     | Expected | Actual                       |
| ------------------------------------------------------------ | -------- | ---------------------------- |
| `what does pagerank compute`                                 | lookup   | graph/pagerank               |
| `which page explains betweenness centrality as an algorithm` | lookup   | graph/betweenness_centrality |
| `show me documentation on shortest path algorithms`          | lookup   | graph/shortest_path          |

The third query produces a second downstream error. Once routed to `shortest_path`, the executor has no endpoints to work with and raises:

```text
A shortest-path question needs two endpoints
```

This is one routing mistake producing two visible symptoms, not two independent bugs.

### Why these failures remain

The three cases are deliberately unfixed.

Three regex exceptions could raise this particular test set from 0.925 to 1.000, but that would amount to fitting the router to forty hand-written queries. The underlying distinction is semantic:

* "Run PageRank."
* "Explain PageRank."

The optional `--llm` router is intended for that kind of intent distinction.

### What the accuracy number means

The evaluation set contains 40 queries written by me. It therefore measures how well the rules handle the phrasings represented in that set, not how the router performs on real user traffic.

The set also contains deliberately adversarial queries, which is why a perfect score is not the goal.

`eval --llm` evaluates the LLM router using the same test set. It has **not been run** because no API key was available, so no LLM-router accuracy number is reported.

---

## 2. Does link structure recover the library split?

```bash
python eval/structure.py
```

```text
component 1:  78 pages  majority=networkx  (networkx 78)
component 2:  75 pages  majority=cugraph   (cugraph 75)
component 3:   5 pages  majority=cugraph   (cugraph 5)
component 4:   2 pages  majority=networkx  (networkx 2)

purity = 160/160 = 1.000
```

The purity score needs to be interpreted carefully.

The crawler only follows links that remain under each site's URL prefix. As a result, a NetworkX page cannot link to a cuGraph page in this corpus, and vice versa.

So:

> **purity = 1.000 confirms the graph was assembled without cross-library links. It does not demonstrate community detection.**

The more useful result is that the graph contains **4 components rather than 2**.

Each library has:

* one large connected component
* one small detached component

The smaller components contain 5 cuGraph pages and 2 NetworkX pages. These pages are not connected to the main body of the crawled documentation because the crawler ignores navigation chrome.

That behavior is discussed in the corpus analysis below.

---

## 3. Tests

```bash
python tests/test_graphrag.py       # 10/10 passed

cd tests && python verify_tests.py  # 8/8 caught a real defect in the original
```

The test suite contains one test for each major defect found in the original implementation.

`verify_tests.py` runs equivalent assertions against the original implementations, copied verbatim from the archived source. All eight executable checks detect a defect.

| Assertion                        | What the original did                                                            |
| -------------------------------- | -------------------------------------------------------------------------------- |
| Scrape ignores navigation        | Took links from the whole page, allowing navigation links into the graph         |
| Graph never invents nodes        | `add_edge` on an uncrawled URL created a textless node                           |
| Route kind is a closed set       | Compared the model's `'AQL'` to `"AQL"`, so the quoted response never matched    |
| Graph questions are executed     | Returned `nx.pagerank(G, alpha=0.85)` as a **string** instead of executing it    |
| Allowlist blocks arbitrary names | `getattr(nx, name)` allowed arbitrary NetworkX attributes, including `write_gml` |
| Impossible request raises        | `parse_algorithm_code` raised `not enough values to unpack`                      |
| Search is case insensitive       | `"Install"` matched nothing                                                      |
| Missing corpus raises            | Returned `None` and continued instead of failing explicitly                      |

Two additional tests cannot be run against the original:

* import has no side effects
* components recover the library split

The original imports the ArangoDB connection module, which calls `exit(1)` when the remote database is unavailable. Consequently, importing the application terminates the process before those tests can execute.

That is itself the main finding from the original implementation.

---

## 4. The corpus bug, measured

The crawler was first run against the entire page. Extraction was then restricted to `<article>` content.

| Metric               |                                                            Whole page |          `<article>` only |
| -------------------- | --------------------------------------------------------------------: | ------------------------: |
| Edges                |                                                                 8,785 |                       239 |
| Density              |                                                                 0.345 |                     0.009 |
| Top PageRank result  | Five-way tie at 0.0498: *Install, Gallery, Backends, Developer, home* | `DiGraph.edges` at 0.0290 |
| Page text began with |        `Section Navigation … Copyright 2004-2025 … Built with Sphinx` |         Actual page prose |

Every Sphinx page contains the same navigation sidebar.

When the crawler extracted the whole page, those navigation links became graph edges on every page. PageRank consequently ranked the navigation menu instead of the relationships between documentation pages.

The important part is that nothing crashed. The algorithm returned a plausible-looking number, but the graph represented the wrong structure.

Restricting extraction to `<article>` reduced the graph from 8,785 edges to 239 and produced rankings that correspond to actual documentation links.

---

## 5. Dependencies

| Metric                | Original |         Current |
| --------------------- | -------: | --------------: |
| Declared requirements |       10 | 3 (+1 optional) |

Several of the original dependencies were incorrect or unnecessary:

* `arango` was the wrong package name; the Python driver is `python-arango`.
* `cugraph` is not installable directly from PyPI.
* `deepseek` was never imported.
* `flask` was used but not declared.
* `beautifulsoup4` was used but not declared.
* `langchain-community` was used but not declared.

As a result, the original `pip install -r requirements.txt` could not produce a working environment.

The rewritten project keeps the default dependency set small and leaves the OpenAI client as an optional dependency for the LLM router.
