"""Stage raw files from one verified scan for the read-only ranking API."""

import argparse
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-date", type=date.fromisoformat, required=True)
    parser.add_argument("--worker-input", type=Path, required=True)
    parser.add_argument("--dl-output", type=Path, required=True)
    parser.add_argument("--ml-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New private snapshot directory")
    args = parser.parse_args()
    sources = {
        "alerts.csv": args.worker_input / "scan/alerts.csv",
        "evidence_transactions.csv": args.worker_input / "scan/evidence_transactions.csv",
        "evidence_source_map.csv": args.worker_input / "history/evidence_source_map.csv",
        "worker-input.json": args.worker_input / "checksums.json",
        "ml.csv": args.ml_output / "scores_1545_final.csv",
        "ml-summary.json": args.ml_output / "summary.json",
        "dl.csv": args.dl_output / "transaction-scores.csv",
        "dl-summary.json": args.dl_output / "summary.json",
    }
    for source in sources.values():
        if not source.is_file():
            parser.error(f"missing input: {source}")
    args.output.mkdir(mode=0o700, exist_ok=False)
    hashes = {}
    for name, path in sources.items():
        snapshot_file = args.output / name
        shutil.copyfile(path, snapshot_file)
        hashes[name] = hashlib.sha256(snapshot_file.read_bytes()).hexdigest()
    manifest = args.output / "manifest.json"
    payload = json.dumps({"scan_date": args.scan_date.isoformat(), "files": hashes}, indent=2) + "\n"
    manifest.write_bytes(payload.encode())
    print(f"AI_DL_SNAPSHOT_MANIFEST={manifest.resolve()}")
    print(f"AI_DL_SNAPSHOT_SHA256={hashlib.sha256(manifest.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
