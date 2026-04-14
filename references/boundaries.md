# Reporting Boundaries

Use these labels consistently.

## `confirmed removed`

Use only when:

- a known marker was detected before processing
- the same class of marker is absent after processing

Typical examples:

- a PNG `AIGC` text chunk is gone after `strip-metadata`
- a previously detected embedded `C2PA` signature no longer appears

## `not detected after processing`

Use when:

- no known marker is detected after processing
- but the tool does not have enough evidence to say a specific known marker was confirmed removed

Typical examples:

- the original image only had pixel suspicion, and the same known signal is no longer detected
- the original image had no embedded marker, and the processed output also has none

## `residual suspicion remains`

Use when:

- pixel suspicion remains
- visible overlay suspicion remains
- or embedded markers are still present

## `cannot verify vendor-private watermark`

Use as a standing caveat whenever:

- the tool is reasoning about unknown proprietary watermark systems
- no public detector is available
- or processing changed the image but cannot prove a vendor-private watermark is gone

## Never Claim

Do not claim:

- "100% removed"
- "all AIGC watermarks are gone"
- "vendor watermark definitely removed"

unless there is a vendor-specific detector that actually verifies that claim.
