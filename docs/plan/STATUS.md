# Status

Where the work stands right now. This file is updated after every milestone.

## Now

| | |
|---|---|
| **Phase** | Build |
| **Done** | Design; M0 to M4 |
| **In progress** | M5 — Storage and sources |
| **Next** | M6 — CLI and MCP server |

See the milestones in [PLAN.md](PLAN.md).

## Milestones

| # | Milestone | State | Review |
|---|---|---|---|
| — | Design | Done | [000](../reviews/000-design.md) |
| M0 | Foundation | Done | [001](../reviews/001-m0-m3-domain.md) |
| M1 | Career file and job model | Done | [001](../reviews/001-m0-m3-domain.md) |
| M2 | Screen and score | Done | [001](../reviews/001-m0-m3-domain.md) |
| M3 | Claim checks | Done | [001](../reviews/001-m0-m3-domain.md) |
| M4 | Agent | Done | [002](../reviews/002-m4-agent.md) |
| M5 | Storage and sources | Not started | |
| M6 | CLI and MCP server | Not started | |
| M7 | Evaluations | Not started | |
| M8 | Hardening | Not started | |

## Decisions

| Topic | Decision |
|---|---|
| Idea | Masar: a personal job-hunt agent that cannot invent claims |
| Stack | Python 3.13, LangGraph, Pydantic, SQLite, Typer, the MCP Python SDK |
| Shape | A pure domain with thin hosts |
| AI | The model writes, the code verifies |
| Docs | Simple technical English, with diagrams |
| Process | Build one small component, test it, review it, fix it, review again. Full review at the end |

## Open questions

| # | Question | Needed for |
|---|---|---|
| 1 | The project name: "Masar" is a working name | Before the first public push |
| 2 | Real model numbers for the evaluations | After M7, with the owner's key |

## Log

| Date | What happened |
|---|---|
| 2026-11-13 | Idea chosen. Design written. |
| 2026-11-13 | Design reviewed: 16 fixes. |
| 2026-11-13 | M0 to M3 done: tooling, career file, skills, job grounding, screen, evidence checks, score, claim checks, document assembly. 223 tests. |
| 2026-11-13 | M4 done: model session, prompts, the intake and tailor graphs, pause and resume from SQLite. 316 tests. |
