"""Measure whether link structure alone recovers which library a page belongs to.

Unlike eval/queries.json, the labels here are not written by hand: a page's
library is where it was crawled from. Connected components never see it.

Run:  python eval/structure.py
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx

from graphrag import graph

G = graph.load_graph()
components = sorted(nx.connected_components(G.to_undirected()), key=len, reverse=True)

agree = 0
print(f"{G.number_of_nodes()} pages, {G.number_of_edges()} links, "
      f"{len(components)} connected components\n")

for i, group in enumerate(components, 1):
    libs = Counter(G.nodes[n]["library"] for n in group)
    majority, count = libs.most_common(1)[0]
    agree += count
    print(f"  component {i}: {len(group):3} pages  majority={majority:9} "
          f"({', '.join(f'{k} {v}' for k, v in libs.most_common())})")

print(f"\npurity = {agree}/{G.number_of_nodes()} = {agree / G.number_of_nodes():.3f}")
print("(fraction of pages whose library matches their component's majority)")
