# Low-level designs

One page per part. Read the [high-level design](../DESIGN.md) first.

| Page | Part |
|---|---|
| [domain](domain.md) | The career file, postings and jobs, application states |
| [matching](matching.md) | Screening against hard limits, evidence checks, the score |
| [grounding](grounding.md) | The claim checks that keep a document honest, and how a document is assembled |
| [agent](agent.md) | The model session, the prompts, the intake graph and the tailor graph |
| [adapters](adapters.md) | SQLite, the job boards, the model providers, files and settings |
| [interfaces](interfaces.md) | The CLI and the MCP server |
| [evaluation](evaluation.md) | The evaluation sets and how they are scored |

## Repository layout

```text
masar/
├── src/masar/
│   ├── domain/        pure rules: career file, job, screen, score, claims, states
│   ├── ports/         what the world must provide
│   ├── agent/         the graphs, prompts and model session
│   ├── app/           use cases
│   ├── adapters/      SQLite, model providers, job boards, files
│   ├── cli/           the masar command
│   └── mcp_server/    the MCP server
├── tests/             one folder per package, plus architecture tests
├── evals/             evaluation sets and saved results
├── examples/          an invented career file and watchlist
└── docs/              design, decisions, plan, reviews
```
