"""Print an exact-HEAD, metadata-only RES-416 training-use audit (no data rows)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dynamislm.training_data import build_training_use_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    result = build_training_use_report(repository_root=args.repository_root)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
