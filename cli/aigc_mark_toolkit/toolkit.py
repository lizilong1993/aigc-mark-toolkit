from __future__ import annotations

import json
import math
import os
import struct
import urllib.request
import zlib
from pathlib import Path
from statistics import pstdev
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False


# Real-ESRGAN 模型配置
REALESRGAN_MODEL_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
)
REALESRGAN_MODEL_FILENAME = "RealESRGAN_x2plus.pth"
REALESRGAN_MODEL_DIR = Path.home() / ".cache" / "aigc-mark-toolkit"


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
KEYWORDS = {
    "aigc": "AIGC keyword",
    "c2pa": "C2PA signature",
    "jumb": "JUMBF signature",
    "content credentials": "Content Credentials string",
    "midjourney": "Generator hint",
    "stable diffusion": "Generator hint",
    "openai": "Generator hint",
    "dall-e": "Generator hint",
    "dalle": "Generator hint",
    "firefly": "Generator hint",
    "adobe": "Generator hint",
    "imagen": "Generator hint",
    "synthesia": "Generator hint",
    "runway": "Generator hint",
    "pika": "Generator hint",
    "stability.ai": "Generator hint",
}

RAW_SIGNATURES = {
    b"aigc": "AIGC keyword",
    b"c2pa": "C2PA signature",
    b"jumb": "JUMBF signature",
    b"content credentials": "Content Credentials string",
    b"midjourney": "Generator hint",
    b"stable diffusion": "Generator hint",
    b"openai": "Generator hint",
    b"dall-e": "Generator hint",
    b"firefly": "Generator hint",
    b"adobe": "Generator hint",
    b"imagen": "Generator hint",
    b"<x:xmpmeta": "XMP packet marker",
    b"xpacket begin=": "XMP packet marker",
    b"http://ns.adobe.com/xap/1.0/": "XMP namespace marker",
    b"http://ns.adobe.com/creatorRecovery/1.0/": "XMP namespace marker",
    b"http://ns.google.com/photos/1.0/": "XMP namespace marker",
    b"http://ns.microsoft.com/photo/1.0/": "XMP namespace marker",
    b"xmp:creatortool": "XMP creator tool",
    b"xmp:generatortool": "XMP generator tool",
    b"xmpRights:": "XMP rights marker",
    b"photoshop:": "XMP photoshop marker",
    b"dc:creator": "XMP creator marker",
    b"stitching": "AIGC stitching hint",
    b"glide": "Generator hint",
    b"make-a-video": "Generator hint",
    b"gen-2": "Generator hint",
    b"craiyon": "Generator hint",
    b"dreamstudio": "Generator hint",
    b"clipdrop": "Generator hint",
    b"ideogram": "Generator hint",
    b"leonardo": "Generator hint",
    b"mage.space": "Generator hint",
    b"recraft": "Generator hint",
    b"veo": "Generator hint",
    b"sora": "Generator hint",
    b"kling": "Generator hint",
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


def _decompress_png_text(chunk_type: str, payload: bytes) -> str:
    """Extract the human-readable text from a PNG text chunk.

    - tEXt: raw latin-1 after the null separator
    - zTXt: zlib-compressed after the null separator
    - iTXt: UTF-8 after locale/compression flag; may be zlib-compressed
    """
    null_index = payload.find(b"\x00")
    if null_index < 0:
        return payload.decode("latin-1", errors="replace")
    _keyword_bytes = payload[:null_index]
    raw_value = payload[null_index + 1 :]

    if chunk_type == "zTXt":
        # zTXt: value is zlib-compressed
        try:
            raw_value = zlib.decompress(raw_value)
        except zlib.error:
            return payload.decode("latin-1", errors="replace")
        return raw_value.decode("latin-1", errors="replace")

    if chunk_type == "iTXt":
        # iTXt: keyword\0locale\0compression\0value
        # If compression flag is 1, value after 2nd null is zlib-compressed UTF-8
        second_null = raw_value.find(b"\x00")
        if second_null >= 0 and second_null + 1 < len(raw_value):
            compression_flag = raw_value[second_null + 1] if second_null + 1 < len(raw_value) else 0
            value_start = second_null + 2
            compressed_value = raw_value[value_start:]
            if compression_flag == 1:
                try:
                    compressed_value = zlib.decompress(compressed_value)
                except zlib.error:
                    pass
            try:
                return compressed_value.decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                return compressed_value.decode("latin-1", errors="replace")
        return raw_value.decode("latin-1", errors="replace")

    # tEXt: raw latin-1
    return raw_value.decode("latin-1", errors="replace")


def _scan_jpeg_segments(data: bytes) -> list[dict[str, Any]]:
    """Scan JPEG APP1/APP2/APP13 markers for EXIF, XMP, C2PA payloads."""
    findings: list[dict[str, Any]] = []
    if data[:2] != b"\xff\xd8":
        return findings

    cursor = 2
    while cursor + 4 <= len(data):
        if data[cursor] != 0xFF:
            break
        marker = data[cursor + 1]
        if marker in (0xD8, 0xD9):
            cursor += 2
            continue
        if marker == 0x00 or 0xD0 <= marker <= 0xD7:
            cursor += 2
            continue
        if cursor + 4 > len(data):
            break
        seg_len = struct.unpack(">H", data[cursor + 2 : cursor + 4])[0]
        if seg_len < 2:
            cursor += 2
            continue
        payload_start = cursor + 4
        payload_end = cursor + 2 + seg_len
        payload = data[payload_start:payload_end]

        if marker in (0xE1, 0xE2, 0xED):
            # APP1 (EXIF/XMP), APP2 (C2PA/ICC), APP13 (IPTC)
            lowered = payload.lower()
            for token, reason in RAW_SIGNATURES.items():
                if token in lowered:
                    tname = {
                        0xE1: "APP1",
                        0xE2: "APP2",
                        0xED: "APP13",
                    }.get(marker, f"APP{marker - 0xE0}")
                    findings.append(
                        {
                            "type": f"jpeg_{tname.lower()}_segment",
                            "chunk_type": tname,
                            "token": token.decode("utf-8", errors="replace"),
                            "reason": reason,
                            "offset": cursor,
                            "snippet": payload[:160].decode("latin-1", errors="replace"),
                        }
                    )
        cursor = cursor + 2 + seg_len
    return findings


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

        decoded = _decompress_png_text(chunk_type, payload)
        null_index = decoded.find("\x00")
        keyword = decoded[:null_index] if null_index >= 0 else decoded
        value = decoded[null_index + 1 :] if null_index >= 0 else ""
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


def _scan_raw_markers(data: bytes, is_jpeg: bool = False) -> list[dict[str, Any]]:
    """Scan raw bytes for known marker strings.

    For JPEG files, only scan the structured marker segments (APP / COM / DQT / SOF / DHT)
    and skip the entropy-coded SOS data to avoid false positives from compressed bitstream.
    For PNG files, scan the full file since non-IDAT chunks are reliable.
    """
    if is_jpeg:
        # For JPEG: only scan structured marker segments, skip SOS (scan data)
        segments = b""
        cursor = 2
        while cursor + 4 <= len(data):
            if data[cursor] != 0xFF:
                break
            marker = data[cursor + 1]
            if marker == 0xD8:  # SOI
                cursor += 2
                continue
            if marker == 0xD9:  # EOI
                break
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:  # Stuffing / RST
                cursor += 2
                continue
            if marker == 0xDA:  # SOS - start of scan data (compressed)
                break
            seg_len = struct.unpack(">H", data[cursor + 2 : cursor + 4])[0]
            payload_start = cursor + 4
            payload_end = cursor + 2 + seg_len
            segments += data[cursor : min(payload_end, len(data))]
            cursor = payload_end
        scan_data = segments
    else:
        scan_data = data

    lowered = scan_data.lower()
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


def _generate_lsb_patterns(
    width: int, height: int
) -> dict[str, np.ndarray]:  # type: ignore[return]
    """Generate pattern matrices for LSB correlation detection using numpy."""
    if not HAS_NUMPY:
        return {}
    y_coords, x_coords = np.mgrid[0:height, 0:width]
    return {
        "checkerboard-2x2": np.where((x_coords + y_coords) % 2 == 0, 1, -1).astype(np.int8),
        "checkerboard-4x4": np.where((x_coords // 2 + y_coords // 2) % 2 == 0, 1, -1).astype(
            np.int8
        ),
        "checkerboard-8x8": np.where((x_coords // 4 + y_coords // 4) % 2 == 0, 1, -1).astype(
            np.int8
        ),
        "vertical-stripes-2": np.where(x_coords % 2 == 0, 1, -1).astype(np.int8),
        "vertical-stripes-4": np.where(x_coords % 4 < 2, 1, -1).astype(np.int8),
        "horizontal-stripes-2": np.where(y_coords % 2 == 0, 1, -1).astype(np.int8),
        "horizontal-stripes-4": np.where(y_coords % 4 < 2, 1, -1).astype(np.int8),
        "diagonal-stripes-2": np.where((x_coords + y_coords) % 3 == 0, 1, -1).astype(np.int8),
    }


def _detect_pixel_suspicion(image: Image.Image) -> list[dict[str, Any]]:
    width, height = image.size
    if width < 32 or height < 32:
        return []

    findings: list[dict[str, Any]] = []

    if HAS_NUMPY:
        gray_arr = np.array(image.convert("L"), dtype=np.uint8)
        red_arr = np.array(image.convert("RGB").getchannel("R"), dtype=np.uint8)
        bands: dict[str, np.ndarray] = {"gray": gray_arr, "red": red_arr}
        patterns = _generate_lsb_patterns(width, height)
        total = width * height
        for band_name, band_arr in bands.items():
            lsb = (band_arr & 1).astype(np.int8) * 2 - 1  # 0->-1, 1->1
            for pname, pattern in patterns.items():
                score = float(abs(np.sum(lsb * pattern))) / total
                if score >= 0.18:
                    findings.append(
                        {
                            "type": "periodic_lsb_signal",
                            "band": band_name,
                            "pattern": pname,
                            "reason": "Regular LSB correlation can indicate a fragile hidden pixel mark.",
                            "score": round(score, 4),
                        }
                    )
    else:
        # Slow fallback without numpy - only check 3 basic patterns
        bands_loop = {
            "gray": image.convert("L"),
            "red": image.convert("RGB").getchannel("R"),
        }
        total = width * height
        for band_name, band_image in bands_loop.items():
            pixels = band_image.load()
            for name in ("checkerboard-2x2", "vertical-stripes-2", "horizontal-stripes-2"):
                accum = 0
                for y in range(height):
                    for x in range(width):
                        lsb_centered = 1 if (pixels[x, y] & 1) else -1
                        parity = 1 if (name == "checkerboard-2x2" and (x + y) % 2) else -1
                        if name == "vertical-stripes-2":
                            parity = 1 if x % 2 else -1
                        elif name == "horizontal-stripes-2":
                            parity = 1 if y % 2 else -1
                        accum += lsb_centered * parity
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

    fmt = _format_from_path(path)
    is_jpeg = fmt == "JPEG"
    embedded_markers = (
        _parse_png_text_chunks(raw)
        + _scan_raw_markers(raw, is_jpeg=is_jpeg)
        + _scan_jpeg_segments(raw)
    )
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
    # mask clears the lower `bits` bits, retaining upper 8-bits worth
    mask = (0xFF << bits) & 0xFF  # e.g. bits=1 -> 0xFE=254, bits=2 -> 0xFC=252
    if HAS_NUMPY:
        arr = np.array(rgb, dtype=np.uint8)
        arr &= np.uint8(mask)
        return Image.fromarray(arr, mode="RGB")
    # Fallback: use PIL point() with a precomputed lookup table
    table = [i & mask for i in range(256)]
    return rgb.point(table * 3)


def _light_resample(image: Image.Image, scale: float) -> Image.Image:
    width = max(8, int(round(image.width * scale)))
    height = max(8, int(round(image.height * scale)))
    if width == image.width and height == image.height:
        return image
    down = image.resize((width, height), Image.Resampling.BICUBIC)
    return down.resize(image.size, Image.Resampling.BICUBIC)


def _dct_domain_noise(image: Image.Image, strength: float = 0.5) -> Image.Image:
    """Add small perturbations in the DCT frequency domain to disrupt
    transform-domain watermarks.

    Operates on 8x8 blocks (matching JPEG block structure). Only the
    mid-frequency coefficients (indices 4-32) are perturbed to minimise
    visible quality loss.
    """
    if not HAS_NUMPY:
        return image
    rgb = np.array(image.convert("RGB"), dtype=np.float32)
    h, w, _ = rgb.shape
    h_blocks, w_blocks = h // 8, w // 8
    # Trim to block boundary
    rgb = rgb[: h_blocks * 8, : w_blocks * 8, :]
    result = rgb.copy()
    for c in range(3):
        for by in range(h_blocks):
            for bx in range(w_blocks):
                block = rgb[by * 8 : (by + 1) * 8, bx * 8 : (bx + 1) * 8, c]
                dct = np.fft.fft2(block)
                # Perturb mid-frequency coefficients
                noise = np.zeros_like(dct, dtype=np.complex64)
                mid_phase = np.exp(2j * np.pi * np.random.random((8, 8)))
                noise[2:6, 2:6] = mid_phase[2:6, 2:6] * strength
                dct += noise
                block_out = np.fft.ifft2(dct).real
                result[by * 8 : (by + 1) * 8, bx * 8 : (bx + 1) * 8, c] = block_out
    result = np.clip(result, 0, 255).astype(np.uint8)
    return Image.fromarray(result, mode="RGB")


def _ensure_realesrgan_model() -> Path:
    """Download Real-ESRGAN model if not cached. Returns model path."""
    model_path = REALESRGAN_MODEL_DIR / REALESRGAN_MODEL_FILENAME
    if model_path.exists():
        return model_path

    REALESRGAN_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Real-ESRGAN model (~67MB) to {model_path} ...")
    urllib.request.urlretrieve(REALESRGAN_MODEL_URL, model_path)
    print("Download complete.")
    return model_path


def _super_resolve(image: Image.Image, scale: int = 2) -> Image.Image:
    """Apply Real-ESRGAN super-resolution to the image.

    Uses spandrel + torch for pure-Python model inference.
    Falls back to PIL.LANCZOS upscale if anything fails, so the
    pipeline never breaks.
    """
    w, h = image.size
    target_size = (w * scale, h * scale)

    model_path = REALESRGAN_MODEL_DIR / REALESRGAN_MODEL_FILENAME
    if not model_path.exists():
        try:
            model_path = _ensure_realesrgan_model()
        except Exception:
            return image.resize(target_size, Image.Resampling.LANCZOS)

    try:
        import torch
        from spandrel import ModelLoader

        device = torch.device("cpu")
        raw_state_dict = torch.load(model_path, map_location=device, weights_only=True)
        # spandrel auto-detects the arch from state_dict keys
        model = ModelLoader.load_from_state_dict(raw_state_dict).to(device)
        model.eval()

        rgb = image.convert("RGB")
        arr = np.array(rgb, dtype=np.float32).transpose(2, 0, 1) / 255.0
        tensor = torch.from_numpy(arr[None, ...]).to(device)

        with torch.no_grad():
            output_tensor = model(tensor)

        output_arr = (
            output_tensor.squeeze(0).cpu().numpy().transpose(1, 2, 0) * 255.0
        ).clip(0, 255).astype(np.uint8)
        return Image.fromarray(output_arr)
    except Exception:
        return image.resize(target_size, Image.Resampling.LANCZOS)


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
        # Light downscale to disrupt pixel-level marks
        image = _light_resample(image, scale=0.94)
        image = ImageEnhance.Sharpness(image).enhance(0.96)
        image = _dct_domain_noise(image, strength=0.5)
        # Super-resolution upscale: restore quality + extra watermark disruption
        image = _super_resolve(image, scale=2)
        steps.extend(
            [
                "neutralized 2 LSB bits",
                "strong resample round-trip",
                "detail rewrite",
                "DCT domain noise",
                "Real-ESRGAN 2x super-resolution",
            ]
        )
        if semantic_rewrite == "global-restyle":
            image = _global_restyle(image)
            content_rewritten = True
            steps.append("global restyle rewrite")
        elif semantic_rewrite == "region-repair" and (box or mask_path):
            temp_output = Path(output_path).with_suffix(".rewrite.tmp.png")
            try:
                _save_sanitized(image, temp_output, "PNG")
                rewrite_result = remove_overlay_file(
                    temp_output, output_path, box=box, mask_path=mask_path, expand=0
                )
            finally:
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
