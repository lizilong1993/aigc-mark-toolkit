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

    batch_parser = subparsers.add_parser("batch-clean")
    batch_parser.add_argument(
        "target",
        help="Directory path or single image file path",
    )
    batch_parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan subdirectories recursively",
    )
    batch_parser.add_argument(
        "--strategy",
        choices=("preserve", "balanced", "aggressive"),
        default="aggressive",
    )
    batch_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process images even if _remove.jpg already exists",
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


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file()


def _already_cleaned(path: Path) -> bool:
    """Check whether a _remove.jpg sibling already exists for this image."""
    return path.with_stem(path.stem + "_remove").with_suffix(".jpg").exists()


def _find_images(target: Path, recursive: bool) -> list[Path]:
    """Collect all image files under target (file or directory)."""
    if target.is_file():
        return [target] if _is_image(target) else []

    if recursive:
        images = [p for p in target.rglob("*") if _is_image(p)]
    else:
        images = [p for p in target.glob("*") if _is_image(p)]
    return sorted(images)


def _batch_clean(target: str, strategy: str, recursive: bool, force: bool) -> dict:
    """Batch clean: scan dir, skip already-cleaned images, quick-clean the rest."""
    root = Path(target)

    images = _find_images(root, recursive)
    if not images:
        return {
            "command": "batch-clean",
            "target": target,
            "error": "No supported image files found",
            "result": "error",
        }

    skipped: list[str] = []
    processed: list[str] = []
    failed: list[str] = []

    for img in images:
        if not force and _already_cleaned(img):
            skipped.append(str(img))
            continue
        try:
            _quick_clean(str(img), None, strategy)
            processed.append(str(img))
        except Exception as exc:
            failed.append(f"{img}: {exc}")

    return {
        "command": "batch-clean",
        "target": str(root),
        "strategy": strategy,
        "recursive": recursive,
        "total": len(images),
        "processed": len(processed),
        "skipped": len(skipped),
        "failed": len(failed),
        "processed_files": processed,
        "skipped_files": skipped,
        "failed_files": failed,
        "result": "done" if not failed else "partial",
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

    if args.command == "batch-clean":
        result = _batch_clean(args.target, args.strategy, args.recursive, args.force)
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
