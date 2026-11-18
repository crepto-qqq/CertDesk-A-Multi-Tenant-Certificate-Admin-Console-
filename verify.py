"""Run live HTTP acceptance checks against disposable SQLite databases."""

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from werkzeug.serving import WSGIRequestHandler, make_server
from werkzeug.test import Client as WSGIClient

import db
from app import create_app


ALICE = "alice@east.test"
BOB = "bob@west.test"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args):
        pass


class ExportOverlap:
    """Pause the first real CSV response after its first chunk reaches the client."""

    def __init__(self, app):
        self.app = app
        self.started = threading.Event()
        self.resume = threading.Event()

    def __call__(self, environ, start_response):
        result = self.app(environ, start_response)
        if environ["PATH_INFO"] != "/api/certificates/export.csv" or self.started.is_set():
            return result
        return self.stream(result)

    def stream(self, result):
        try:
            for chunk in result:
                yield chunk
                if chunk and not self.started.is_set():
                    self.started.set()
                    if not self.resume.wait(timeout=15):
                        raise RuntimeError("List did not complete during the paused export")
        finally:
            if hasattr(result, "close"):
                result.close()


class Client:
    def __init__(self, port=None, wsgi=None):
        self.base = f"http://127.0.0.1:{port}/api"
        self.wsgi = wsgi

    def request(self, path, actor=ALICE, body=None, key=None, expected=200, csv_file=False):
        headers = {"X-Actor": actor}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        if self.wsgi is None:
            request = Request(self.base + path, data=data, headers=headers)
            try:
                response = urlopen(request, timeout=60)
            except HTTPError as err:
                response = err
            with response:
                content, status = response.read(), response.status
                cache_control = response.headers.get("Cache-Control", "")
        else:
            # Independent clients exercise Flask's full request and streaming paths.
            agent = WSGIClient(self.wsgi, use_cookies=False)
            response = agent.open("/api" + path, method="GET" if data is None else "POST",
                                  data=data, headers=headers, buffered=True)
            with response:
                content, status = response.get_data(), response.status_code
                cache_control = response.headers.get("Cache-Control", "")
        accepted = expected if isinstance(expected, tuple) else (expected,)
        check(status in accepted, f"{path}: expected {accepted}, got {status}: {content[:320]!r}")
        check("no-store" in cache_control.split(", "), f"{path}: API response allows caching")
        return content if csv_file else json.loads(content)

    def issue(self, key, course=1, actor=ALICE, expected=(200, 201), **extra):
        return self.request("/bulk-issue", actor, {"course_id": course, **extra}, key, expected)


@contextmanager
def service(database, overlap=False, in_process=False):
    app = create_app(str(database))
    wrapped = ExportOverlap(app) if overlap else app
    if in_process:
        try:
            yield Client(wsgi=wrapped), wrapped
        finally:
            if overlap:
                wrapped.resume.set()
        return
    server = make_server("127.0.0.1", 0, wrapped, threaded=True, request_handler=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(server.server_port), wrapped
    finally:
        if overlap:
            wrapped.resume.set()
        server.shutdown()
        thread.join()
        server.server_close()


def counts(database):
    with closing(sqlite3.connect(database)) as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("certificates", "audit_events", "operations"))


def execute(database, sql):
    with closing(sqlite3.connect(database)) as conn:
        conn.execute(sql)
        conn.commit()


def csv_rows(content):
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))


def check_isolation_and_dates(client, database):
    before = counts(database)
    for actor, cert_id, serial, local in (
        (ALICE, 1, "EAST-0001", "2026-01-11 00:30"),
        (BOB, 2, "WEST-0001", "2026-01-10 21:30"),
    ):
        detail = client.request(f"/certificates/{cert_id}", actor)
        check(detail["local_datetime"] == local, f"Local timestamp mismatch for {actor}")
        listing = client.request("/certificates?q=alEx%20leE", actor)
        check([r["serial"] for r in listing["items"]] == [serial], "Cross-tenant list")
        check(listing["items"][0]["local_date"] == local[:10], "Incorrect local date in list")
        rows = csv_rows(client.request("/certificates/export.csv?q=AlEx", actor, csv_file=True))
        check(rows[1:] == [["Alex Lee", "Safety 101", serial, local[:10]]],
              "Incorrect tenant/date in CSV")
    client.request("/certificates/1", BOB, expected=404)
    client.request("/certificates/1/revoke", BOB, body={}, expected=404)
    client.issue("wrong-tenant", actor=BOB, expected=(403, 404))
    check(counts(database) == before, "Cross-tenant requests changed database state")
    print("PASS A1 / A5: Bob's list and export contain only West, East detail and writes "
          "rejected; Sydney 2026-01-11 00:30 and Perth 2026-01-10 21:30 verified.")


def check_rollback(client, database):
    before = counts(database)
    # Reach the final result write after the certificate and its audit were inserted.
    execute(database, """CREATE TRIGGER verify_result_failure BEFORE UPDATE OF result_json ON operations
            BEGIN SELECT RAISE(ABORT, 'verification: forced result persistence failure'); END""")
    try:
        client.issue("audit-retry", expected=(500, 503))
        check(counts(database) == before, "Partial certificate, audit, or idempotency write")
    finally:
        execute(database, "DROP TRIGGER verify_result_failure")


def check_issuance(client, database):
    before = counts(database)
    gate = threading.Barrier(2)

    def issue_at_gate():
        gate.wait(timeout=5)
        return client.issue("audit-retry")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [pool.submit(issue_at_gate) for _ in range(2)]
        result = first.result()
        check(result == second.result() == client.issue("audit-retry"),
              "Parallel or sequential retries returned different results")
    outcomes = {r["learner"]: r for r in result["outcomes"]}
    check(Counter(r["outcome"] for r in result["outcomes"]) == {"issued": 1, "skipped": 2},
          "Incorrect counts for mixed eligibility")
    check(outcomes["Sam Chen"]["outcome"] == "issued", "Completed learner did not receive a certificate")
    for name in ("Alex Lee", "Jordan Park"):
        check(outcomes[name]["outcome"] == "skipped" and outcomes[name]["reason"],
              f"Missing skip outcome/reason for {name}")
    after = tuple(n + 1 for n in before)
    check(counts(database) == after, "Expected one new certificate, audit, and operation")
    client.issue("audit-retry", course=3, expected=409)
    client.issue("audit-retry", expected=409, source="changed")
    check(client.issue("audit-retry") == result and counts(database) == after,
          "Key misuse overwrote the first result or mutated state")
    issued_id = outcomes["Sam Chen"]["certificate_id"]
    audit = client.request(f"/certificates/{issued_id}")["audit"]
    check([e["action"] for e in audit] == ["ISSUED"] and audit[0]["actor_email"] == ALICE,
          "Missing issuance audit on the actual certificate")
    print("PASS rollback / A2 / A3 / A4: forced result persistence failure rolled back all writes; two "
          "simultaneous retries and a sequential replay returned one result; both payload "
          "conflicts returned 409; one learner issued, two skipped with reasons.")


def check_revocation(client, database):
    before = counts(database)
    for _ in range(2):
        client.request("/certificates/1/revoke", body={})
    detail = client.request("/certificates/1")
    check(detail["status"] == "REVOKED", "Certificate remains active after revocation")
    check(Counter(e["action"] for e in detail["audit"]) == {"ISSUED": 1, "REVOKED": 1},
          "Incorrect audit for twice-revoked certificate")
    check(counts(database) == (before[0], before[1] + 1, before[2]),
          "Repeated revocation was not idempotent")
    result = client.issue("after-revocation")
    check(all(r["outcome"] == "skipped" for r in result["outcomes"]), "Revoked learner reissued")
    rows = csv_rows(client.request("/certificates/export.csv?q=EAST-0001", csv_file=True))
    check(len(rows) == 2 and rows[1][2] == "EAST-0001", "Revoked certificate missing from export")
    print("PASS A7: two revocations created one revocation audit; subsequent bulk issuance "
          "skipped the revoked learner, and the certificate remained exportable.")


def check_isolated_failure(client, database):
    # Mix an accepted and a rejected learner in First Aid, in that order.
    execute(database, "INSERT INTO learners VALUES (7, 1, 'Test Learner')")
    execute(database, "INSERT INTO enrollments VALUES (1, 3, 7, 1)")
    execute(database, """CREATE TRIGGER verify_rule BEFORE INSERT ON certificates
            WHEN NEW.learner_id = 7
            BEGIN SELECT RAISE(ABORT, 'verification: individual learner rule'); END""")
    before = counts(database)
    try:
        result = client.issue("mixed-result", course=3)
        outcomes = {r["learner"]: r["outcome"] for r in result["outcomes"]}
        check(outcomes == {"Sam Chen": "issued", "Test Learner": "failed"},
              "Individual failure did not preserve the other learner's success")
        check(client.issue("mixed-result", course=3) == result, "Mixed-result replay differed")
        check(counts(database) == tuple(n + 1 for n in before), "Incorrect partial success writes")
    finally:
        execute(database, "DROP TRIGGER verify_rule")
    print("PASS individual failure: learner rule rejected one enrolment, preserved the "
          "successful certificate and audit, and replayed the same mixed result.")


def check_local_date_sort(client, database):
    # Both timestamps occur on Jan 11 in Sydney. A UTC-time sort would reverse their IDs.
    execute(database, """UPDATE certificates SET issued_at='2026-01-10T15:30:00Z'
            WHERE tenant_id=1 AND learner_id=3 AND course_id=1""")
    with closing(sqlite3.connect(database)) as conn:
        expected = [r[0] for r in conn.execute(
            "SELECT serial FROM certificates WHERE tenant_id=1 AND course_id=1 ORDER BY id")]
    listing = client.request("/certificates?sort=date&direction=desc")
    list_serials = [r["serial"] for r in listing["items"] if r["course"] == "Safety 101"]
    exported = csv_rows(client.request("/certificates/export.csv?sort=date&direction=desc", csv_file=True))
    csv_serials = [r[2] for r in exported[1:] if r[1] == "Safety 101"]
    check(len(expected) == 2 and expected == list_serials == csv_serials,
          "Same local calendar date did not use the certificate ID tiebreaker")
    print("PASS A5 sorting: two different UTC instants on the same Sydney date tie in both list and CSV.")


def check_read_boundaries(client):
    client.request("/certificates", actor="", expected=401)
    client.request("/courses", actor="unknown@example.test", expected=401)
    for path in (
        "/certificates?page=0", "/certificates?page_size=201", "/certificates?sort=unknown",
        "/certificates/export.csv?direction=unknown",
    ):
        client.request(path, expected=400)
    empty = {"items": [], "total": 0}
    check(client.request("/certificates?q=%25") == empty, "Search must treat % literally")
    check(client.request("/certificates?q=missing") == empty, "Missing search should return no rows")
    check(client.request("/certificates?page=2", BOB) == {"items": [], "total": 1},
          "An out-of-range page should preserve the total")
    exported = csv_rows(client.request("/certificates/export.csv?q=missing", csv_file=True))
    check(exported == [["learner_name", "course_title", "serial_number", "issue_date"]],
          "An empty export must still contain the CSV header")
    print("PASS read boundaries: actor, sort and pagination validation, literal search and empty CSV.")


def check_detail_snapshot(client):
    format_fields = db._fields
    with ThreadPoolExecutor(max_workers=1) as writer:
        def format_during_revocation(row):
            # Keep the writer in a separate request context even in WSGI mode.
            revoke = writer.submit(client.request, "/certificates/2/revoke", BOB, body={})
            revoke.result(timeout=5)
            return format_fields(row)

        with patch.object(db, "_fields", format_during_revocation):
            before = client.request("/certificates/2", BOB)
    after = client.request("/certificates/2", BOB)
    check(before["status"] == "ACTIVE" and [event["action"] for event in before["audit"]] == ["ISSUED"],
          "An in-flight detail mixed state from before and after revocation")
    check(after["status"] == "REVOKED" and
          [event["action"] for event in after["audit"]] == ["ISSUED", "REVOKED"],
          "A subsequent detail did not see the completed revocation")
    print("PASS concurrent detail: certificate status and audit share one snapshot across a revoke.")


def expected_export(database):
    zone = ZoneInfo("Australia/Sydney")
    with closing(sqlite3.connect(database)) as conn:
        east_count = conn.execute("SELECT COUNT(*) FROM certificates WHERE tenant_id=1").fetchone()[0]
        check(east_count == 100000, f"Expected exactly 100000 East certificates, got {east_count}")
        rows = conn.execute("""
            SELECT l.name, c.title, t.serial, t.issued_at
            FROM certificates t
            JOIN learners l ON l.id=t.learner_id AND l.tenant_id=t.tenant_id
            JOIN courses c ON c.id=t.course_id AND c.tenant_id=t.tenant_id
            WHERE t.tenant_id=1 AND (lower(t.serial) LIKE '%bench-%' OR lower(l.name) LIKE '%bench-%')
            ORDER BY l.name COLLATE NOCASE ASC, t.id ASC
        """)
        result = [[name, course, serial, datetime.fromisoformat(utc).astimezone(zone).date().isoformat()]
                  for name, course, serial, utc in rows]
    check(0 < len(result) < east_count, "Benchmark must exercise an actual search subset")
    check(len({r[0] for r in result}) < len(result), "Benchmark must exercise equal sort keys")
    return result


def check_export(client, overlap, database):
    expected = expected_export(database)
    path = "/certificates/export.csv?" + urlencode({"q": "bEnCh-", "sort": "learner", "direction": "asc"})

    def fetch():
        start = monotonic()
        data = client.request(path, csv_file=True)
        elapsed = monotonic() - start
        check(elapsed < 60, f"Export exceeded the time limit: {elapsed:.3f}s")
        parsed = csv_rows(data)
        check(parsed[0] == ["learner_name", "course_title", "serial_number", "issue_date"],
              "Incorrect CSV header")
        check(parsed[1:] == expected, "CSV membership, order, or values differ")
        return hashlib.sha256(data).hexdigest(), elapsed

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(fetch)
        try:
            check(overlap.started.wait(timeout=30), "First export never began streaming")
            start = monotonic()
            listing = client.request("/certificates?page_size=1")
            list_time = monotonic() - start
            check(listing["total"] == 100000 and len(listing["items"]) == 1, "Concurrent list failed")
        finally:
            overlap.resume.set()
        first_digest, first_time = first.result()
    second_digest, second_time = fetch()
    check(first_digest == second_digest, "Repeated exports differ")
    print(f"PASS A6: {len(expected):,} filtered rows from 100,000 East certificates; "
          f"exports {first_time:.3f}s / {second_time:.3f}s; list during first stream "
          f"{list_time:.3f}s; equal SHA-256 {first_digest}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip the A6 100,000-row benchmark")
    parser.add_argument("--in-process", action="store_true",
                        help="exercise Flask through WSGI when loopback TCP is unavailable")
    args = parser.parse_args()
    print("Transport:", "in-process WSGI" if args.in_process else "loopback HTTP", flush=True)
    with TemporaryDirectory(prefix="certdesk-verify-") as tmp:
        demo = Path(tmp) / "demo.sqlite"
        with service(demo, in_process=args.in_process) as (client, _):
            check_isolation_and_dates(client, demo)
            check_rollback(client, demo)
            check_issuance(client, demo)
            check_revocation(client, demo)
            check_isolated_failure(client, demo)
            check_local_date_sort(client, demo)
            check_read_boundaries(client)
            check_detail_snapshot(client)
        if not args.quick:
            benchmark = Path(tmp) / "benchmark.sqlite"
            db.initialize(str(benchmark))
            db.generate(str(benchmark), count=100000)
            with service(benchmark, overlap=True, in_process=args.in_process) as (client, overlap):
                check_export(client, overlap, benchmark)


if __name__ == "__main__":
    main()
