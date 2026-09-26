---
version: alpha
name: NotAI
description: Dark-first terminal notebook UI. Derived from the Oh My Posh documentation theme (near-black surfaces, monospace chrome, single cornflower-blue accent).
colors:
  background: "#f4f6fa"
  background-dark: "#1b1b1b"
  surface: "#e9edf4"
  surface-dark: "#202020"
  surface-raised: "#ffffff"
  surface-raised-dark: "#262626"
  border: "#dbe0e9"
  border-dark: "#313131"
  border-strong: "#c1c8d6"
  border-strong-dark: "#434343"
  on-surface: "#131720"
  on-surface-dark: "#e7e7e7"
  on-surface-muted: "#59616f"
  on-surface-muted-dark: "#9c9c9c"
  primary: "#1f6feb"
  primary-dark: "#6ba5f8"
  primary-strong: "#1a5fd0"
  primary-strong-dark: "#4b8cf0"
  on-primary: "#ffffff"
  on-primary-dark: "#10161f"
  warn: "#f0f0c8"
  warn-dark: "#3b3b1d"
  on-warn: "#5c5c14"
  on-warn-dark: "#e3e38a"
  danger: "#b42318"
  danger-dark: "#f28b82"
typography:
  display:
    fontFamily: JetBrains Mono
    fontSize: 34px
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: -0.02em
  headline:
    fontFamily: JetBrains Mono
    fontSize: 22px
    fontWeight: 700
    lineHeight: 1.3
  title:
    fontFamily: JetBrains Mono
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0.02em
  code:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: 4px
  md: 8px
  lg: 12px
  full: 999px
spacing:
  1: 4px
  2: 8px
  3: 12px
  4: 16px
  5: 20px
  6: 28px
  7: 44px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: 9px 14px
  button-primary-dark:
    backgroundColor: "{colors.primary-dark}"
    textColor: "{colors.on-primary-dark}"
    rounded: "{rounded.md}"
    padding: 9px 14px
  button-ghost:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    padding: 9px 14px
  button-ghost-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-surface-dark}"
    rounded: "{rounded.md}"
    padding: 9px 14px
  card:
    backgroundColor: "{colors.surface-raised}"
    rounded: "{rounded.lg}"
    padding: 16px
  card-dark:
    backgroundColor: "{colors.surface-raised-dark}"
    rounded: "{rounded.lg}"
    padding: 16px
  chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface-muted}"
    rounded: "{rounded.full}"
    padding: 3px 10px
    typography: "{typography.label}"
  chip-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-surface-muted-dark}"
    rounded: "{rounded.full}"
    padding: 3px 10px
    typography: "{typography.label}"
  keycap:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.on-surface-muted}"
    rounded: "{rounded.sm}"
    padding: 2px 6px
  keycap-dark:
    backgroundColor: "{colors.surface-raised-dark}"
    textColor: "{colors.on-surface-muted-dark}"
    rounded: "{rounded.sm}"
    padding: 2px 6px
  input:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    padding: 8px 12px
  input-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-surface-dark}"
    rounded: "{rounded.md}"
    padding: 8px 12px
---

# NotAI

## Overview
A local-first notebook for developers. One notebook (caderno) holds many notes; a note is a run of
blocks (text, code, url, image, video) typed straight through with `Alt+Space` switching the
block kind under the cursor. Visual language is lifted from the Oh My Posh docs: near-black
surfaces, monospace chrome, hairline borders, one blue accent, no decorative gradients.

Audience is a single technical owner at a desktop keyboard, so density beats airiness and
every primary action has a hotkey.

Dial values: `DESIGN_VARIANCE: 4` (predictable split-pane product UI), `MOTION_INTENSITY: 2`
(only state-change feedback), `VISUAL_DENSITY: 6` (sidebar carries five per-type counters per
notebook).

## Colors
- **Background (#1b1b1b dark / #f4f6fa light):** app canvas.
- **Surface (#202020 / #e9edf4):** sidebar, top bar, inputs — the chrome band. In light the canvas
  is paper and the chrome sits *below* it in value; in dark the chrome sits above. Either way the
  point is the same: only what is elevated is pure white (`surface-raised`), so a card reads as a
  card without needing a shadow.
- **Surface raised (#262626 / #ffffff):** cards and blocks sitting on the canvas.
- **Border (#313131 / #dbe0e9):** 1px hairlines; the only separation device used in cards.
- **Primary (#6ba5f8 dark / #1f6feb light):** links, active nav, active block kind, primary CTA.
  The single accent on the whole app; nothing else is colored except the two semantic states.
- **Warn (#3b3b1d / #f0f0c8):** draft/unsaved state only. **Danger:** destructive hover only.

## Typography
Monospace throughout (`JetBrains Mono`, falling back to Cascadia Code / Consolas / ui-monospace).
Chrome leans monospace because the reference does; prose blocks use the same family at `body`
size with a 1.7 line-height so long text stays readable.

## Layout
Two-column split: fixed left sidebar (288px) + fluid main column, under a 52px top bar.
Sidebar carries the notebook list and its per-kind counters. Main column changes between
notebook overview, note editor, and the relations graph.

## Elevation & Depth
Flat. Depth comes from border contrast and one surface step, never from shadows. Only
floating surfaces (command palette, tag palette) get a single soft shadow to lift them off
the content they overlap.

## Shapes
`rounded.md` (8px) for interactive controls, `rounded.lg` (12px) for cards and blocks,
`rounded.full` for chips and avatars, `rounded.sm` (4px) for keycaps. Applied consistently;
no square/pill mixing outside that rule.

## Components
- **Buttons:** solid primary for the one commit action per view, ghost (surface + border) for
  everything else. Icon-only buttons are 32px squares.
- **Chips:** block-kind badges, tags, and counters. Outline chips for tags, filled chips for
  kind badges.
- **Cards:** note previews, blocks and the per-kind lists. Hairline border, no shadow, hover
  raises the border color; 14–18px of padding, and the footer of a card pins to the bottom
  (`margin-top: auto`) so the action lines up across cards of different heights. Radii step down
  with nesting: 12px on the container, 8px on what sits inside it.
- **Spacing:** everything horizontal/vertical comes from the `--space-*` scale in
  `styles/tokens.css` (4/8/12/16/20/28/44). Content column maxes at 1180px, 28px of padding, and
  the bottom padding is larger than the top so the page does not look cut off.
- **Motion:** 160ms on color/border of interactive surfaces, a 1px translate on press, and nothing
  else — no entrance animations on the working UI.
- **Inputs:** surface fill + border; focus replaces the border with the accent and adds a 2px
  accent halo.
- **Keycaps:** `Ctrl`, `K`, `Alt+Space` hints rendered as small bordered keys, uppercase.

## Do's and Don'ts
- Do keep exactly one accent color; semantic warn/danger are the only exceptions.
- Do keep counters visible: every notebook row shows its per-kind element counts.
- Do give every primary action a keyboard path; the mouse is the fallback.
- Don't add gradients, glows, or drop shadows to static surfaces.
- Don't use color to encode block kind alone; always pair it with the kind label.
