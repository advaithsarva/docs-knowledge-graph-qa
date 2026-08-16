"""Command line entry point:  build | ask | eval | serve."""

import argparse
import json
import os
import sys

from . import execute, graph, router, scrape

EVAL_SET = os.path.join(os.path.dirname(os.path.dirname(__file__)), "eval", "queries.json")


def cmd_build(args):
    print(f"Crawling (max {args.max_pages} pages per site)...")
    pages = scrape.crawl(max_pages=args.max_pages, delay=args.delay)
    if not pages:
        sys.exit("Crawl returned no pages; refusing to write an empty corpus.")
    graph.save_pages(pages, args.corpus)
    G = graph.build_graph(pages)
    print(f"Wrote {args.corpus}: {G.number_of_nodes()} pages, {G.number_of_edges()} links")


def cmd_ask(args):
    G = graph.load_graph(args.corpus)
    question = " ".join(args.question)
    chosen = router.route_llm(question) if args.llm else router.route(question)
    print(f"[route: {chosen.kind}{'/' + chosen.algorithm if chosen.algorithm else ''}]\n")
    try:
        print(execute.run(chosen, G))
    except (ValueError, KeyError) as exc:
        sys.exit(f"Cannot answer that: {exc}")


def cmd_eval(args):
    """Score the router against the labelled set, and print every failure."""
    with open(args.queries, encoding="utf-8") as f:
        cases = json.load(f)

    classify = router.route_llm if args.llm else router.route
    kind_ok = algo_ok = algo_total = 0
    failures = []

    for case in cases:
        got = classify(case["question"])
        if got.kind == case["kind"]:
            kind_ok += 1
        else:
            failures.append((case, got, "kind"))

        if case["kind"] == "graph":
            algo_total += 1
            if got.algorithm == case["algorithm"]:
                algo_ok += 1
            elif got.kind == case["kind"]:
                failures.append((case, got, "algorithm"))

    n = len(cases)
    print(f"Router: {'LLM' if args.llm else 'rules'}")
    print(f"  kind accuracy      {kind_ok}/{n} = {kind_ok / n:.3f}")
    print(f"  algorithm accuracy {algo_ok}/{algo_total} = {algo_ok / algo_total:.3f}"
          f"   (of {algo_total} graph questions)")
    print(f"\n{len(failures)} failure(s):")
    for case, got, what in failures:
        want = case["kind"] if what == "kind" else case["algorithm"]
        have = got.kind if what == "kind" else got.algorithm or "(none)"
        print(f"  [{what}] {case['question']!r}\n      want {want}, got {have}")

    if args.answer:
        G = graph.load_graph(args.corpus)
        print("\nAnswers were also executed to confirm every route runs:")
        for case in cases:
            try:
                execute.run(classify(case["question"]), G)
            except Exception as exc:
                print(f"  RAISED on {case['question']!r}: {exc}")


def cmd_serve(args):
    from .web import create_app

    create_app(args.corpus).run(host=args.host, port=args.port)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="graphrag", description=__doc__)
    parser.add_argument("--corpus", default=graph.DEFAULT_CORPUS, help="path to docs.json")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="crawl the docs sites into a corpus")
    b.add_argument("--max-pages", type=int, default=80, help="per site (default 80)")
    b.add_argument("--delay", type=float, default=0.3, help="seconds between requests")
    b.set_defaults(func=cmd_build)

    a = sub.add_parser("ask", help="ask a question")
    a.add_argument("question", nargs="+")
    a.add_argument("--llm", action="store_true", help="route with an LLM instead of rules")
    a.set_defaults(func=cmd_ask)

    e = sub.add_parser("eval", help="score the router on the labelled query set")
    e.add_argument("--queries", default=EVAL_SET)
    e.add_argument("--llm", action="store_true")
    e.add_argument("--answer", action="store_true", help="also execute every route")
    e.set_defaults(func=cmd_eval)

    s = sub.add_parser("serve", help="run the web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)
    s.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
