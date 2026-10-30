"""Metadata-only admission CLI; source and grant bytes must live outside Git."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from dynamislm.training_data.admission import Purpose, Request, Source, SourceClass, admit_sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "request", type=Path, help="JSON list of source, purpose, paths, transformations"
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument(
        "--evaluated-at", required=True, help="Explicit timezone-aware ISO timestamp"
    )
    args = parser.parse_args()
    items = json.loads(args.request.read_bytes())
    requests = []
    root = args.repository_root.resolve()
    for item in items:
        paths = [Path(item[k]).resolve() for k in ("content_path", "grant_path")]
        if any(p.is_relative_to(root) for p in paths):
            parser.error("content and grants must be outside the repository")
        source = dict(item["source"])
        source["source_class"] = SourceClass(source["source_class"])
        requests.append(
            (
                Request(
                    Source(**source),
                    Purpose(item["purpose"]),
                    tuple(item["transformations"]),
                    item.get("partition", "TRAIN"),
                ),
                paths[0].read_bytes(),
                paths[1].read_bytes(),
            )
        )
    result = admit_sources(
        tuple(requests),
        repository_root=root,
        evaluated_at=datetime.fromisoformat(args.evaluated_at),
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
