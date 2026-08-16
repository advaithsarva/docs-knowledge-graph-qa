"""Flask UI: a query box over the same router and executor the CLI uses.

The graph is loaded once by create_app() and closed over -- not at import
time, and not per request. The original opened a database connection at import
and called plt.show() inside a request handler, which blocks the serving
thread on any machine without a display.
"""

from flask import Flask, jsonify, render_template, request

from . import execute, graph, router


def create_app(corpus=None):
    app = Flask(__name__, template_folder="templates")
    G = graph.load_graph(corpus or graph.DEFAULT_CORPUS)

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            pages=G.number_of_nodes(),
            links=G.number_of_edges(),
        )

    @app.route("/ask", methods=["POST"])
    def ask():
        question = (request.form.get("query") or "").strip()
        if not question:
            return jsonify({"error": "Empty query."}), 400

        chosen = router.route(question)
        try:
            answer = execute.run(chosen, G)
        except (ValueError, KeyError) as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify({
            "route": chosen.kind + (f"/{chosen.algorithm}" if chosen.algorithm else ""),
            **answer.as_dict(),
        })

    return app
