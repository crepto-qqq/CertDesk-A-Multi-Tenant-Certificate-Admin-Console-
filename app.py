"""HTTP endpoints for the CertDesk single-service application."""

import csv
import io
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, send_from_directory

import db
import writes


SORT_FIELDS = {"learner", "course", "serial", "date", "status"}


def listing_options():
    sort = request.args.get("sort", "date")
    direction = request.args.get("direction", "desc")
    if sort not in SORT_FIELDS or direction not in ("asc", "desc"):
        raise writes.APIError(400, "Unsupported sort field or direction.")
    return request.args.get("q", "").strip(), sort, direction


def positive_int(name, default, maximum):
    try:
        value = int(request.args.get(name, default))
    except ValueError:
        value = 0
    if not 1 <= value <= maximum:
        raise writes.APIError(400, f"{name} must be between 1 and {maximum}.")
    return value


def create_app(path):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    database = Path(path).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    db.initialize(database)

    @app.before_request
    def identify_actor():
        if request.path.startswith("/api/"):
            g.connection = db.connect(database)
            email = request.headers.get("X-Actor", "").strip()
            g.actor = db.actor(g.connection, email)
            if g.actor is None:
                raise writes.APIError(401, "Select a valid demo administrator.")

    @app.after_request
    def prevent_api_caching(response):
        if request.path.startswith("/api/"):
            response.cache_control.no_store = True
        return response

    @app.teardown_request
    def close_connection(_error):
        connection = g.pop("connection", None)
        if connection is not None:
            connection.close()

    @app.errorhandler(writes.APIError)
    def handle_api_error(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(sqlite3.Error)
    def handle_database_error(error):
        app.logger.error("Database operation failed", exc_info=True)
        if getattr(error, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return jsonify(error="The database is busy. Retry this request."), 503
        return jsonify(error="The database operation could not be completed."), 500

    @app.get("/")
    def home():
        return app.send_static_file("index.html")

    @app.get("/vendor/vue.global.prod.js")
    def vue_asset():
        return send_from_directory(Path(app.static_folder) / "vendor", "vue.global.prod.js")

    @app.get("/api/courses")
    def list_courses():
        return jsonify(items=db.courses(g.connection, g.actor["tenant_id"]))

    @app.get("/api/certificates")
    def certificates():
        options = listing_options()
        page = positive_int("page", 1, 2_147_483_647)
        page_size = positive_int("page_size", 20, 200)
        return jsonify(db.list_certificates(g.connection, g.actor["tenant_id"],
                                            *options, page, page_size))

    @app.get("/api/certificates/<int(max=9223372036854775807):cert_id>")
    def certificate(cert_id):
        result = db.certificate(g.connection, g.actor["tenant_id"], cert_id)
        if result is None:
            raise writes.APIError(404, "Certificate not found.")
        return jsonify(result)

    @app.post("/api/bulk-issue")
    def bulk_issue():
        payload = request.get_json(silent=True)
        return jsonify(writes.issue(g.connection, g.actor, payload,
                                    request.headers.get("Idempotency-Key")))

    @app.post("/api/certificates/<int(max=9223372036854775807):cert_id>/revoke")
    def revoke(cert_id):
        return jsonify(writes.revoke(g.connection, g.actor, cert_id))

    @app.get("/api/certificates/export.csv")
    def export():
        options = listing_options()
        tenant_id = g.actor["tenant_id"]

        def chunks():
            with closing(db.connect(database)) as connection:
                buffer = io.StringIO(newline="")
                writer = csv.writer(buffer)
                writer.writerow(("learner_name", "course_title", "serial_number", "issue_date"))
                for row in db.export_rows(connection, tenant_id, *options):
                    writer.writerow((row["learner"], row["course"], row["serial"], row["local_date"]))
                    if buffer.tell() >= 32768:
                        yield buffer.getvalue()
                        buffer.seek(0)
                        buffer.truncate()
                if buffer.tell():
                    yield buffer.getvalue()

        return Response(chunks(), mimetype="text/csv", headers={
            "Content-Disposition": 'attachment; filename="certificates.csv"'
        })

    return app
