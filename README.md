# Masar

A personal job-hunt agent that cannot invent claims.

*Masar* (مسار) is the Arabic word for "path".

> **Status:** design. See [docs/plan/STATUS.md](docs/plan/STATUS.md).

Masar collects job postings, screens and scores them against your own career file, drafts a tailored CV, cover letter and outreach message, and tracks your applications. It runs on your machine, for you alone.

The rule that shapes everything: **the model writes, the code verifies.** Every sentence about you must rest on a fact you wrote yourself. Code checks each technology, number, employer and title in a draft against those facts, and removes what it cannot verify. Masar never sends or applies; you approve every draft.

## Docs

| Document | What is in it |
|---|---|
| [Design](docs/DESIGN.md) | The high-level design: context, parts, flows, security, testing |
| [Low-level designs](docs/lld/README.md) | One page per part |
| [Architecture decisions](docs/adr/README.md) | Why each important choice was made |
| [Glossary](docs/GLOSSARY.md) | The words used in the code and the docs |
| [Build plan](docs/plan/PLAN.md) | Milestones and when each one counts as done |
| [Status](docs/plan/STATUS.md) | Where the work stands today |
| [Contributing](CONTRIBUTING.md) | Docs style, commits, and the build-test-review loop |

## License

[MIT](LICENSE)
