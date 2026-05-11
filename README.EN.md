# aigc-mark-toolkit

> English version · [中文版](README.md)

Local-first, independently runnable toolkit for inspecting and reducing AIGC-related image marks with evidence-based recheck output.

**Honest claims only** — the toolkit never promises "100% removed." Output labels are strictly:
- `confirmed removed` — known marker was present before and absent after
- `not detected after processing` — no known marker detected after processing
- `residual suspicion remains` — some signal remains
- `cannot verify vendor-private watermark` — proprietary schemes are out of scope

---

## Quick Start

One-shot clean, no intermediate files:

```powershell
# Auto-named as {input_stem}_remove.jpg (in same directory as input)
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 quick-clean input.png

# Custom output path
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 quick-clean input.png --output result.jpg

# Choose strategy (default: aggressive)
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 quick-clean input.png --strategy balanced
```

### Batch Processing

```powershell
# Process all unprocessed images in directory (skips those with _remove.jpg)
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 batch-clean ./images

# Recursive (subdirectories included)
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 batch-clean ./images --recursive

# Force reprocess all
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 batch-clean ./images --force
```

---

## Detection Coverage

| Type | Method | Coverage |
|------|--------|----------|
| **File-level embedded markers** | PNG text chunk parsing + JPEG segment scanning + raw byte signature matching | C2PA, JUMBF, OpenAI, Veo, Sora, Midjourney, Stable Diffusion, Adobe Firefly, Google Imagen, 30+ generator signatures; XMP namespaces |
| **Visible overlays** | Alpha channel corner analysis | Semi-transparent logos, text, badges in corners |
| **Pixel-level steganography** | NumPy-vectorized LSB correlation (8 spatial patterns) | Checkerboard 2x2/4x4/8x8, stripes 2/4, diagonal patterns |
| **Frequency-domain watermarks** | FFT/DCT block analysis (aggressive mode injects DCT noise) | DCT/DWT domain embedded watermarks |

---

## Removal Capability

| Strategy | Operations | Use Case |
|----------|-----------|----------|
| `preserve` | Strip metadata + light re-encode | Metadata-only cleanup, preserve quality |
| `balanced` | + 1-bit LSB clear + 0.985x resample | General cleanup |
| `aggressive` | + 2-bit LSB clear + 0.94x resample + sharpness adj + **DCT domain noise + Real-ESRGAN 2x super-resolution** | Deep cleanup + quality restoration, extra watermark disruption through texture reconstruction |

Aggressive mode auto-converts PNG to JPEG and runs Real-ESRGAN 2x upscaling. The model (~64MB) auto-downloads on first use to `~/.cache/aigc-mark-toolkit/`.

---

## Command Reference

```powershell
# Inspect
aigc-mark-toolkit inspect input.png --output report.json

# Strip metadata
aigc-mark-toolkit strip-metadata input.png --output stripped.png

# Normalize image (core removal step)
aigc-mark-toolkit normalize-image input.png --output out.jpg --strategy aggressive

# Region overlay repair
aigc-mark-toolkit remove-overlay input.png --output repaired.png --box 20,20,120,80

# Before/after recheck
aigc-mark-toolkit recheck original.png processed.jpg --output recheck.json

# Full pipeline (with intermediate artifacts)
clean-aigc-marks input.png --output-dir ./out --strategy aggressive

# One-shot clean (no intermediate files)
aigc-mark-toolkit quick-clean input.png

# Batch clean directory (auto-skip processed)
aigc-mark-toolkit batch-clean ./images
aigc-mark-toolkit batch-clean ./images --recursive
```

---

## Installation

Requires Python 3.10+, Pillow, NumPy:

```powershell
# From project directory
py -3 -m pip install -e .

# Or use the thin wrapper directly (no install needed)
powershell -ExecutionPolicy Bypass -File skill/run-local-skill.ps1 quick-clean input.png
```

---

## Project Layout

```
cli/aigc_mark_toolkit/     # Python package + CLI implementation
skill/run-local-skill.ps1  # Thin local wrapper
references/                 # Methodology & wording boundaries
tests/                      # Automated tests
SKILL.md                   # Discoverable skill entry
```

---

## Output Labels

- `confirmed removed`
- `not detected after processing`
- `residual suspicion remains`
- `cannot verify vendor-private watermark`

See `references/boundaries.md` for the full wording contract.
