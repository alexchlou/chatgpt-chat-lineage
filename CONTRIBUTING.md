# Contributing

Use Python 3.9+ and Node.js 20+. Core runtime helpers have no third-party dependencies. Optional report rendering and browser-view QA use Playwright.

```sh
python3 -B -m unittest discover -s tests -p 'test_*.py'
node --test tests/cua_workflow.test.cjs tests/recovery_integration.test.cjs
python3 scripts/build_demo.py --output build/demo
python3 scripts/check_release.py
```

For offline UI tests:

```sh
npm ci
npx playwright install chromium
mkdir -p build/qa
node tests/knowledge_graph_view.test.cjs build/demo/knowledge_graph/rename-knowledge-graph.html build/qa/ui.json
```

The UI test launches a fresh headless browser, blocks network requests, and uses synthetic reports only. It must never control an authenticated ChatGPT session. Run it with `PLAYWRIGHT_CHROME_CHANNEL=chrome` only if testing a local installed Chrome instead of bundled Chromium.

Preserve these contracts: frozen target order; exact URL and account identity; one save dispatch; append-only corrections; same-event idempotency; explicit unknown fields; two-ended source support; E0/E1/H semantics; quarantine after source change; manual Obsidian sections; one email dispatch per run and recipient.

Keep all documentation and product strings in English. Non-English browser control literals are intentional compatibility selectors and may remain in the AX adapter. Add synthetic regression cases when changing their behavior. Do not claim live browser validation from fixture tests.

Use a new branch and a concise pull request with the problem, resulting behavior, tests, and limits. Include no private data. Before publication, use Gitleaks in addition to the project's privacy checker. A maintainer may reproduce findings; neither self-review nor CI is independent certification.

## GitHub Actions template

The checked-in [workflow template](docs/ci-workflow.yml) is not active. To enable it, an owner with permission to write Actions workflows can copy it to `.github/workflows/ci.yml` and commit it. The publishing OAuth session lacked the workflow scope; this release therefore makes no claim of GitHub-hosted CI execution. The template pins third-party actions by commit and grants read-only repository permissions.
