"""Emit the RES-71 verifier-ready deterministic reference interface."""

from __future__ import annotations

import argparse
import sys

from dynamislm.qualification import reference_case_digest, reference_case_manifest

VERIFIER_REFERENCE_INTERFACE = "res71-reference-interface@1.0.0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--digest", action="store_true", help="emit the canonical case digest")
    output.add_argument("--manifest", action="store_true", help="emit canonical case JSON")
    args = parser.parse_args(argv)
    if args.digest:
        sys.stdout.write(reference_case_digest() + "\n")
    else:
        sys.stdout.write(reference_case_manifest() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
