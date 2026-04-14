from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from statistics import pstdev
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
KEYWORDS = {
    "aigc": "AIGC keyword",
    "c2pa": "C2PA signature",
    "jumb": "JUMBF signature",
    "content credentials": "Content Credentials string",
    "midjourney": "Generator hint",
    "stable diffusion": "Generator hint",
    "openai": "Generator hint",
}

RAW_SIGNATURES = {
    b"aigc": "AIGC keyword",
    b"c2pa": "C2PA signature",
    b"jumb": "JUMBF signature",
    b"content credentials": "Content Credentials string",
    b"midjourney": "Generator hint",
    b"stable diffusion": "Generator hint",
    b"openai": "Generator hint",
    b"<x:xmpmeta": "XMP packet marker",
    b"xpacket begin=": "XMP packet marker",
    b"http://ns.adobe.com/xap/1.0/": "XMP namespace marker",
}


def _ensure_parent(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    target = _ensure_parent(path)
    target.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(target)


def _write_markdown(path: str | Path, text: str) -> str:
    target = _ensure_parent(path)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")
    return str(target)


def _format_from_path(path: str | Path, fallback: str = "PNG") -> str:
    suffix = Path(path).suffix.lower()
    mapping = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".webp": "WEBP",
    }
    return mapping.get(suffix, fallback)


def _parse_png_text_chunks(data: bytes) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not data.startswith(PNG_SIGNATURE):
        return findings

    cursor = len(PNG_SIGNATURE)
    while cursor + 8 <= len(data):
        length = struct.unpack(">I", data[cursor : cursor + 4])[0]
        chunk_type = data[cursor + 4 : cursor + 8].decode("latin-1")
        payload_start = cursor + 8
        payload_end = payload_start + length
        payload = data[payload_start:payload_end]
        cursor = payload_end + 4

        if chunk_type not in {"tEXt", "zTXt", "iTXt"}:
            if chunk_type == "IEND":
                break
            continue

        decoded = payload.decode("latin-1", errors="replace")
        keyword, _, value = decoded.partition("\x00")
        lowered = f"{keyword} {value}".lower()
        for token, reason in KEYWORDS.items():
            if token in lowered:
                findings.append(
                    {
                        "type": "png_text_chunk",
                        "chunk_type": chunk_type,
                        "keyword": keyword,
                        "reason": reason,
                        "snippet": decoded[:160],
                    }
                )
    return findings


def _scan_raw_markers(data: bytes) -> list[dict[str, Any]]:
    lowered = data.lower()
    findings: list[dict[str, Any]] = []
    for token, reason in RAW_SIGNATURES.items():
        index = lowered.find(token)
        if index < 0:
            continue
        snippet = data[max(0, index - 32) : index + 96].decode(
            "latin-1", errors="replace"
        )
        findings.append(
            {
                "type": "raw_signature",
                "token": token.decode("utf-8", errors="replace"),
                "reason": reason,
                "offset": index,
                "snippet": snippet,
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for finding in findings:
        key = (
            finding.get("type", ""),
            finding.get("token", finding.get("keyword", "")),
            int(finding.get("offset", -1)),
        )
        if key not in seen:
            deduped.append(finding)
            seen.add(key)
    return deduped


def _image_facts(image: Image.Image) -> dict[str, Any]:
    bands = image.getbands()
    return {
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "has_alpha": "A" in bands,
        "bands": list(bands),
    }


def _patch_stats(values: list[int]) -> tuple[int, float]:
    if not values:
        return 255, 0.0
    return min(values), float(pstdev(values))


def _detect_visible_overlay(image: Image.Image) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if "A" not in image.getbands():
        return findings

    alpha = image.getchannel("A")
    width, height = image.size
    corner_height = max(8, height // 6)
    corner_width = max(8, width // 6)
    corners = {
        "top_left": (0, 0, corner_width, corner_height),
        "top_right": (width - corner_width, 0, width, corner_height),
        "bottom_left": (0, height - corner_height, corner_width, height),
        "bottom_right": (width - corner_width, height - corner_height, width, height),
    }
    for name, box in corners.items():
        values = list(alpha.crop(box).getdata())
        patch_min, patch_std = _patch_stats(values)
        patch_mean = sum(values) / len(values) if values else 255.0
        if patch_min < 245 and 20.0 < patch_mean < 235.0 and patch_std > 4.0:
            findings.append(
                {
                    "type": "alpha_corner_overlay",
                    "corner": name,
                    "reason": "Alpha variation near a corner can indicate a visible overlay.",
                    "alpha_min": patch_min,
                    "alpha_mean": round(patch_mean, 3),
                    "alpha_std": round(patch_std, 3),
                }
            )
    if len(findings) >= 3 and all(item["alpha_min"] == 0 for item in findings):
        return []
    return findings


def _pattern_value(name: str, x: int, y: int) -> int:
    if name == "checkerboard-2x2":
        return 1 if (x + y) % 2 else -1
    if name == "vertical-stripes-2":
        return 1 if x % 2 else -1
    if name == "horizontal-stripes-2":
        return 1 if y % 2 else -1
    raise ValueError(f"Unsupported pattern: {name}")


def _detect_pixel_suspicion(image: Image.Image) -> list[dict[str, Any]]:
    bands = {"gray": image.convert("L"), "red": image.convert("RGB").getchannel("R")}
    width, height = next(iter(bands.values())).size
    if width < 32 or height < 32:
        return []

    findings: list[dict[str, Any]] = []
    total = width * height
    for band_name, band_image in bands.items():
        pixels = band_image.load()
        for name in ("checkerboard-2x2", "vertical-stripes-2", "horizontal-stripes-2"):
            accum = 0
            for y in range(height):
                for x in range(width):
                    lsb_centered = 1 if (pixels[x, y] & 1) else -1
                    accum += lsb_centered * _pattern_value(name, x, y)
            score = abs(accum / total)
            if score >= 0.18:
                findings.append(
                    {
                        "type": "periodic_lsb_signal",
                        "band": band_name,
                        "pattern": name,
                        "reason": "Regular LSB correlation can indicate a fragile hidden pixel mark.",
                        "score": round(score, 4),
                    }
                )

    deduped: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for finding in sorted(findings, key=lambda item: item["score"], reverse=True):
        key = (finding["type"], finding["pattern"])
        if key not in seen_pairs:
            deduped.append(finding)
            seen_pairs.add(key)
    return deduped


def _primary_inspect_message(
    embedded_markers: list[dict[str, Any]],
    visible_overlay: list[dict[str, Any]],
    pixel_suspicion: list[dict[str, Any]],
) -> str:
    if embedded_markers:
        return "Embedded marker(s) detected."
    if visible_overlay or pixel_suspicion:
        return "No embedded marker detected, but visible/pixel suspicion remains."
    return "No known embedded marker detected."


def inspect_image(path: str | Path) -> dict[str, Any]:
    input_path = Path(path)
    image = Image.open(input_path)
    raw = input_path.read_bytes()

    embedded_markers = _parse_png_text_chunks(raw) + _scan_raw_markers(raw)
    visible_overlay = _detect_visible_overlay(image)
    pixel_suspicion = _detect_pixel_suspicion(image)

    return {
        "command": "inspect",
        "input_path": str(input_path),
        "image": _image_facts(image),
        "embedded_markers": embedded_markers,
        "visible_overlay_suspicions": visible_overlay,
        "pixel_suspicions": pixel_suspicion,
        "summary": {
            "embedded_marker_status": "detected" if embedded_markers else "not_detected",
            "visible_overlay_status": "suspicious" if visible_overlay else "not_detected",
            "pixel_suspicion_status": "suspicious" if pixel_suspicion else "not_detected",
            "primary_message": _primary_inspect_message(
                embedded_markers, visible_overlay, pixel_suspicion
            ),
            "vendor_private_note": "cannot verify vendor-private watermark",
        },
    }


def _flatten_alpha(
    image: Image.Image, background: tuple[int, int, int] = (255, 255, 255)
) -> Image.Image:
    if "A" not in image.getbands():
        return image
    base = Image.new("RGB", image.size, background)
    base.paste(image, mask=image.getchannel("A"))
    return base


def _save_sanitized(
    image: Image.Image, output_path: str | Path, fmt: str, quality: int = 95
) -> None:
    target = _ensure_parent(output_path)
    save_kwargs: dict[str, Any] = {}
    if fmt == "JPEG":
        working = image.convert("RGB")
        save_kwargs.update({"quality": quality, "subsampling": 0})
    else:
        working = image
    working.save(target, format=fmt, **save_kwargs)


def strip_metadata_file(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(input_path)
    image = Image.open(source)
    fmt = _format_from_path(output_path, fallback=_format_from_path(source, "PNG"))
    if fmt == "JPEG":
        image = image.convert("RGB")
    _save_sanitized(image, output_path, fmt)
    return {
        "command": "strip-metadata",
        "input_path": str(source),
        "output_path": str(Path(output_path)),
        "output_format": fmt,
        "steps": [
            "decode image pixels",
            "drop text/EXIF/XMP/C2PA-like payloads by clean re-save",
        ],
    }


def _neutralize_lsb(image: Image.Image, bits: int) -> Image.Image:
    rgb = image.convert("RGB")
    mask = 0xFF << bits
    pixels = []
    source = rgb.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            red, green, blue = source[x, y]
            pixels.append((red & mask, green & mask, blue & mask))
    cleaned = Image.new("RGB", rgb.size)
    cleaned.putdata(pixels)
    return cleaned


def _light_resample(image: Image.Image, scale: float) -> Image.Image:
    width = max(8, int(round(image.width * scale)))
    height = max(8, int(round(image.height * scale)))
    if width == image.width and height == image.height:
        return image
    down = image.resize((width, height), Image.Resampling.BICUBIC)
    return down.resize(image.size, Image.Resampling.BICUBIC)


def _global_restyle(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    softened = rgb.filter(ImageFilter.GaussianBlur(radius=0.8))
    sharpened = softened.filter(
        ImageFilter.UnsharpMask(radius=1, percent=110, threshold=3)
    )
    return ImageEnhance.Color(sharpened).enhance(0.98)


def _parse_box(
    box: str | None, size: tuple[int, int]
) -> tuple[int, int, int, int] | None:
    if not box:
        return None
    x1, y1, x2, y2 = [int(part.strip()) for part in box.split(",")]
    x1 = max(0, min(size[0], x1))
    x2 = max(0, min(size[0], x2))
    y1 = max(0, min(size[1], y1))
    y2 = max(0, min(size[1], y2))
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"Invalid box: {box}")
    return (x1, y1, x2, y2)


def _load_mask(
    size: tuple[int, int], box: str | None, mask_path: str | None, expand: int
) -> Image.Image:
    if box:
        parsed = _parse_box(box, size)
        if parsed is None:  # pragma: no cover
            raise ValueError("A box value is required.")
        mask = Image.new("L", size, 0)
        overlay = Image.new("L", (parsed[2] - parsed[0], parsed[3] - parsed[1]), 255)
        mask.paste(overlay, (parsed[0], parsed[1]))
    elif mask_path:
        mask = Image.open(mask_path).convert("L").resize(
            size, Image.Resampling.NEAREST
        )
    else:
        raise ValueError("remove-overlay requires --box or --mask")

    if expand > 0:
        kernel = expand * 2 + 1
        if kernel % 2 == 0:
            kernel += 1
        mask = mask.filter(ImageFilter.MaxFilter(kernel))
    return mask


def _fallback_repair(image: Image.Image, mask: Image.Image) -> Image.Image:
    repaired = image.convert("RGB")
    for radius in (4, 8, 12):
        blurred = repaired.filter(ImageFilter.GaussianBlur(radius=radius))
        repaired = Image.composite(blurred, repaired, mask)
    return repaired


def remove_overlay_file(
    input_path: str | Path,
    output_path: str | Path,
    box: str | None = None,
    mask_path: str | None = None,
    expand: int = 0,
) -> dict[str, Any]:
    source = Path(input_path)
    image = Image.open(source)
    mask = _load_mask(image.size, box=box, mask_path=mask_path, expand=expand)
    repaired = _fallback_repair(image, mask)

    fmt = _format_from_path(output_path, fallback=_format_from_path(source, "PNG"))
    _save_sanitized(repaired, output_path, fmt)
    return {
        "command": "remove-overlay",
        "input_path": str(source),
        "output_path": str(Path(output_path)),
        "box": box,
        "mask_path": mask_path,
        "expand": expand,
        "method": "blur-composite-fallback",
        "modified_region_only": True,
    }


def normalize_image_file(
    input_path: str | Path,
    output_path: str | Path,
    strategy: str = "balanced",
    semantic_rewrite: str = "none",
    box: str | None = None,
    mask_path: str | None = None,
) -> dict[str, Any]:
    source = Path(input_path)
    image = Image.open(source)

    steps: list[str] = ["clean re-encode"]
    content_rewritten = False

    if strategy in {"balanced", "aggressive"} and "A" in image.getbands():
        image = _flatten_alpha(image)
        steps.append("alpha flattened")

    if strategy == "balanced":
        image = _neutralize_lsb(image, bits=1)
        image = _light_resample(image, scale=0.985)
        steps.extend(["neutralized 1 LSB bit", "light resample round-trip"])
    elif strategy == "aggressive":
        image = _neutralize_lsb(image, bits=2)
        image = _light_resample(image, scale=0.94)
        image = ImageEnhance.Sharpness(image).enhance(0.96)
        steps.extend(
            ["neutralized 2 LSB bits", "strong resample round-trip", "detail rewrite"]
        )
        if semantic_rewrite == "global-restyle":
            image = _global_restyle(image)
            content_rewritten = True
            steps.append("global restyle rewrite")
        elif semantic_rewrite == "region-repair" and (box or mask_path):
            temp_output = Path(output_path).with_suffix(".rewrite.tmp.png")
            _save_sanitized(image, temp_output, "PNG")
            rewrite_result = remove_overlay_file(
                temp_output, output_path, box=box, mask_path=mask_path, expand=0
            )
            temp_output.unlink(missing_ok=True)
            return {
                "command": "normalize-image",
                "input_path": str(source),
                "output_path": str(Path(output_path)),
                "strategy": strategy,
                "semantic_rewrite": semantic_rewrite,
                "steps": steps + ["region rewrite"],
                "content_rewritten": True,
                "rewrite_result": rewrite_result,
            }

    output_format = _format_from_path(output_path, fallback=_format_from_path(source))
    if strategy == "aggressive" and output_format == "PNG" and "A" not in image.getbands():
        output_format = "JPEG"
        output_path = str(Path(output_path).with_suffix(".jpg"))
        steps.append("format converted to JPEG")

    _save_sanitized(image, output_path, output_format)
    return {
        "command": "normalize-image",
        "input_path": str(source),
        "output_path": str(Path(output_path)),
        "strategy": strategy,
        "semantic_rewrite": semantic_rewrite,
        "steps": steps,
        "content_rewritten": content_rewritten,
    }


def _result_label(
    before: dict[str, Any], after: dict[str, Any], content_rewritten: bool
) -> str:
    before_embedded = bool(before["embedded_markers"])
    after_embedded = bool(after["embedded_markers"])
    after_suspicion = bool(
        after["pixel_suspicions"] or after["visible_overlay_suspicions"] or after_embedded
    )

    if before_embedded and not after_embedded:
        return "confirmed removed"
    if not after_suspicion:
        return "not detected after processing"
    return "residual suspicion remains"


def recheck_images(
    original_path: str | Path,
    processed_path: str | Path,
    content_rewritten: bool = False,
) -> dict[str, Any]:
    before = inspect_image(original_path)
    after = inspect_image(processed_path)

    removed_embedded = []
    for finding in before["embedded_markers"]:
        snippet = finding.get("snippet") or finding.get("token") or finding.get("keyword")
        if not any(
            (other.get("snippet") or other.get("token") or other.get("keyword")) == snippet
            for other in after["embedded_markers"]
        ):
            removed_embedded.append(finding)

    return {
        "command": "recheck",
        "original_path": str(Path(original_path)),
        "processed_path": str(Path(processed_path)),
        "before": before,
        "after": after,
        "comparison": {
            "result_label": _result_label(before, after, content_rewritten),
            "removed_embedded_markers": removed_embedded,
            "remaining_embedded_markers": after["embedded_markers"],
            "before_pixel_suspicion": before["summary"]["pixel_suspicion_status"],
            "after_pixel_suspicion": after["summary"]["pixel_suspicion_status"],
            "before_visible_overlay": before["summary"]["visible_overlay_status"],
            "after_visible_overlay": after["summary"]["visible_overlay_status"],
            "content_rewritten": content_rewritten,
            "vendor_private_note": "cannot verify vendor-private watermark",
        },
    }


def _pipeline_markdown(report: dict[str, Any]) -> str:
    comparison = report["recheck"]["comparison"]
    lines = [
        "# AIGC Mark Toolkit Report",
        "",
        f"- Input: `{report['input_path']}`",
        f"- Strategy: `{report['strategy']}`",
        f"- Final image: `{report['result_image_path']}`",
        f"- Result label: `{comparison['result_label']}`",
        f"- Content rewritten: `{str(report['content_rewritten']).lower()}`",
        "- Vendor-private caveat: `cannot verify vendor-private watermark`",
        "",
        "## Steps",
    ]
    for step in report["steps"]:
        lines.append(f"- `{step['name']}` -> `{step['output']}`")
    lines.extend(
        [
            "",
            "## Detected Marks Before",
            f"- Embedded markers: `{len(report['before']['embedded_markers'])}`",
            f"- Pixel suspicions: `{len(report['before']['pixel_suspicions'])}`",
            f"- Overlay suspicions: `{len(report['before']['visible_overlay_suspicions'])}`",
            "",
            "## Recheck",
            f"- Removed embedded markers: `{len(comparison['removed_embedded_markers'])}`",
            f"- Remaining embedded markers: `{len(comparison['remaining_embedded_markers'])}`",
            f"- After pixel suspicion: `{comparison['after_pixel_suspicion']}`",
            f"- After overlay suspicion: `{comparison['after_visible_overlay']}`",
        ]
    )
    return "\n".join(lines)


def clean_aigc_marks(
    input_path: str | Path,
    output_dir: str | Path,
    strategy: str = "balanced",
    semantic_rewrite: str = "none",
    box: str | None = None,
    mask_path: str | None = None,
) -> dict[str, Any]:
    source = Path(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem

    before = inspect_image(source)
    before_report_path = _write_json(out_dir / f"{stem}.inspect.before.json", before)

    stripped_path = out_dir / f"{stem}.stripped{source.suffix.lower() or '.png'}"
    strip_result = strip_metadata_file(source, stripped_path)

    normalized_target = out_dir / f"{stem}.normalized{source.suffix.lower() or '.png'}"
    normalize_result = normalize_image_file(
        stripped_path,
        normalized_target,
        strategy=strategy,
        semantic_rewrite=semantic_rewrite,
        box=box,
        mask_path=mask_path,
    )
    normalized_path = Path(normalize_result["output_path"])

    final_path = normalized_path
    overlay_result: dict[str, Any] | None = None
    content_rewritten = bool(normalize_result.get("content_rewritten", False))

    if (box or mask_path) and semantic_rewrite != "region-repair":
        overlay_target = out_dir / f"{stem}.cleaned{normalized_path.suffix}"
        overlay_result = remove_overlay_file(
            normalized_path,
            overlay_target,
            box=box,
            mask_path=mask_path,
            expand=0,
        )
        final_path = Path(overlay_result["output_path"])
        content_rewritten = True

    after = inspect_image(final_path)
    after_report_path = _write_json(out_dir / f"{stem}.inspect.after.json", after)
    recheck = recheck_images(source, final_path, content_rewritten=content_rewritten)
    recheck_path = _write_json(out_dir / f"{stem}.recheck.json", recheck)

    steps = [
        {"name": "inspect-before", "output": before_report_path},
        {"name": "strip-metadata", "output": strip_result["output_path"]},
        {"name": "normalize-image", "output": normalize_result["output_path"]},
    ]
    if overlay_result is not None:
        steps.append({"name": "remove-overlay", "output": overlay_result["output_path"]})
    steps.extend(
        [
            {"name": "inspect-after", "output": after_report_path},
            {"name": "recheck", "output": recheck_path},
        ]
    )

    report = {
        "command": "clean-aigc-marks",
        "input_path": str(source),
        "output_dir": str(out_dir),
        "strategy": strategy,
        "semantic_rewrite": semantic_rewrite,
        "steps": steps,
        "before": before,
        "after": after,
        "recheck": recheck,
        "result_image_path": str(final_path),
        "content_rewritten": content_rewritten,
    }
    report_json = _write_json(out_dir / f"{stem}.report.json", report)
    report_markdown = _write_markdown(
        out_dir / f"{stem}.report.md", _pipeline_markdown(report)
    )
    report["report_json"] = report_json
    report["report_markdown"] = report_markdown
    return report
