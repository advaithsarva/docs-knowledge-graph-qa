# Results

Every number below came from the command shown above it, run on the committed
corpus (`data/docs.json`, crawled 2026-08-16). Nothing here needs an API key.

---

## Corpus

```bash
python -m graphrag.cli ask how many pages are in the corpus
```

| | |
|---|---|
| Pages | 160 (80 NetworkX, 80 cuGraph) |
| Links between pages | 239 |
| Density | 0.0094 |
| Connected components | 4 |

---

## 1. Router accuracy

```bash
python -m graphrag.cli eval
```

| Metric | Result |
|---|---|
| Route kind (lookup vs graph) | **37/40 = 0.925** |
| Algorithm choice, given a graph question | **25/25 = 1.000** |

### The three failures, and why they are the interesting part

All three are the same mistake: a question that *names* a graph algorithm but
asks for **documentation about** it, not for it to be **run**.

| Question | Wanted | Got |
|---|---|---|
| `what does pagerank compute` | lookup | graph/pagerank |
| `which page explains betweenness centrality as an algorithm` | lookup | graph/betweenness_centrality |
| `show me documentation on shortest path algorithms` | lookup | graph/shortest_path |

The third then fails a second time downstream, correctly: routed to
`shortest_path`, it has no endpoints to work with and raises
`A shortest-path question needs two endpoints`. That is one root cause
producing two visible symptoms, not two bugs.

**This is not fixed, deliberately.** Three targeted regex exceptions would take
0.925 to 1.000 on this set and would be pure overfitting to forty queries I
wrote myself. Distinguishing "run PageRank" from "explain PageRank" needs
intent, which is what the optional `--llm` router is for.

### What this number is not

The eval set is 40 queries **I wrote**, so it measures the router against my own
idea of how the questions get phrased. Treat 0.925 as "the rules cover the
phrasings anticipated", not as accuracy on real user traffic. The set does
include adversarial cases written to fail, which is why it does not read 40/40.

`eval --llm` scores the LLM router the same way. **It has not been run** — no
API key was available — so no number for it is claimed anywhere.

---

## 2. Does link structure recover the library split?

```bash
python eval/structure.py
```

```
component 1:  78 pages  majority=networkx  (networkx 78)
component 2:  75 pages  majority=cugraph   (cugraph 75)
component 3:   5 pages  majority=cugraph   (cugraph 5)
component 4:   2 pages  majority=networkx  (networkx 2)

purity = 160/160 = 1.000
```

**Read this one sceptically.** Purity of 1.000 is close to tautological: the
crawler only follows links that stay under a site's own URL prefix, so an edge
between a NetworkX page and a cuGraph page cannot exist. Perfect purity confirms
the graph was assembled correctly; it does not demonstrate community detection.

The part that is a real finding is the count: **4 components, not 2.** Each
library's docs break into a large body plus a small detached island (5 cuGraph
pages, 2 NetworkX pages) that nothing in the crawled set links to. Those are
pages reachable only from navigation chrome, which the crawler deliberately
ignores — see the corpus bug below.

---

## 3. Tests

```bash
python tests/test_graphrag.py     # 10/10 passed
cd tests && python verify_tests.py # 8/8 caught a real defect in the original
```

The suite is written one test per bug found in the original. `verify_tests.py`
re-runs the same assertions against the original implementations, copied
verbatim from the archived source, and every one of them fails:

| Assertion | What the original did |
|---|---|
| scrape ignores navigation | took links from the whole page, so nav links leaked in |
| graph never invents nodes | `add_edge` on an uncrawled URL created a textless node |
| route kind is a closed set | compared the model's `'AQL'` (quoted) to `"AQL"` |
| graph questions are executed | returned `nx.pagerank(G, alpha=0.85)` as a **string** |
| allowlist blocks arbitrary names | `getattr(nx, name)` executed `write_gml` |
| impossible request raises | `parse_algorithm_code` threw `not enough values to unpack` |
| search is case insensitive | `"Install"` matched nothing |
| missing corpus raises | returned `None` and carried on |

The two remaining tests — *import has no side effects* and *components recover
library split* — cannot be run against the original at all, because it calls
`exit(1)` at import time. That is itself the headline finding.

---

## 4. The corpus bug, measured

Scoping extraction to `<article>` instead of the whole page:

| | Whole page | `<article>` only |
|---|---|---|
| Edges | 8,785 | 239 |
| Density | 0.345 | 0.009 |
| Top PageRank result | 5-way tie at 0.0498 on *Install, Gallery, Backends, Developer, home* | `DiGraph.edges` at 0.0290 |
| Page text began with | `Section Navigation … Copyright 2004-2025 … Built with Sphinx` | the page's actual prose |

Every Sphinx page carries the same navigation sidebar, so scraping whole pages
gave all 160 pages an identical set of outbound links. PageRank then ranked the
navigation menu. It returned a number, it never raised, and it was meaningless.

---

## 5. Dependencies

| | Original | Now |
|---|---|---|
| Declared requirements | 10 | 3 (+1 optional) |

Of the original ten: `arango` was the wrong package name (the driver is
`python-arango`), `cugraph` is not installable from PyPI, `deepseek` was never
imported, and `flask`, `beautifulsoup4` and `langchain-community` were used but
never declared — so `pip install -r requirements.txt` could not have produced a
working environment.
