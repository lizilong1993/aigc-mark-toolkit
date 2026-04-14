---
name: aigc-mark-toolkit
description: Use when checking an image for AIGC watermark, AIGC metadata, C2PA, hidden logo, file-level embedded marks, or pixel-level watermark suspicion, and when removing AIGC marks locally from PNG, JPEG, or WebP with evidence-based recheck. Triggers include requests such as remove AIGC marks, remove AIGC watermark, remove hidden logo, 去除AIGC水印, 剥离元数据标记, C2PA inspection, or hidden watermark inspection.
---

# AIGC Mark Toolkit

## Overview

Use this skill when the job is to inspect or reduce image marks locally without making unverifiable claims. The repository works as a standalone CLI project; the skill layer is only a thin wrapper over the local command.

## Local Entry

- Prefer the repository CLI: `aigc-mark-toolkit ...` or `clean-aigc-marks ...`
- If the package is not installed, call `skill/run-local-skill.ps1`
- Keep all work inside this repository; do not depend on private `.system` helpers after creation

## Workflow

1. Run `inspect` on the original image.
2. Run `strip-metadata` to remove embedded text, EXIF, XMP, or C2PA-like payloads when possible.
3. Run `normalize-image` with `preserve`, `balanced`, or `aggressive`.
4. If there is a visible overlay and the user provides a `--box` or `--mask`, run `remove-overlay`.
5. Run `recheck` on original vs processed output.
6. For one-shot local cleanup, use `clean-aigc-marks`.

## Commands

- `inspect`: detect visible-overlay suspicion, embedded metadata markers, and basic pixel-level anomaly signals
- `strip-metadata`: rewrite PNG/JPEG/WebP without common text, EXIF/XMP, or similar embedded payloads
- `normalize-image`: re-encode, drop fragile bitplane marks, flatten alpha if needed, and optionally use stronger transforms
- `remove-overlay`: repair only the user-specified box or mask region
- `recheck`: compare before/after detection outputs and map them to an evidence label
- `clean-aigc-marks`: run inspect -> strip -> normalize -> optional overlay repair -> recheck -> report

## Boundary Rules

- Only say `confirmed removed` when a known detected marker was present before and absent after.
- If no known marker is detected after processing but there was no confirmed removable marker before, say `not detected after processing`.
- If pixel suspicion or overlay suspicion remains, say `residual suspicion remains`.
- Always keep the caveat `cannot verify vendor-private watermark` available for unknown or proprietary watermark schemes.

## References

- Read `references/methodology.md` for the three mark classes and processing logic.
- Read `references/boundaries.md` for the reporting contract.

## Thin Wrapper

The thin wrapper lives at `skill/run-local-skill.ps1`. It only resolves the repository root and forwards arguments to the local Python CLI.
