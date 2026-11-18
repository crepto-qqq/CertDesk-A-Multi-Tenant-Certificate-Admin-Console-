"""Serve an isolated browser verification page at http://127.0.0.1:5052/checks."""

import argparse
import csv
import hashlib
import io
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4

from flask import Flask, abort, jsonify, send_file
from werkzeug.serving import run_simple

import db
from app import create_app
from verify import ExportOverlap, expected_export


class BrowserRun:
    def __init__(self, app):
        self.app = app
        self.overlap = ExportOverlap(app)

    def __call__(self, environ, start_response):
        path = environ["PATH_INFO"]
        if path == "/api/certificates/export.csv" and environ.get("HTTP_X_CHECK_STREAM") == "1":
            return self.overlap(environ, start_response)
        if path != "/api/certificates" or environ.get("HTTP_X_CHECK_OVERLAP") != "1":
            return self.app(environ, start_response)
        gated = self.overlap.started.wait(timeout=2) and not self.overlap.resume.is_set()

        def with_overlap_header(status, headers, exc_info=None):
            return start_response(status, [*headers, ("X-Export-In-Progress", str(int(gated)))], exc_info)

        response = self.app(environ, with_overlap_header)
        return self.release_after_list(response)

    def release_after_list(self, response):
        try:
            yield from response
        finally:
            if hasattr(response, "close"):
                response.close()
            self.overlap.resume.set()


def fixtures(starting_db):
    db.generate(starting_db, count=100000)
    rows = expected_export(starting_db)
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["learner_name", "course_title", "serial_number", "issue_date"])
    writer.writerows(rows)
    return len(rows), hashlib.sha256(out.getvalue().encode("utf-8")).hexdigest()


def build_harness(folder):
    template = folder / "starting.sqlite"
    count, digest = fixtures(template)
    control = Flask("browser-verification", static_folder=None)
    active = {}
    lock = Lock()

    @control.get("/checks")
    def checks():
        return send_file(Path(__file__).with_name("tests") / "browser_checks.html")

    @control.post("/checks/start")
    def start():
        token = uuid4().hex
        path = folder / f"{token}.sqlite"
        with closing(sqlite3.connect(template)) as source, closing(sqlite3.connect(path)) as dest:
            source.backup(dest)
        run = BrowserRun(create_app(path))
        with lock:
            active[token] = run
        return jsonify(base=f"/checks/run/{token}", count=count, digest=digest)

    @control.post("/checks/finish/<token>")
    def finish(token):
        with lock:
            run = active.pop(token, None)
        if run is None:
            abort(404)
        run.overlap.resume.set()
        return "", 204

    def dispatch(environ, start_response):
        path = environ["PATH_INFO"]
        if path.startswith("/checks/run/"):
            _, _, _, token, *parts = path.split("/")
            with lock:
                run = active.get(token)
            if run and parts and parts[0] == "api":
                env = environ.copy()
                env["SCRIPT_NAME"] += "/checks/run/" + token
                env["PATH_INFO"] = "/" + "/".join(parts)
                return run(env, start_response)
        return control(environ, start_response)

    return dispatch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5052)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="certdesk-browser-") as tmp:
        service = build_harness(Path(tmp))
        print(f"Open http://127.0.0.1:{args.port}/checks and select Run checks.", flush=True)
        run_simple("127.0.0.1", args.port, service, threaded=True, use_reloader=False)
