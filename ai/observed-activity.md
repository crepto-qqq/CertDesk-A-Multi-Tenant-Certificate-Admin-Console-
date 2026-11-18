# Observed tool activity

This partial record preserves the repository-inspection worker's original project-specific command results and the commit timestamps produced by Git. Times below are UTC. Git author timestamps describe commits and do not measure session duration.

## Initial repository inspection

The worker ran `git --no-optional-locks status --porcelain=v1 --branch --untracked-files=all` from the clone. Its complete output was:

```text
## main...origin/main
```

`git rev-parse --verify --quiet HEAD` returned:

```text
af755d7f2e35e1871ed5a892e6da2ab7e40b019d
```

`git ls-files` returned `README.md`. Reading that file returned the single title `# CertDesk-A-Multi-Tenant-Certificate-Admin-Console-`. `git rev-list HEAD --count` returned `1`. The repository-inspection worker sent these findings back to the project thread.

## Recorded project changes

| UTC time on 2026-11-18 | Commit | Git subject |
| --- | --- | --- |
| 09:30:51 | `af755d7` | Initial commit |
| 09:44:08 | `e3fa94e` | Record confirmed scope and verification constraints |
| 09:46:15 | `dae79b4` | Implement tenant-scoped certificate workflows and atomic retry handling |
| 09:47:26 | `d584c28` | Add English Vue console for certificate administration |

To inspect actual per-file changes, run `git show <commit>` for the listed revisions.

## Export lookup

The evidence worker looked up the project session and its own thread by their runtime IDs in the local native session directory, archive, thread index and per-thread activity store. No matching records were returned. The root thread and the evidence worker independently requested the root thread using the desktop thread reader. Both received:

```text
tool call error: tool call failed for `codex_app/read_thread`

Caused by:
    Mcp error: -32000: Codex app tool request failed
```

The candidate was informed that the project-only conversation and its tool activity still need to be exported. This document does not cover every worker action.

## Worker messages

The evidence worker received these original activity reports in the order shown. The workers did not provide native per-message timestamps.

**Frontend**

> Frontend process $env:CODEX_THREAD_ID = 6afd731c-70d4-8191-ba34-ce14f867a0ab, $env:CODEX_SESSION_ID = 6afd70b6-50bc-8191-8392-7bfe29d2a08d. Purpose: implementation and UI verification of the Vue certificate console. Parent owns commits.

**Writes**

> Thread 6afd730b-ee40-8191-b723-8de514c7809a, session 6afd70b6-50bc-8191-8392-7bfe29d2a08d. Implemented writes.py, checked 8-way SQLite concurrency, key replay/misuse, tenant isolation, repeated revoke, partial vs systemic rollback with fault injection. Also located independent Vue 3.5.43 distro and verified SHA256. Parent handles commits.

**Verification**

> Verification thread 6afd732d-6e04-8191-8003-e44209491085, CODEX_SESSION_ID 6afd70b6-50bc-8191-8392-7bfe29d2a08d. Feature is live HTTP A1–A7 acceptance and transaction failure verification; test execution pending environment deps.

**Storage**

> Storage thread 6afd72f5-90d4-8191-892b-48c068f28080, session 6afd70b6-50bc-8191-8392-7bfe29d2a08d. Implemented db.py, schema.sql and seed.py. Verified two tenant-local dates, FK integrity, exactly 100k East records, ordering/ties/pagination, generated fixture audit and repeatable seed. Local IANA package discovered after venv-timezone check failed.

**Verification follow-up**

> Full verify.py --in-process actually passed at 20:51 Sydney, A1–A7 + systemic rollback + isolated failure, 99,999 exported rows, durations 0.531 s / 0.765 s; concurrent list 0.078 s; equal SHA 18cbb4dcbd325ea53142394df25b95fc62ad0403f28fd7efd75f5123e0046278.

The reported test invocation above used Flask's in-process test path. The time in this verbatim message corresponds to 09:51 UTC.

## Loopback HTTP acceptance run

At approximately 10:00 UTC on 2026-11-18, Codex session `01a1ee17-db08-7861-a566-bfab0dfe9750` ran `& '.\.venv\Scripts\python.exe' -B -u verify.py` from the repository root. The verifier printed `Transport: loopback HTTP` and exited with code 0. It used a threaded server and disposable SQLite databases.

| Check | Observed result |
| --- | --- |
| A1 | Bob's list and CSV held only West data. East detail, revocation and bulk issuance were rejected. The database counts were unchanged. |
| A2–A4 and rollback | Two concurrent requests and a sequential replay received the same result. One certificate and one issuance audit were created. Both changed payloads returned 409. A forced failure saving the result raised the expected `sqlite3.IntegrityError` and rolled back certificates, audit events and the idempotency record. An isolated learner failure preserved another learner's successful issuance. |
| A5 | Sydney displayed `2026-01-11 00:30` and Perth displayed `2026-01-10 21:30`. The list and CSV both used the stable tie-break for timestamps on the same Sydney calendar date. |
| A6 | From 100,000 East certificates, both exports contained the same 99,999 filtered rows in order. The runs took 0.625 and 0.547 seconds. A list request returned in 0.094 seconds while the first stream was held open by the verifier. Both exports had SHA-256 `18cbb4dcbd325ea53142394df25b95fc62ad0403f28fd7efd75f5123e0046278`. |
| A7 | Two revocation requests produced one revocation audit. Later issuance skipped the revoked learner and the certificate remained exportable. |

This entry is a summary of the run. The follow-up session's native transcript and tool activity are part of the outstanding export evidence.

## Startup smoke check

At approximately 10:02 UTC, worker `01a1ee18-187c-7012-afed-3486f556b9b8` ran `python run.py --port 62690 --db <temporary SQLite path>` using the system Python. The launcher reused the existing virtual environment and initialized the demo database. Over loopback HTTP, the SPA document, the bundled Vue script, and Alice's courses API all returned 200. The worker stopped the test server and removed the temporary database. This check covered startup with existing dependencies and HTTP responses.

An initial PowerShell test wrapper was rejected before execution. The replacement Python test driver first failed to load the Sydney time zone under the system interpreter. Running the driver under the existing virtual environment allowed the system Python launcher itself to be verified.

## Hardening and boundary checks

On 2026-11-18 at approximately 10:10 UTC, the root follow-up session ran `.venv/Scripts/python.exe -B -u verify.py` with Flask 3.1.3 and Werkzeug 3.1.9. `pip check` passed, then the threaded loopback HTTP verifier passed A1–A7, rollback and the added read checks. Both filtered exports returned 99,999 rows in the expected order with identical hashes (0.734 and 0.656 seconds). The list returned successfully in 0.094 seconds during the first stream.

| Area | Change or observed result |
| --- | --- |
| Read consistency and caching | A detail request takes one SQLite snapshot for status and audit. The verifier commits a revoke between the reads and checks a consistent result and a fresh subsequent result. API responses carry `Cache-Control: no-store`. |
| Read boundaries | Missing and unknown actors, unsupported sorts and page bounds, literal percent search, an empty CSV and an out-of-range page passed. |
| Write boundaries | Worker `01a1ee1e-bb4b-7c20-a76a-b058d4aecf88` verified missing keys, invalid and unknown IDs, simultaneous issuance with different keys, independent replay by different actors, empty course replay and four concurrent revocations. |
| Browser | Worker `01a1ee1e-acf5-7bf1-ab7d-5e7548e34dcd` used headless Chromium with a live local Flask server and a disposable database. Paging, empty states, list retry, delayed responses during tenant switching, CSV download, same-key retry after a committed response was lost, and revocation with detail reload failure all passed. A successful revocation message now remains visible while the detail reload is retried. |
| Clean startup | The writes worker ran `python run.py --port 49334 --db smoke.sqlite3` in a disposable source copy without a database or virtual environment. It installed Flask 3.1.3, Werkzeug 3.1.9 and tzdata 2025.2. The home page and seeded Alice list returned HTTP 200 in approximately 17 seconds. |

The first in-process snapshot test shared an application context between the nested Flask clients and failed Windows temporary database cleanup. The verifier gave the writer a separate thread and both loopback HTTP and quick in-process runs then passed. The first Chromium run hit an ambiguous text selector. The browser worker scoped the selector and reran the checks successfully.

The fixes and reproducible check are in commit `853f75f5ce2972e325d11ac679cee4ee43c7d761`. Flask and Werkzeug were updated using the maintainers' [Flask 3.1.3](https://flask.palletsprojects.com/en/stable/changes/#version-3-1-3) and [Werkzeug 3.1.9](https://werkzeug.palletsprojects.com/en/stable/changes/#version-3-1-9) release notes.
