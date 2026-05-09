from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from .toolkit import (
    clean_aigc_marks,
    inspect_image,
    normalize_image_file,
    remove_overlay_file,
    recheck_images,
    strip_metadata_file,
)


def _emit(result: dict, output: str | None) -> int:
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(payload + "\n", encoding="utf-8")
    try:
        sys.stdout.write(payload + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((payload + "\n").encode("utf-8", errors="replace"))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aigc-mark-toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("input")
    inspect_parser.add_argument("--output")

    strip_parser = subparsers.add_parser("strip-metadata")
    strip_parser.add_argument("input")
    strip_parser.add_argument("--output", required=True)
    strip_parser.add_argument("--report")

    normalize_parser = subparsers.add_parser("normalize-image")
    normalize_parser.add_argument("input")
    normalize_parser.add_argument("--output", required=True)
    normalize_parser.add_argument(
        "--strategy",
        choices=("preserve", "balanced", "aggressive"),
        default="balanced",
    )
    normalize_parser.add_argument(
        "--semantic-rewrite",
        choices=("none", "region-repair", "global-restyle"),
        default="none",
    )
    normalize_parser.add_argument("--box")
    normalize_parser.add_argument("--mask")
    normalize_parser.add_argument("--report")

    overlay_parser = subparsers.add_parser("remove-overlay")
    overlay_parser.add_argument("input")
    overlay_parser.add_argument("--output", required=True)
    overlay_parser.add_argument("--box")
    overlay_parser.add_argument("--mask")
    overlay_parser.add_argument("--expand", type=int, default=0)
    overlay_parser.add_argument("--report")

    recheck_parser = subparsers.add_parser("recheck")
    recheck_parser.add_argument("original")
    recheck_parser.add_argument("processed")
    recheck_parser.add_argument("--output")

    clean_parser = subparsers.add_parser("clean-aigc-marks")
    clean_parser.add_argument("input")
    clean_parser.add_argument("--output-dir", required=True)
    clean_parser.add_argument(
        "--strategy",
        choices=("preserve", "balanced", "aggressive"),
        default="balanced",
    )
    clean_parser.add_argument(
        "--semantic-rewrite",
        choices=("none", "region-repair", "global-restyle"),
        default="none",
    )
    clean_parser.add_argument("--box")
    clean_parser.add_argument("--mask")
    clean_parser.add_argument("--report")

    quick_parser = subparsers.add_parser("quick-clean")
    quick_parser.add_argument("input")
    quick_parser.add_argument(
        "--output",
        help="Output path (default: {input_stem}_remove.jpg)",
    )
    quick_parser.add_argument(
        "--strategy",
        choices=("preserve", "balanced", "aggressive"),
        default="aggressive",
    )

    return parser


def _quick_clean(input_path: str, output_path: str | None, strategy: str) -> dict:
    """One-shot clean: strip → normalize (aggressive) → single output, tempdir cleaned up."""
    source = Path(input_path)
    if output_path:
        final = Path(output_path)
    else:
        final = source.with_stem(source.stem + "_remove").with_suffix(".jpg")

    with tempfile.TemporaryDirectory(prefix="aigc-clean-") as tmp:
        tmp_dir = Path(tmp)
        stripped = tmp_dir / f"stripped{source.suffix}"
        strip_metadata_file(source, stripped)
        norm_result = normalize_image_file(
            stripped,
            tmp_dir / "normalized.jpg",
            strategy=strategy,
        )
        result_path = Path(norm_result["output_path"])
        shutil.copy2(result_path, final)

    return {
        "command": "quick-clean",
        "input": str(source),
        "output": str(final),
        "strategy": strategy,
        "result": "done",
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        return _emit(inspect_image(args.input), args.output)

    if args.command == "strip-metadata":
        result = strip_metadata_file(args.input, args.output)
        return _emit(result, args.report)

    if args.command == "normalize-image":
        result = normalize_image_file(
            args.input,
            args.output,
            strategy=args.strategy,
            semantic_rewrite=args.semantic_rewrite,
            box=args.box,
            mask_path=args.mask,
        )
        return _emit(result, args.report)

    if args.command == "remove-overlay":
        result = remove_overlay_file(
            args.input,
            args.output,
            box=args.box,
            mask_path=args.mask,
            expand=args.expand,
        )
        return _emit(result, args.report)

    if args.command == "recheck":
        return _emit(recheck_images(args.original, args.processed), args.output)

    if args.command == "clean-aigc-marks":
        result = clean_aigc_marks(
            args.input,
            args.output_dir,
            strategy=args.strategy,
            semantic_rewrite=args.semantic_rewrite,
            box=args.box,
            mask_path=args.mask,
        )
        return _emit(result, args.report)

    if args.command == "quick-clean":
        result = _quick_clean(args.input, args.output, args.strategy)
        return _emit(result, None)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def main_clean(argv: list[str] | None = None) -> int:
    forwarded = ["clean-aigc-marks"]
    if argv:
        forwarded.extend(argv)
    return main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
