# ADR-0010: One small model port, two adapters, no provider SDK

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

Masar needs one thing from a model: messages in, text out, with token counts. Provider SDKs bring many features Masar must not use (tools, agents) and many dependencies.

## Decision

- The port is one method: `complete(messages, max_output_tokens) -> ChatResult(text, tokens_in, tokens_out, model)`.
- Two adapters over `httpx`: an OpenAI-compatible one (`/chat/completions`, which also covers local and hosted compatible servers) and an Anthropic one (`/v1/messages`).
- JSON is asked for in the prompt and parsed by Masar's own code. Provider-specific structured-output features are not relied on.
- A scripted model implements the same port for tests.

## Consequences

- **Good:** any provider, or a local model, with one setting; the whole flow runs in tests with no network.
- **Cost:** no streaming, no provider-side schema enforcement. Masar's parser and one retry cover malformed output.
