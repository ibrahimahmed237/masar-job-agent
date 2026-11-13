# ADR-0004: Postings come from public job-board APIs and pasted text only

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

Large job sites forbid scraping, change their pages often and sit behind logins. Many companies, though, publish their openings through the public JSON API of the job-board product they use.

## Decision

| Source | Endpoint | Auth |
|---|---|---|
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true` | None |
| Lever | `GET https://api.lever.co/v0/postings/{site}?mode=json` (EU: `api.eu.lever.co`) | None |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{board}` | None |
| Manual | Text pasted or read from a file | — |

- The watchlist names the companies and their boards. Masar does not crawl or discover.
- No site that needs a login, and no site whose terms forbid automated reading.
- Each fetch has a timeout, a size limit, a named user agent, and one request per board.

## Consequences

- **Good:** legal, stable and cheap. Three small clients cover a large share of technology companies.
- **Cost:** a company on another system is added by pasting its posting.
- **Watch:** these APIs can change. Each client reads defensively and reports what it could not read.
