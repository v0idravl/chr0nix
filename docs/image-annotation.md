# Image annotation: swappy, with investigative defaults

The suite does not annotate images itself. When an exhibit image needs
markup — arrows, boxes, redaction, callout text — the workflow is:

1. Hash and manifest the **original** first (`cust0dia`). The annotated
   copy is a *derivative exhibit*, never a replacement: annotate a copy,
   then manifest the copy alongside the original so both are on record.
2. Annotate the copy with [swappy](https://github.com/jtheoof/swappy)
   (external tool, invoked manually — the suite never executes it).
3. File the annotated copy next to the original and re-run the manifest.

## Recommended config (`~/.config/swappy/config`)

swappy's stock defaults are tuned for quick desktop screenshots: thin
lines, small text. For images that will end up in reports — possibly
printed, possibly projected in a courtroom — legibility wins:

```ini
[Default]
# Legibility first: thick strokes and large type survive printing,
# photocopying, and projection.
line_size=8
text_size=24
text_font=monospace

# Deliberate, not accidental: never save without an explicit decision,
# and keep the editor open until the operator says it is done.
auto_save=false
early_exit=false
show_panel=true

save_filename_format=swappy-%Y%m%d-%H%M%S.png
```

- `line_size=8` — visible at report scale; the default 5 disappears in
  print.
- `text_size=24` with `monospace` — readable at arm's length and on a
  projector; monospace keeps callout labels aligned and sober-looking.
- `auto_save=false`, `early_exit=false` — an annotation is an
  evidentiary artifact; it should exist because the operator chose to
  save it, not because a keybinding fired.

## On "jerky" freehand lines

swappy's brush mode draws raw pointer motion with no stroke smoothing,
so freehand lines inherit every tremor of the mouse. Two habits fix
most of it:

- **Prefer the shape tools** (arrow, line, rectangle, ellipse) over
  freehand brush for anything meant to be read by someone else. Shapes
  are rendered from two points — perfectly straight every time — and
  they look more professional in a report anyway.
- When a freehand mark genuinely is needed (circling an irregular
  region), slow down and draw at a higher zoom level; upscaled-pointer
  motion is what reads as "jerky" at 100%.

## Redaction note

Swappy draws *on top* of pixels; a black rectangle is not guaranteed to
destroy the underlying data in every export path. For true redaction,
crop or overwrite the region with a destructive editor after
annotation, and treat the pre-redaction original's custody accordingly
(it stays hashed and sealed in the evidence tree — its exposure is
governed by access control, not by the annotation).
