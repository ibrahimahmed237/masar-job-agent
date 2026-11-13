# ADR-0003: Masar never acts outside the machine; approval is a human act

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

An agent that applies or sends messages by itself can do harm that cannot be undone: a wrong letter to the one company that mattered, the same message twice, an application the person did not want.

## Decision

- Masar has no code that sends an email, posts a message, submits a form or logs in anywhere.
- Its network use is: reading the public job-board APIs of the watchlist, and calling the configured model provider.
- It writes only inside its own folder, and into the export folder the person names in a command.
- A draft becomes a document only when the person approves it. Approving, rejecting and moving an application exist only in the CLI.
- The MCP server has no tool that approves, rejects, moves or exports. An assistant can prepare; only the person decides.

## Consequences

- **Good:** nothing Masar does needs to be taken back.
- **Good:** the tool is safe to give to an assistant.
- **Cost:** the person copies the text into the application form themselves.
- **Watch:** a new feature that "just sends" is a new ADR, not a small change.
