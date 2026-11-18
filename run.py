"""Install declared dependencies, initialize demo data, and serve CertDesk."""

import argparse
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent


def dependencies_ready():
    for requirement in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not requirement.strip():
            continue
        name, version = requirement.split("==", 1)
        try:
            if importlib.metadata.version(name) != version:
                return False
        except importlib.metadata.PackageNotFoundError:
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Start the complete CertDesk application.")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "certdesk.sqlite3")
    args = parser.parse_args()

    if not dependencies_ready():
        environment = ROOT / ".venv"
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            print("Creating a local Python environment...", flush=True)
            venv.EnvBuilder(with_pip=True).create(environment)
        if Path(sys.executable).resolve() != python.resolve():
            return subprocess.call([str(python), str(ROOT / "run.py"), *sys.argv[1:]], cwd=ROOT)
        print("Installing declared dependencies...", flush=True)
        subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])

    from app import create_app

    args.db.parent.mkdir(parents=True, exist_ok=True)
    app = create_app(str(args.db.resolve()))
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
