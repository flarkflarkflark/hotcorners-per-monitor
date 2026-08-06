# Application icon

- `hotcorners-per-monitor.png` — 1024×1024 RGBA master, transparent background.
- `hotcorners-per-monitor-512.png` — 512×512 RGBA, installed by `setup.sh` as the
  `hicolor` theme icon.

## Provenance

The original source PNG carried an embedded C2PA content-credentials chunk
(`caBX`) identifying it as generated via an external image-generation API,
plus an unrelated signing certificate chain, timestamps and an instance
UUID — none of it relevant to this repository. It was stripped from
`hotcorners-per-monitor.png` before committing; pixel data (including the
alpha channel) is byte-for-byte unchanged, verified by direct RGBA
comparison. Only `IHDR`/`IDAT`/`IEND` chunks remain.

## Regenerating the 512×512 variant

Generated once at release-preparation time, not on end-user install, so
`setup.sh` never depends on an image library:

```bash
magick assets/icons/hotcorners-per-monitor.png \
    -filter Lanczos -resize 512x512 \
    -define png:exclude-chunks=all -depth 8 \
    assets/icons/hotcorners-per-monitor-512.png
```

Produced with ImageMagick 7.1.2-29 (Q16-HDRI). Verified deterministic:
running the command twice from the same source produces byte-identical
output (same SHA-256).

## Small-size legibility

Inspected downscaled renders at 16/22/32/48/64/128/256/512px. Below ~32px
the fine detail that identifies the icon (cursor, corner triangle, midpoint
dot) blurs into an indistinct blue blob, and inventing a simplified design
for those sizes was out of scope for this change. Only 512×512 is shipped
and installed; `hicolor` theme lookup scales a single large icon down
correctly for smaller launcher contexts, so this is not a functional gap.
