# Validation and release scope

The public edition is verified with synthetic fixtures and offline artifacts. It must not be described as a live rename or a real Gmail/Obsidian acceptance test.

Run the commands in CONTRIBUTING.md to reproduce Python/Node regression tests, the synthetic demo, the offline graph browser test, and the source privacy check. Release-specific counts, tool versions, and asset hashes are recorded in the release notes and SHA256 manifest.

| Layer | Meaning |
|---|---|
| Python/Node tests | Synthetic journal, save recovery, evidence, export, and mail-state behavior |
| Offline browser QA | Rendered synthetic graph, interaction, responsive layout, and no network requests |
| Privacy checker + Gitleaks | Tested source/history/archive bytes match the included detection rules |
| Source ZIP manifest | Listed archive bytes match their SHA-256 hashes |
| Live ChatGPT save | NOT_RUN for this public edition |
| Live Gmail delivery/rendering | NOT_RUN for this public edition |
| Native Obsidian UI | NOT_RUN for this public edition |
| Model routing behavior | NOT_RUN; routing cases are an instruction contract |
| Independent certification | Not performed |

The earlier local implementation informed the recovery design. Private operational records and real-data tests are not part of this public package and are not used as public release evidence. Tests that intentionally use historical source types still run only on fictional data.

## Local release-candidate results

- 86 Python tests and 43 Node tests passed on Python 3.9.6 / Node.js 22.17.1.
- Playwright 1.62.1 with an isolated installed Chrome passed 18 offline view checks at widths 320, 420, 736, 1000, and 1440 pixels, plus dark mode. No external requests occurred.
- Offline PDF rendering produced a nonempty PDF from the synthetic report. This is artifact rendering, not Gmail delivery.
- The demo retained one blocked event and one correction; identical event replay, graph export, and Obsidian synchronization were idempotent.
- Gitleaks 8.30.1 source scan returned zero findings; its separate synthetic token control returned one finding. Default rules, no custom allowlist, archive/decode depth 3, redacted reports. The binary was downloaded from the official release and checked against its published SHA-256 inventory.
- Release ZIP, Git history, metadata, and remote checks are performed during publication; their final receipts and hashes belong to the release, not this pre-publication source claim.

GitHub-hosted CI: **NOT_RUN**. The publishing OAuth session did not permit creating Actions workflows. `docs/ci-workflow.yml` is provided as an inactive template; the owner may enable it with an appropriately authorized connection.
