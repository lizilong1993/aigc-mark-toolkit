# Methodology

`aigc-mark-toolkit` treats image marks as three separate classes because they need different handling and different claims.

## 1. Visible Overlays

Examples:

- corner logos
- visible text such as "AI generated"
- badges or semi-transparent watermarks

Handling:

- detection is heuristic unless the user gives a region
- removal requires an explicit `--box` or `--mask`
- repair is constrained to the specified region only

## 2. File-Level Embedded Marks

Examples:

- PNG `tEXt`, `zTXt`, or `iTXt` chunks
- EXIF/XMP text payloads
- raw `C2PA`, `JUMBF`, or generator strings embedded in the file

Handling:

- `inspect` scans textual chunks and raw marker signatures
- `strip-metadata` removes them by decoding pixels and saving a clean file
- `recheck` can confirm removal when a previously detected embedded marker disappears

## 3. Pixel-Level or Frequency-Domain Suspicion

Examples:

- LSB-encoded patterns
- periodic bitplane artifacts
- fragile watermark signals that survive as pixel structure rather than metadata

Handling:

- `inspect` reports these as suspicion, not proof of a specific vendor watermark
- `normalize-image` breaks fragile signals through re-encoding, LSB neutralization, alpha flattening, and resampling
- `aggressive` can add stronger transforms or region rewrite

## Important Boundary

Unknown vendor-private watermark systems may not expose a public detector. In those cases the toolkit can report that a known signal is no longer detected, but it cannot honestly prove that every proprietary watermark is gone.
