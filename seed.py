"""Create a separate SQLite database for export acceptance checks."""
import argparse
from pathlib import Path

import db


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("benchmark.sqlite3"))
    parser.add_argument("--count", type=int, default=100000)
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    db.generate(args.database, args.count)
    print(f"{args.database}: {args.count:,} East certificates")
