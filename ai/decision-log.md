# AI decision log

The parent project thread is `6afd70b6-50bc-8191-8392-7bfe29d2a08d`. Worker thread IDs are listed in [the session index](session-index.csv). Entries below are decision summaries. The project conversation export is still incomplete.

| Decision | Effect on this submission | Verification and commit |
| --- | --- | --- |
| **Corrected proposal.** The candidate selected Flask, SQLite and Vue 3 after the assistant suggested Django and React. | One local Flask service can expose the JSON API and serve the Vue interface. | The choice is recorded in `AGENTS.md` at `e3fa94e`. Inspect the Flask API and SQLite connection code at `dae79b4` and the Vue interface at `d584c28`. |
| **Accepted transactional design.** Keep the certificate, issuance audit event and saved idempotent operation result in one transaction. | A retry can replay an existing outcome, and a failure that rolls back the operation cannot leave certificates or audit events behind. | See the bulk write flow in `writes.py` and database constraints in `schema.sql` at `dae79b4`. The writes worker (`6afd730b-ee40-8191-b723-8de514c7809a`) reported an eight-caller replay check and rollback checks using injected failures. |
| **Scope tradeoff.** The candidate chose to keep a revoked certificate revoked when the same course is issued again. | Existing certificate records preserve their serial number and history. The bulk action skips a previously certified learner. | The policy is recorded in `AGENTS.md` at `e3fa94e`. The duplicate enrollment check and uniqueness constraint can be inspected at `dae79b4`. |
