from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, PngImagePlugin

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_ROOT = PROJECT_ROOT / "cli"
if str(CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(CLI_ROOT))

from aigc_mark_toolkit.toolkit import (  # noqa: E402
    clean_aigc_marks,
    inspect_image,
    recheck_images,
    remove_overlay_file,
    strip_metadata_file,
)


def _gradient_image(size: tuple[int, int] = (128, 128)) -> Image.Image:
    width, height = size
    pixels = []
    for y in range(height):
        for x in range(width):
            pixels.append(((x * 2 + 30) % 256, (y * 2 + 60) % 256, ((x + y) + 90) % 256))
    image = Image.new("RGB", size)
    image.putdata(pixels)
    return image


def _write_marked_png(path: Path) -> None:
    image = _gradient_image()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("AIGC", "AIGC\0demo-hidden-marker")
    image.save(path, pnginfo=metadata)


def _write_plain_png(path: Path) -> None:
    _gradient_image().save(path)


def _write_lsb_suspect_png(path: Path) -> None:
    source = _gradient_image().convert("RGB")
    pixels = []
    width, height = source.size
    for y in range(height):
        for x in range(width):
            red, green, blue = source.getpixel((x, y))
            marker = 1 if (x + y) % 2 else 0
            pixels.append(((red & 0xFE) | marker, green, blue))
    image = Image.new("RGB", source.size)
    image.putdata(pixels)
    image.save(path)


def _write_overlay_png(path: Path) -> tuple[int, int, int, int]:
    image = _gradient_image(size=(160, 120))
    draw = ImageDraw.Draw(image)
    box = (24, 20, 118, 74)
    draw.rectangle(box, fill=(240, 40, 40))
    image.save(path)
    return box


class ToolkitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_inspect_detects_png_text_marker(self) -> None:
        marked = self.root / "marked.png"
        _write_marked_png(marked)

        report = inspect_image(marked)

        self.assertEqual(report["summary"]["embedded_marker_status"], "detected")
        self.assertTrue(
            any(item["type"] == "png_text_chunk" for item in report["embedded_markers"])
        )

    def test_strip_metadata_then_recheck_confirms_removed(self) -> None:
        marked = self.root / "marked.png"
        stripped = self.root / "stripped.png"
        _write_marked_png(marked)

        strip_metadata_file(marked, stripped)
        recheck = recheck_images(marked, stripped)

        self.assertEqual(recheck["comparison"]["result_label"], "confirmed removed")
        self.assertFalse(recheck["after"]["embedded_markers"])

    def test_inspect_plain_png_does_not_false_positive(self) -> None:
        plain = self.root / "plain.png"
        _write_plain_png(plain)

        report = inspect_image(plain)

        self.assertEqual(report["summary"]["embedded_marker_status"], "not_detected")
        self.assertEqual(report["summary"]["pixel_suspicion_status"], "not_detected")
        self.assertFalse(report["embedded_markers"])

    def test_inspect_reports_pixel_suspicion_without_embedded_marker(self) -> None:
        suspect = self.root / "suspect.png"
        _write_lsb_suspect_png(suspect)

        report = inspect_image(suspect)

        self.assertEqual(report["summary"]["embedded_marker_status"], "not_detected")
        self.assertEqual(report["summary"]["pixel_suspicion_status"], "suspicious")
        self.assertTrue(report["pixel_suspicions"])

    def test_remove_overlay_only_changes_specified_region(self) -> None:
        source = self.root / "overlay.png"
        output = self.root / "overlay.cleaned.png"
        box = _write_overlay_png(source)

        remove_overlay_file(source, output, box="24,20,118,74")

        before = Image.open(source).convert("RGB")
        after = Image.open(output).convert("RGB")
        width, height = before.size
        x1, y1, x2, y2 = box

        changed_inside = False
        for y in range(height):
            for x in range(width):
                different = before.getpixel((x, y)) != after.getpixel((x, y))
                if x1 <= x < x2 and y1 <= y < y2:
                    changed_inside = changed_inside or different
                else:
                    self.assertFalse(different)

        self.assertTrue(changed_inside)

    def test_clean_pipeline_reports_steps_for_all_strategies(self) -> None:
        marked = self.root / "marked.png"
        _write_marked_png(marked)

        for strategy in ("preserve", "balanced", "aggressive"):
            report = clean_aigc_marks(marked, self.root / strategy, strategy=strategy)
            self.assertEqual(report["strategy"], strategy)
            self.assertTrue(report["steps"])
            self.assertTrue(Path(report["result_image_path"]).exists())
            self.assertIn("comparison", report["recheck"])
            self.assertIn("content_rewritten", report)

    def test_aggressive_region_repair_marks_content_rewritten(self) -> None:
        overlay = self.root / "overlay.png"
        _write_overlay_png(overlay)

        report = clean_aigc_marks(
            overlay,
            self.root / "aggressive-region",
            strategy="aggressive",
            semantic_rewrite="region-repair",
            box="24,20,118,74",
        )

        self.assertTrue(report["content_rewritten"])
        self.assertTrue(report["recheck"]["comparison"]["content_rewritten"])
        self.assertTrue(Path(report["result_image_path"]).exists())

    def test_recheck_does_not_overclaim_when_only_pixel_signal_changes(self) -> None:
        suspect = self.root / "suspect.png"
        _write_lsb_suspect_png(suspect)

        report = clean_aigc_marks(suspect, self.root / "balanced-out", strategy="balanced")

        self.assertNotEqual(report["recheck"]["comparison"]["result_label"], "confirmed removed")


if __name__ == "__main__":
    unittest.main()
