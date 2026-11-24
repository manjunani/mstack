---
name: image-batch
description: Applies one resize, crop and export to a whole folder of images into a new folder, and checks every output. Use when the user wants many photos resized, cropped to one shape, stripped of location data or exported for web or social. Previews the first few, then checks dimensions, file size, GPS removal and count; uses sips, ImageMagick or Pillow. Not for comparing UI to a mockup (use ui-match).
license: MIT
metadata:
  pack: media
  version: 0.2.2
  needs: python3; sips (macOS), ImageMagick or Pillow
---

# Image batch

Produces `<out>/preview/` (first few results) and `<out>/images/` (all results), each file checked.

## Done when

- The user saw the preview images and said yes.
- `image_batch.py run` (or `check`) passes: one output per input, every output exactly the asked dimensions (read from the file itself), under the size limit, with no GPS data.
- The input folder is unchanged.

End in exactly one state: **pass**, **fail**, **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| An image tool | `python3 scripts/image_batch.py tools` | end as blocked; name sips (built into macOS), ImageMagick or Pillow; ask before installing |

## Steps

The script is `scripts/image_batch.py` (`"${CLAUDE_SKILL_DIR}/scripts/image_batch.py"`).

1. **Settle the settings** with the user: width, height, `cover` (exact size, overflow trimmed evenly) or `within` (fits inside, nothing trimmed), JPEG or PNG, size limit.
2. **Preview.**
   ```
   python3 scripts/image_batch.py preview <folder> --out <new folder> --width 1200 --height 1200 --mode cover --max-kb 300
   ```
   Open the preview images and show them. A centred trim can cut off a face or a product; only a look catches that.
3. **Run** with the same settings after a yes.
   ```
   python3 scripts/image_batch.py run <folder> --out <same new folder> --width 1200 --height 1200 --mode cover --max-kb 300
   ```
4. **Report.** End state first, then counts, any file that failed and why, and the output folder.

## Rules

- Output always goes to a new folder; the script refuses the input folder and a folder that already holds files.
- Location removal drops the whole EXIF and XMP block, so camera details and orientation go too. Say so.
- A file over the size limit is fixed by a lower `--quality` or smaller size, chosen with the user.
- Background removal is not part of this version. Say so if asked; do not improvise it.

## Not for

- Comparing a built UI with a mockup → use `ui-match`.
- Video frames or thumbnails from footage → use `video-edit`.
- Deleting the original images → use `safe-delete`.

## Level

- beginner: explain cover and within with the preview.
- standard: as written.
- expert: run the preview and report failures only. The preview and every check remain.
