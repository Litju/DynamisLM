"""Process externally stored, authorized UTF-8 inputs on CPU; never trains a model."""

import argparse
import json
from pathlib import Path

from dynamislm.training_data.admission import Purpose, Request, Source, SourceClass, _document
from dynamislm.training_data.processing import process_training_inputs, require_external


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="External JSON object with an inputs list")
    parser.add_argument("--exclusions", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        document = _document(require_external(args.request).read_bytes())
        if set(document) != {"inputs"} or not isinstance(document["inputs"], list):
            raise ValueError("expected inputs only; manifests confer no authority")
        inputs = []
        for item in document["inputs"]:
            if set(item) != {
                "source",
                "purpose",
                "transformations",
                "partition",
                "content_path",
                "grant_path",
            }:
                raise ValueError("invalid input fields")
            source = dict(item["source"])
            source["source_class"] = SourceClass(source["source_class"])
            inputs.append(
                (
                    Request(
                        Source(**source),
                        Purpose(item["purpose"]),
                        tuple(item["transformations"]),
                        item["partition"],
                    ),
                    require_external(Path(item["content_path"])).read_bytes(),
                    require_external(Path(item["grant_path"])).read_bytes(),
                )
            )
        result = process_training_inputs(
            tuple(inputs),
            exclusion_bundle=require_external(args.exclusions).read_bytes()
            if args.exclusions
            else None,
            output_root=args.output_root,
        )
    except (ValueError, PermissionError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"processing refused: {type(exc).__name__}\n")
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "CLEAN":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
