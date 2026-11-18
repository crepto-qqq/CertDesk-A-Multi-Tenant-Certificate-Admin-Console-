CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    email TEXT PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    UNIQUE (tenant_id, email)
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    title TEXT NOT NULL,
    UNIQUE (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS learners (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    UNIQUE (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS enrollments (
    tenant_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    learner_id INTEGER NOT NULL,
    completed INTEGER NOT NULL CHECK (completed IN (0, 1)),
    PRIMARY KEY (tenant_id, course_id, learner_id),
    FOREIGN KEY (tenant_id, course_id) REFERENCES courses(tenant_id, id),
    FOREIGN KEY (tenant_id, learner_id) REFERENCES learners(tenant_id, id)
);
CREATE TABLE IF NOT EXISTS certificates (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    learner_id INTEGER NOT NULL,
    serial TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
    UNIQUE (tenant_id, course_id, learner_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, course_id, learner_id)
        REFERENCES enrollments(tenant_id, course_id, learner_id)
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    certificate_id INTEGER NOT NULL,
    actor_email TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('ISSUED', 'REVOKED')),
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, certificate_id, action),
    FOREIGN KEY (tenant_id, certificate_id) REFERENCES certificates(tenant_id, id),
    FOREIGN KEY (tenant_id, actor_email) REFERENCES admins(tenant_id, email)
);
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    actor_email TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_json TEXT,
    UNIQUE (tenant_id, actor_email, idempotency_key),
    FOREIGN KEY (tenant_id, actor_email) REFERENCES admins(tenant_id, email)
);
