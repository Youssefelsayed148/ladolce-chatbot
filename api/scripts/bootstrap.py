#!/usr/bin/env python3
"""First-run / every-start catalog bootstrap, called by entrypoint.sh.

  * seed_catalog.py  - ONLY when the catalog is empty (it deletes products, which
                       would break carts/orders that reference them on a live DB)
  * sync_store_catalog.py --apply - every start; updates in place from the store
  * ingest_kb.py     - every start; skips unchanged chunks (embeddings, cents)

The sync and ingest are best-effort: if the store or OpenAI is unreachable the API
still starts with whatever the DB already holds.
"""

import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from seed_catalog import _sync_engine  # noqa: E402


def run(script: str, *args: str) -> bool:
    print(f"[bootstrap] {script} {' '.join(args)}", flush=True)
    return subprocess.run([sys.executable, str(HERE / script), *args]).returncode == 0


def main() -> None:
    with _sync_engine().connect() as conn:
        products = conn.execute(text("select count(*) from products")).scalar()
    if products == 0:
        if not run("seed_catalog.py"):
            sys.exit("[bootstrap] seed failed")
    else:
        print(f"[bootstrap] catalog has {products} products; skipping seed", flush=True)
    if not run("sync_store_catalog.py", "--apply"):
        print("[bootstrap] WARNING: store sync failed; using existing catalog", flush=True)
    if not run("ingest_kb.py"):
        print("[bootstrap] WARNING: knowledge-base ingest failed", flush=True)


if __name__ == "__main__":
    main()
