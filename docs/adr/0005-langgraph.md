# ADR-0005: The flows are LangGraph graphs with durable checkpoints

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

The tailor flow has a loop (check, repair, check again) and a pause that can last hours: the person approves a draft later, often in another process. Hand-written code for this needs its own saved state, its own resume logic, and its own tests for both.

## Decision

- Each flow is an explicit `StateGraph`: named nodes, named edges, one typed state.
- The graph is compiled with the SQLite checkpointer, in the same database file.
- The approval step uses `interrupt`. Resuming is `Command(resume=...)` with the run's thread id.
- Nodes are plain functions that call the domain and the model port. LangChain model classes, agents and tools are not used: the model has no tools ([ADR-0012](0012-untrusted-postings.md)).
- Loops are bounded by a counter in the state, and by the graph's recursion limit as a second guard.

## Consequences

- **Good:** pause and resume across processes without custom code; the flow is readable as a picture.
- **Good:** each node is a function that is tested alone.
- **Cost:** a dependency with its own release rhythm. It is kept inside `masar.agent`.
- **Watch:** the state must stay serializable and small: ids and plain data, never a connection or a client.
