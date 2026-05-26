# SMA2 Layer 2 / Background ID Editor

**Author:** Oquendo · **Version:** v0.3 · **Target ROM:** Super Mario Advance 2 (GBA)

A command-line tool to edit Layer 2 background IDs, tilemap pointers, and visual header fields in Super Mario Advance 2. All edits are written directly to your working ROM.

![SMA2 BG Editor](assets/image.png)

---

## Table of Contents

1. [Requirements & Setup](#requirements--setup)
2. [How edits are saved](#how-edits-are-saved)
3. [Main Commands](#main-commands)
4. [Advanced Commands](#advanced-commands)
5. [Background IDs Reference](#background-ids-reference)
6. [Technical Reference](#technical-reference)

---

## Requirements & Setup

- Python 3.8+ (standard library only, no pip installs needed)
- A legally-obtained Super Mario Advance 2 ROM (`sma2.gba`)

Place `sma2_bgid_editor.py` anywhere. Run it from your terminal:

```
python sma2_bgid_editor.py
```

Running with no arguments prints the main command guide. To see all advanced commands:

```
python sma2_bgid_editor.py sma2.gba help
```

---

## How edits are saved

Every write command modifies your ROM **in-place** — the same file you pass in is the one that gets updated. There is no `_edited` copy. Make a backup of your original ROM before you start editing.

---

## Main Commands

These commands cover the most common editing tasks.

## Before / After

![Before](assets/before.png)

![After](assets/after.png)

### `info` — List all backgrounds

```
python sma2_bgid_editor.py sma2.gba info
```

Lists all 18 known backgrounds with their L2 tilemap offsets and the full header preset the tool uses for each one (bg_pal, fg_pal, sp_pal, tileset, bg_color).

> **No ROM needed for this command.** The table is built from internal data.

### `list` — See all sublevels

```
python sma2_bgid_editor.py sma2.gba list
python sma2_bgid_editor.py sma2.gba list --raw
```

Lists all named sublevels with their current BGID and L2 tilemap pointer. Also flags mismatches between the BGID and the pointer.

- Without `--raw`: only named sublevels are shown
- With `--raw`: all 521 sublevel slots (0x000–0x208) are dumped

### `get` — Full details

```
python sma2_bgid_editor.py sma2.gba get <sublevel_id>
```

Shows the BGID, L2 pointer, and sublevel/ROM offset info. Reports `[vanilla override]` or `[MISMATCH]` if the pointer does not match the BGID.

```
python sma2_bgid_editor.py sma2.gba get 0x105
```

### `get-header` — Full header info

```
python sma2_bgid_editor.py sma2.gba get-header <sublevel_id>
```

Shows the full 7-byte Layer 1 header for a sublevel — every field, its current value, and the raw bytes.

```
python sma2_bgid_editor.py sma2.gba get-header 0x105
```

Fields shown: `length`, `bg_pal`, `level_mode`, `scroll_a`, `sp_tileset`, `music`, `fg_pal`, `sp_pal`, `timer`, `tileset`, `bg_color`, and the raw 7-byte hex dump.

### `set` — Change background

```
python sma2_bgid_editor.py sma2.gba set <sublevel_id> <new_bgid>
```

The main editing command. Does three things automatically:

1. Writes the new BGID to the BGID table
2. Updates the L2 tilemap pointer to match the new background
3. Patches the tileset ID in the header (auto, from a preset)

Then interactively asks you two questions:

```
  Background palette:
    0 = green
    1 = blue
    2 = beige  <-- current
    3 = brown
    4 = strong purple (unused)
    5 = dark gray
    6 = dark brown
    7 = default green
  Pick Background palette (0-7) [Enter = keep 2]: _

  Back area color:
    0 = beige
    1 = light green
    2 = blue (default)
    3 = black
    4 = dark green
    5 = dark blue
    6 = light blue
    7 = white
  Pick Back area color (0-7) [Enter = keep 3]: _
```

Press **Enter** to keep the current value.

### `batch` — Change multiple at once

```
python sma2_bgid_editor.py sma2.gba batch <sub=bgid> [sub=bgid...]
```

Changes multiple sublevels in one pass. No interactive prompts — only BGID and L2 pointer are updated.

```
python sma2_bgid_editor.py sma2.gba batch 0x105=0x11 0x106=0x0D 0x107=0x00
```

---

## Options

| Option | Effect |
|--------|--------|
| `--keep-ptr` | Skips updating the L2 tilemap pointer. Only the BGID byte is changed. Useful to replicate intentional vanilla overrides. Works with `set` and `batch`. |

---

## Background IDs Reference

| BGID | Description | Tileset |
|------|-------------|---------|
| `0x00` | Yoshi's Island Mountains (default) | 0 |
| `0x01` | Aquatic | 9 |
| `0x02` | Athletic / Low Clouds with mountains | 0 |
| `0x03` | Athletic / High Clouds | 0 |
| `0x04` | Low Mountains | 0 |
| `0x05` | Chocolate Island Mountains | 0 |
| `0x06` | Castle 1 | 1 |
| `0x07` | High Mountains | 0 |
| `0x08` | Switch Palace | 4 |
| `0x09` | Night Stars | 6 |
| `0x0A` | Beta Mountains? | 0 |
| `0x0B` | Blank Background | 1 |
| `0x0C` | Castle 2 | 1 |
| `0x0D` | Underground | 3 |
| `0x0E` | Forest of Illusion / Jungle | 0 |
| `0x0F` | Ghost House | 5 |
| `0x10` | Sunken Ship | 5 |
| `0x11` | Castle 3 | 1 |
| `0xFF` | Interactive L2 (object data) | — |

---

## Technical Reference

### ROM Tables and Addresses

### BGID Table
```
ROM offset : 0x0F3B38 – 0x0F3D40
GBA address: 0x080F3B38
Size       : 0x209 entries, 1 byte each (521 sublevels)
Formula    : offset = 0x0F3B38 + sublevel_id
```

### L2 Tilemap Pointer Table
```
ROM offset : 0x0F2AF0 – 0x0F3313
GBA address: 0x080F2AF0
Size       : 0x209 entries, 4 bytes each (little-endian GBA pointers)
Formula    : offset = 0x0F2AF0 + sublevel_id * 4
```

### L1 Data Pointer Table (header access)
```
ROM offset : 0x0F22CC – 0x0F2AEF
GBA address: 0x080F22CC
Size       : 0x209 entries, 4 bytes each (little-endian GBA pointers)
```

### The 7-Byte Level Header

Located at the address pointed to by the L1 pointer table. Layout:

<table>
  <tr><th>Byte</th><th>Layout</th></tr>
  <tr>
    <td><strong><font color="#FF6B6B">byte 0</font></strong></td>
    <td><code>bits 0-4</code> = length in screens<br>
        <code>bits 5-7</code> = Background palette ID</td>
  </tr>
  <tr>
    <td><strong><font color="#4ECDC4">byte 1</font></strong></td>
    <td><code>bits 0-4</code> = level mode<br>
        <code>bits 5-7</code> = scroll-related</td>
  </tr>
  <tr>
    <td><strong><font color="#95E881">byte 2</font></strong></td>
    <td><code>bits 0-3</code> = sprite tileset<br>
        <code>bits 4-7</code> = music index</td>
  </tr>
  <tr>
    <td><strong><font color="#FFD93D">byte 3</font></strong></td>
    <td><code>bits 0-2</code> = Foreground palette ID (never touched)<br>
        <code>bits 3-5</code> = Sprite palette ID (never touched)<br>
        <code>bits 6-7</code> = timer</td>
  </tr>
  <tr>
    <td><strong><font color="#FF6B6B">byte 4</font></strong></td>
    <td><code>bits 0-3</code> = Layer 1/2 tileset ID (auto from BGID)<br>
        <code>bits 4-7</code> = scroll/item memory</td>
  </tr>
  <tr>
    <td><strong><font color="#4ECDC4">byte 5</font></strong></td>
    <td><code>bits 0-3</code> = scroll-related<br>
        <code>bits 4-7</code> = Back area color ID</td>
  </tr>
  <tr>
    <td><strong><font color="#95E881">byte 6</font></strong></td>
    <td>unused, always 0x00</td>
  </tr>
</table>

**Legend:** <font color="#FF6B6B">byte 0, 4</font> = palette/tileset &nbsp;|&nbsp; <font color="#4ECDC4">byte 1, 5</font> = mode/color &nbsp;|&nbsp; <font color="#95E881">byte 2, 6</font> = sprites/unused &nbsp;|&nbsp; <font color="#FFD93D">byte 3</font> = palettes

---

## BG/FG Coupling and Risks

### Why the tileset is auto-locked to the BGID

The **Layer 1/2 tileset ID** (byte 4 bits 0–3) is a single shared field that controls **both** layers simultaneously:

- Which **16×16 tile layout tables** are used
- Which **object function pointers** are used
- Which **Layer 0 flag tables** are used

**If you change the tileset to one from a different group**, tile rendering breaks. This is why the tool sets the tileset automatically from the BGID.

### Why fg_pal and sp_pal are never modified

The **foreground palette** and **sprite palette** are tied to the actual graphics data loaded for Layer 1. Changing them without swapping the GFX files will corrupt colors.

### Summary: what is safe to change

| Field | Safe to change freely? | Notes |
|-------|------------------------|-------|
| BGID | Yes | Tool handles the pointer sync |
| Background palette | Yes | Only affects Layer 2 colors |
| Back area color | Yes | Only affects the solid backdrop |
| Tileset | **No** | Crossing groups breaks FG tile rendering |
| Foreground palette | **No** | Tied to loaded GFX data |
| Sprite palette | **No** | Same reason as FG palette |

---

## Intentional Vanilla Mismatches

Two sublevels have a BGID that does not match their L2 pointer:

| Sublevel | BGID | Actual L2 pointer | Notes |
|----------|------|-------------------|-------|
| `0x108` | `0x0A` | `0x080E42D0` | Intro cutscene — Vanilla Dome gfx, Plains layout |
| `0x112` | `0x00` | `0x080E4929` | Test level — Plains gfx, Chocolate Island layout |

Use `--keep-ptr` to preserve these overrides.
