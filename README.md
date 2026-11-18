# CertDesk

CertDesk is an internal certificate administration console for two demo training providers. Select an administrator to search certificates, issue certificates to a course, inspect audit history, revoke a certificate or export the current results.

## Start

With Python 3.11 or newer and pip installed, run this command in the repository root.

```shell
python run.py
```

Open **http://127.0.0.1:5000**. On first use the launcher installs the declared dependencies into a local virtual environment and initializes SQLite. Initial dependency installation requires access to a Python package source. The Vue 3 production build and its license are included under `static/vendor/`. Flask serves both the page and the API on the same port. Subsequent launches preserve your demo data. To start with a new database, pass a fresh filename, for example `python run.py --db demo-fresh.sqlite3 --port 5001`.

| Administrator | Tenant | Time zone | Safety 101 course ID | Seed certificate |
| --- | --- | --- | --- | --- |
| `alice@east.test` | East | Australia/Sydney | 1 | `EAST-0001` (ID 1) |
| `bob@west.test` | West | Australia/Perth | 2 | `WEST-0001` (ID 2) |

Both tenants have a learner named Alex Lee. In East's Safety 101, Alex already has a certificate, Sam Chen has completed the course, and Jordan Park is incomplete. East also has First Aid (course ID 3). Both seeded Alex certificates were issued at `2026-01-10T13:30:00Z`.

## Use the API

Send `X-Actor: alice@east.test` or `X-Actor: bob@west.test` with every API request. This header selects a seeded demo identity. The server derives the tenant from that identity. Bulk issuance requires JSON and an `Idempotency-Key` header. For example, in PowerShell:

```powershell
$headers = @{ 'X-Actor' = 'alice@east.test'; 'Idempotency-Key' = 'safety-demo-1' }
Invoke-RestMethod 'http://127.0.0.1:5000/api/bulk-issue' -Method Post -Headers $headers -ContentType 'application/json' -Body '{"course_id":1}'
```

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/api/courses` | List the selected tenant's courses. |
| GET | `/api/certificates` | Search with `q`, sort with `sort` and `direction`, paginate with `page` and `page_size`. |
| GET | `/api/certificates/{id}` | Show certificate details, local issue time, and audit events. |
| POST | `/api/bulk-issue` | Issue to eligible learners on a course and return per-learner outcomes. Repeating the same key and JSON returns the original result. |
| POST | `/api/certificates/{id}/revoke` | Revoke the certificate. A repeated call returns the revoked status. |
| GET | `/api/certificates/export.csv` | Stream all matching rows with the same search and sort as the list. |

Search matches literal, case-insensitive substrings of learner names and serials. Supported sort fields are `learner`, `course`, `serial`, `date` and `status`. Use `asc` or `desc`. The default is descending tenant-local calendar date. Ties use ascending certificate ID. Export includes revoked certificates and all matching pages. The CSV columns are `learner_name`, `course_title`, `serial_number` and `issue_date`.

## Reproduce the acceptance scenarios

Run the verification script with the Python environment containing the declared dependencies. On Windows, use:

```powershell
.\.venv\Scripts\python.exe verify.py
```

On macOS or Linux the equivalent command is `.venv/bin/python verify.py`. If the launcher used dependencies already installed in your active interpreter, use `python verify.py`. The verifier starts a threaded HTTP server on an available loopback port, creates temporary databases, and prints each result. Add `--quick` to skip the 100,000-row benchmark.

| Scenario | Reproduction and expected result |
| --- | --- |
| A1. Tenant isolation | On a fresh demo, search Alex Lee as Bob and export. Only WEST-0001 appears. As Bob, request East certificate ID 1, post its revocation, or issue course ID 1. Each request returns 404. The verifier compares database counts before and after. |
| A2. Safe retry | Send two simultaneous Alice requests for course 1 using the same key and body, then replay sequentially. All responses carry the same operation and learner outcomes. Only Sam receives a new certificate and issuance audit. The verifier synchronizes independent HTTP clients. |
| A3. Key misuse | Reuse that key with course 3, or change the JSON by adding another field. Both return 409. Send the original request again to recover the first result. |
| A4. Learner outcomes | Issue East Safety 101 on a fresh demo. Sam is issued, Jordan is skipped as incomplete, and Alex is skipped as already certified. The verifier also exercises one rejected learner alongside a successful learner. |
| A5. DST and local dates | View the seeded Alex certificate as Alice and then as Bob. Sydney displays 2026-01-11 00:30 and Perth displays 2026-01-10 21:30. Compare the CSV issue dates. The verifier also places two distinct UTC instants on one Sydney date and checks the ID tie-break in the list and export. |
| A6. Export under load | Run the full verifier. It generates exactly 100,000 East certificates in a separate database, exports twice with a case-insensitive filter and ties on learner names, then checks every CSV row and the identical file hashes. During the first export, a test-only pause between streamed chunks gives a second HTTP client time to request the list. Each export must finish within 60 seconds. |
| A7. Revocation audit | Open EAST-0001, confirm revocation, then repeat the revocation via the API. Its history has one issuance and one revocation. Later bulk operations skip this learner with reason `revoked`. |

The verifier also checks invalid actors, sort and page bounds, literal search, header-only CSV, and detail consistency when a revocation commits between the certificate and audit reads.

To inspect the large dataset manually:

```shell
python seed.py --database benchmark.sqlite3 --count 100000
python run.py --db benchmark.sqlite3 --port 5001
```

The normal startup database is separate. On a freshly generated benchmark database, search `BENCH-` as Alice to match 99,999 rows, or `EAST-` to match all 100,000.

## Transaction and export design

SQLite foreign keys bind each enrollment, certificate and audit to its tenant. The application opens a connection per request. The shared query functions bind tenant IDs and values and allow-list sort expressions. List and CSV share their filtering and ordering logic. The certificate detail reads status and audit events in one snapshot. Tenant API responses carry `Cache-Control: no-store`. A streaming export uses its own read connection. WAL mode permits concurrent readers while keeping writes serialized.

Bulk issuance takes the SQLite write lock before looking up a prior operation. The stored key is scoped to the tenant and actor and paired with a hash of the canonical JSON body. The receipt, certificates, and audit rows commit together. A learner-specific certificate rule can fail within its own savepoint. An unexpected write or audit failure rolls back the entire batch. The verifier injects a failure while saving the final result, checks that no partial rows survived, and retries the same key.

Issuance timestamps are stored in UTC. IANA time-zone rules convert each timestamp for the tenant. Certificate uniqueness spans tenant, course and learner, including revoked certificates, so future batch issuance preserves a deliberate revocation.

## Submission status

See `ai/` for interaction evidence, decisions, and export limitations. The assessment's written answers are a separate candidate-authored deliverable.
