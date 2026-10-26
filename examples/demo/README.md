# Synthetic demo

Download or clone the repository and open `index.html` locally. This standalone interactive report makes no network requests. The synthetic identifiers are not links to real conversations.

All eight conversations, titles, tags, and analyst assertions are fictional. The generator creates four E0 tag-overlap edges, two E1 metadata-compatibility edges, and three H hypotheses, plus a separate analyst-domain view. One conversation deliberately remains isolated. A simulated blocked event is retained alongside its later no-save correction.

The report supports evidence and source filters, search, one-hop focus, provenance inspection, title history, run outcomes, and CSV export. Graph positions and degree do not measure evidential strength or research priority.

Rebuild into a new directory:

```sh
python3 scripts/build_demo.py --output build/demo
```

The generated folder includes a temporary synthetic journal, graph files, CSV exports, an Obsidian demo vault, and a summary of idempotency checks. None of these operations access ChatGPT or Gmail. The ready-made `index.html` is an illustrative snapshot; newly generated update IDs can differ with source-code changes.
