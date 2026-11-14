# Evaluation sets

Invented data for measuring the steps where a model decides something. The design is in [docs/lld/evaluation.md](../docs/lld/evaluation.md). New to it? [How the evaluations work](HOW-IT-WORKS.md) explains them in plain words.

| File | What it measures |
|---|---|
| `claims.json` | The claim checks: planted false claims caught, honest blocks flagged |
| `extraction.json` | How well a model reads a posting |
| `assessment.json` | How well a model judges requirements against facts, before and after the evidence checks |
| `injection.json` | Whether instructions hidden in a posting change the result |

Run one with `masar eval <name>`. Results are written to `results/` and committed.

Every person, company and posting here is made up.
