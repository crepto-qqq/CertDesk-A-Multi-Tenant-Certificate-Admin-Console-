"""Tenant-scoped certificate commands. A successful response follows commit."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from uuid import uuid4

import db


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


@contextmanager
def _write_transaction(conn):
    # Acquire the write lock before looking up a replay or checking eligibility.
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _audit(query, cert_id, actor_email, action, timestamp):
    query(
        """INSERT INTO audit_events
           (tenant_id, certificate_id, actor_email, action, created_at)
           VALUES (:tenant_id, :cert_id, :actor, :action, :timestamp)""",
        cert_id=cert_id, actor=actor_email, action=action, timestamp=timestamp,
    )


def _issue_one(conn, query, actor_email, course_id, enrollment, timestamp):
    learner_id = enrollment["learner_id"]
    result = {"learner_id": learner_id, "learner": enrollment["learner"]}
    if enrollment["status"] is not None:
        reason = "revoked" if enrollment["status"] == "REVOKED" else "already_certified"
        return {**result, "outcome": "skipped", "reason": reason}
    if not enrollment["completed"]:
        return {**result, "outcome": "skipped", "reason": "incomplete"}
    if not (enrollment["learner"] or "").strip():
        return {**result, "outcome": "failed", "reason": "missing_learner_name"}

    serial = "CERT-" + uuid4().hex.upper()
    conn.execute("SAVEPOINT issue_learner")
    try:
        cert_id = query(
            """INSERT INTO certificates
               (tenant_id, course_id, learner_id, serial, issued_at, status)
               VALUES (:tenant_id, :course, :learner, :serial, :timestamp, 'ACTIVE')""",
            course=course_id, learner=learner_id, serial=serial, timestamp=timestamp,
        ).lastrowid
    except sqlite3.IntegrityError as exc:
        # A row rejected by a certificate rule is an individual failure.
        # Unexpected integrity errors and audit failures abort the entire batch.
        if not conn.in_transaction or exc.sqlite_errorcode not in (
            sqlite3.SQLITE_CONSTRAINT_CHECK, sqlite3.SQLITE_CONSTRAINT_TRIGGER,
        ):
            raise
        conn.execute("ROLLBACK TO issue_learner")
        conn.execute("RELEASE issue_learner")
        return {**result, "outcome": "failed", "reason": "certificate_rule_rejected"}

    _audit(query, cert_id, actor_email, "ISSUED", timestamp)
    conn.execute("RELEASE issue_learner")
    return {**result, "outcome": "issued", "certificate_id": cert_id, "serial": serial}


def issue(conn, actor, payload, key):
    if not isinstance(key, str) or not key.strip():
        raise APIError(400, "Idempotency-Key is required.")
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise APIError(400, "The request must contain valid JSON.") from exc
    request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    query = partial(db.tenant_query, conn, actor["tenant_id"])
    email = actor["email"]
    with _write_transaction(conn):
        previous = query(
            """SELECT request_hash, result_json FROM operations
               WHERE tenant_id=:tenant_id AND actor_email=:email AND idempotency_key=:key""",
            email=email, key=key,
        ).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise APIError(409, "This idempotency key was used with a different request.")
            return json.loads(previous["result_json"])

        course_id = payload.get("course_id") if isinstance(payload, dict) else None
        if type(course_id) is not int or course_id < 1 or course_id > 2**63 - 1:
            raise APIError(400, "course_id must be a positive integer.")
        course = query(
            "SELECT id FROM courses WHERE tenant_id=:tenant_id AND id=:course",
            course=course_id,
        ).fetchone()
        if course is None:
            raise APIError(404, "Course not found.")
        operation_id = query(
            """INSERT INTO operations (tenant_id, actor_email, idempotency_key, request_hash)
               VALUES (:tenant_id, :email, :key, :request_hash)""",
            email=email, key=key, request_hash=request_hash,
        ).lastrowid
        enrollments = query(
            """SELECT e.learner_id, l.name AS learner, e.completed, c.status
               FROM enrollments e
               JOIN learners l ON l.tenant_id=e.tenant_id AND l.id=e.learner_id
               LEFT JOIN certificates c ON c.tenant_id=e.tenant_id
                 AND c.course_id=e.course_id AND c.learner_id=e.learner_id
               WHERE e.tenant_id=:tenant_id AND e.course_id=:course
               ORDER BY e.learner_id""",
            course=course_id,
        ).fetchall()
        timestamp = _now()
        counts = {"issued": 0, "skipped": 0, "failed": 0}
        outcomes = []
        for enrollment in enrollments:
            result = _issue_one(conn, query, email, course_id, enrollment, timestamp)
            outcomes.append(result)
            counts[result["outcome"]] += 1
        response = {"operation_id": operation_id, "course_id": course_id,
                    "status": "completed", "counts": counts, "outcomes": outcomes}
        query(
            "UPDATE operations SET result_json=:result WHERE tenant_id=:tenant_id AND id=:op",
            result=json.dumps(response, separators=(",", ":")), op=operation_id,
        )
        return response


def revoke(conn, actor, cert_id):
    query = partial(db.tenant_query, conn, actor["tenant_id"])
    with _write_transaction(conn):
        cert = query(
            "SELECT status FROM certificates WHERE tenant_id=:tenant_id AND id=:cert",
            cert=cert_id,
        ).fetchone()
        if cert is None:
            raise APIError(404, "Certificate not found.")
        if cert["status"] == "ACTIVE":
            query(
                """UPDATE certificates SET status='REVOKED'
                   WHERE tenant_id=:tenant_id AND id=:cert AND status='ACTIVE'""",
                cert=cert_id,
            )
            _audit(query, cert_id, actor["email"], "REVOKED", _now())
        return {"id": cert_id, "status": "REVOKED"}
