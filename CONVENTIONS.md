# Conventions

The conventions that `osaudit` checks, and the interfaces it shares with the research agent, are specified in one place:
[CONVENTIONS.md of agentic-scientifc-method](https://github.com/ASSERT-KTH/agentic-scientifc-method/blob/main/CONVENTIONS.md).

They live there because the research agent works earlier in the process: it writes the pre-registrations, exploration logs and results that `osaudit` audits afterwards.
That document covers the repository layout (`audit.toml`, `[study]`), the study (pre-registration and exploration-log formats, confirmatory and exploratory runs), results provenance, numbers, quotes, references and reviews.
Rule ids printed by `osaudit` (`study/…`, `numbers/…`, `results/…`, `quotes/…`) are the ones used there.
