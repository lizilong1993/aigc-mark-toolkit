# aigc-mark-toolkit

`aigc-mark-toolkit` is a local-first, independently runnable toolkit for inspecting and reducing AIGC-related image marks with evidence-based recheck output.

It does not promise unverifiable claims like "100% removed." The product contract is:

- maximize removal coverage
- preserve a repeatable local workflow
- generate before/after evidence
- distinguish `confirmed removed` from `not detected after processing`

## Scope

The toolkit covers three classes of image marks:

- visible overlays such as logos, text, or badges
- file-level embedded markers such as PNG text chunks, EXIF/XMP payloads, and C2PA-like signatures
- pixel-level suspicion signals such as fragile LSB-style patterns or periodic bitplane artifacts

## Repository Layout

- `cli/`: Python package and CLI implementation
- `skill/`: thin local wrapper that invokes the repository CLI
- `references/`: methodology and wording boundaries
- `tests/`: automated tests and sample generators
- `SKILL.md`: discoverable local skill entry

## Local Install

Use any normal Python environment. This project does not depend on your private skill scaffolding after creation.

```powershell
cd C:\Users\lizilong\.codex\skills\learned\aigc-mark-toolkit
py -3 -m pip install --no-build-isolation -e .
```

If you do not want to install the package, you can call the thin wrapper directly:

```powershell
powershell -ExecutionPolicy Bypass -File .\skill\run-local-skill.ps1 inspect path\to\image.png
```

## Commands

```powershell
aigc-mark-toolkit inspect input.png --output inspect.json
aigc-mark-toolkit strip-metadata input.png --output stripped.png
aigc-mark-toolkit normalize-image input.png --output normalized.png --strategy balanced
aigc-mark-toolkit remove-overlay input.png --output repaired.png --box 20,20,120,80
aigc-mark-toolkit recheck input.png repaired.png --output recheck.json
clean-aigc-marks input.png --output-dir .\out --strategy aggressive --box 20,20,120,80 --semantic-rewrite region-repair
```

## Strategy Levels

- `preserve`: strip metadata and do a light re-encode
- `balanced`: add LSB neutralization, profile stripping, alpha flattening when needed, and light resampling
- `aggressive`: allow stronger resampling and optional region rewrite; when content is repainted, the report marks the output as not pixel-faithful

## Output Boundary

Use the following result labels honestly:

- `confirmed removed`
- `not detected after processing`
- `residual suspicion remains`
- `cannot verify vendor-private watermark`

See `references/boundaries.md` for the full wording contract.
