"""SQLite connection management, tenant-scoped certificate reads and demo fixtures."""
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo


@lru_cache(maxsize=2048)
def local_datetime(utc_timestamp, timezone):
    instant = datetime.fromisoformat(utc_timestamp.replace("Z", "+00:00"))
    return instant.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")


def connect(path):
    conn = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("local_datetime", 2, local_datetime, deterministic=True)
    conn.create_function("casefold", 1, str.casefold, deterministic=True)
    return conn


def tenant_query(conn, tenant_id, sql, **params):
    if ":tenant_id" not in sql:
        raise ValueError("Tenant-scoped SQL must bind :tenant_id")
    return conn.execute(sql, {**params, "tenant_id": tenant_id})


@contextmanager
def read_snapshot(conn):
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN")
    try:
        yield
    finally:
        conn.rollback()  # End the read-only snapshot.


def initialize(path):
    with closing(connect(path)) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Schema creation is repeatable. Seed once to preserve subsequent user actions.
            if not conn.execute("SELECT 1 FROM tenants LIMIT 1").fetchone():
                _seed_demo(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _seed_demo(conn):
    conn.executemany("INSERT INTO tenants VALUES (?, ?, ?)", [
        (1, "East", "Australia/Sydney"), (2, "West", "Australia/Perth")
    ])
    conn.executemany("INSERT INTO admins VALUES (?, ?)", [
        ("alice@east.test", 1), ("bob@west.test", 2)
    ])
    conn.executemany("INSERT INTO courses VALUES (?, ?, ?)", [
        (1, 1, "Safety 101"), (2, 2, "Safety 101"), (3, 1, "First Aid")
    ])
    conn.executemany("INSERT INTO learners VALUES (?, ?, ?)", [
        (1, 1, "Alex Lee"), (2, 2, "Alex Lee"), (3, 1, "Sam Chen"),
        (4, 1, "Jordan Park"), (5, 2, "Taylor Wong"), (6, 2, "Casey Reed")
    ])
    conn.executemany("INSERT INTO enrollments VALUES (?, ?, ?, ?)", [
        (1, 1, 1, 1), (1, 1, 3, 1), (1, 1, 4, 0), (2, 2, 2, 1),
        (2, 2, 5, 1), (2, 2, 6, 0), (1, 3, 3, 1)
    ])
    issued_at = "2026-01-10T13:30:00Z"
    for tenant, serial, email in [(1, "EAST-0001", "alice@east.test"),
                                  (2, "WEST-0001", "bob@west.test")]:
        conn.execute("""INSERT INTO certificates
            (id, tenant_id, course_id, learner_id, serial, issued_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')""",
            (tenant, tenant, tenant, tenant, serial, issued_at))
        conn.execute("""INSERT INTO audit_events
            (tenant_id, certificate_id, actor_email, action, created_at)
            VALUES (?, ?, ?, 'ISSUED', ?)""", (tenant, tenant, email, issued_at))


def actor(conn, email):
    row = conn.execute("""SELECT a.email, a.tenant_id, t.timezone, t.name AS tenant
        FROM admins a JOIN tenants t ON t.id = a.tenant_id WHERE a.email = ?""", (email,)).fetchone()
    return dict(row) if row else None


def courses(conn, tenant_id):
    rows = tenant_query(conn, tenant_id, """SELECT id, title FROM courses
        WHERE tenant_id = :tenant_id ORDER BY title COLLATE NOCASE, id""")
    return [dict(row) for row in rows]


_JOIN = """
    FROM certificates c
    JOIN tenants t ON t.id = c.tenant_id
    JOIN learners l ON l.id = c.learner_id AND l.tenant_id = c.tenant_id
    JOIN courses co ON co.id = c.course_id AND co.tenant_id = c.tenant_id
    WHERE c.tenant_id = :tenant_id
"""
_COLUMNS = """SELECT c.id, l.name AS learner, co.title AS course, c.serial,
    c.status, c.issued_at, t.timezone"""
_SORTS = {
    "learner": "casefold(l.name)", "course": "casefold(co.title)",
    "serial": "casefold(c.serial)", "status": "c.status",
    "date": "substr(local_datetime(c.issued_at, t.timezone), 1, 10)",
}


def _fields(row):
    item = dict(row)
    item["local_datetime"] = local_datetime(item["issued_at"], item.pop("timezone"))
    item["local_date"] = item["local_datetime"][:10]
    return item


def certificate(conn, tenant_id, cert_id):
    with read_snapshot(conn):
        row = tenant_query(conn, tenant_id, _COLUMNS + _JOIN + " AND c.id = :cert_id",
                           cert_id=cert_id).fetchone()
        if not row:
            return None
        item = _fields(row)
        events = tenant_query(conn, tenant_id, """SELECT actor_email, action, created_at
            FROM audit_events WHERE tenant_id = :tenant_id AND certificate_id = :cert_id
            ORDER BY id""", cert_id=cert_id)
        item["audit"] = [{**dict(event), "local_datetime": local_datetime(event["created_at"], row["timezone"])}
                         for event in events]
    return item


def _filter_and_order(search, sort, direction):
    if sort not in _SORTS or direction.lower() not in ("asc", "desc"):
        raise ValueError("Unsupported sort field or direction")
    filters = _JOIN
    params = {}
    if search:
        # instr treats search text literally, including SQL wildcard characters.
        filters += " AND (instr(casefold(l.name), :term) > 0 OR instr(casefold(c.serial), :term) > 0)"
        params["term"] = search.casefold()
    order = f" ORDER BY {_SORTS[sort]} {direction.upper()}, c.id ASC"
    return filters, order, params


def list_certificates(conn, tenant_id, search, sort, direction, page, page_size):
    filters, order, params = _filter_and_order(search, sort, direction)
    with read_snapshot(conn):
        total = tenant_query(conn, tenant_id, "SELECT count(*)" + filters, **params).fetchone()[0]
        rows = tenant_query(conn, tenant_id, _COLUMNS + filters + order + " LIMIT :size OFFSET :offset",
                            **params, size=page_size, offset=(page - 1) * page_size)
        return {"items": [_fields(row) for row in rows], "total": total}


def export_rows(conn, tenant_id, search, sort, direction):
    filters, order, params = _filter_and_order(search, sort, direction)
    cursor = tenant_query(conn, tenant_id, _COLUMNS + filters + order, **params)
    try:
        for row in cursor:
            yield _fields(row)
    finally:
        cursor.close()


def generate(path, count=100000):
    """Fill East to exactly count certificates. The CLI targets a separate benchmark database."""
    if count < 1:
        raise ValueError("Count must be positive")
    initialize(path)
    with closing(connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("SELECT count(*) FROM certificates WHERE tenant_id=1").fetchone()[0]
            if current > count:
                raise ValueError("The database already contains more East certificates than requested")
            remaining = count - current
            if remaining:
                _generate_batch(conn, remaining)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _generate_batch(conn, remaining):
    first_learner = conn.execute("SELECT coalesce(max(id), 0) + 1 FROM learners").fetchone()[0]
    first_cert = conn.execute("SELECT coalesce(max(id), 0) + 1 FROM certificates").fetchone()[0]
    first_serial = conn.execute("""SELECT coalesce(max(CAST(substr(serial, 12) AS INTEGER)), 0) + 1
        FROM certificates WHERE tenant_id = 1 AND serial GLOB 'EAST-BENCH-[0-9]*'""").fetchone()[0]
    conn.executemany("INSERT INTO learners(id, tenant_id, name) VALUES (?, 1, ?)",
                     ((first_learner + i, f"Benchmark Learner {(first_serial + i) % 100:03}")
                      for i in range(remaining)))
    conn.executemany("INSERT INTO enrollments VALUES (1, 3, ?, 1)",
                     ((first_learner + i,) for i in range(remaining)))
    conn.executemany("""INSERT INTO certificates
        (id, tenant_id, course_id, learner_id, serial, issued_at, status)
        VALUES (?, 1, 3, ?, ?, ?, 'ACTIVE')""", (
            (first_cert + i, first_learner + i, f"EAST-BENCH-{first_serial + i:06}",
             f"2026-01-{1 + (first_serial + i) % 28:02}T13:30:00Z") for i in range(remaining)))
    conn.execute("""INSERT INTO audit_events(tenant_id, certificate_id, actor_email, action, created_at)
        SELECT tenant_id, id, 'alice@east.test', 'ISSUED', issued_at FROM certificates
        WHERE tenant_id = 1 AND id >= ?""", (first_cert,))
