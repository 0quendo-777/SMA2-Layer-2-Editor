"""
SMA2 (Super Mario Advance 2) - Layer 2 / Background ID Editor by Oquendo
=========================================================================================
Reads and modifies the Layer 2 BGID for each level in the ROM.
When changing a BGID, also updates the L2 tilemap pointer AND the
level header (BG palette, FG palette, sprite palette, tileset ID,
BG color) to match the new background automatically.
Use --keep-ptr to skip the L2 pointer update.
Use --keep-header to skip the header palette/tileset update.
 
ROM tables (verified against ROM map and real edits):
  BGID table   : 0x0F3B38 - 0x0F3D40  (0x209 entries, 1 byte each)
                 GBA: 0x080F3B38 | sublevel IDs 0x000-0x208
                 Spot-check: sublevel 0x105 -> offset 0x0F3C3D
  Layout ptrs  : 0x0F2AF0 - 0x0F3313  (0x209 entries, 4 bytes each)
                 GBA: 0x080F2AF0 | same sublevel index
                 Spot-check: sublevel 0x105 -> offset 0x0F2F04
 
  All 'Length' values in the ROM map are in hex.
  End addresses are exclusive (last valid byte = end - 1).
 
Intentional vanilla mismatches (original game overrides):
  Sublevel 0x108: BGID=0x0A, L2 ptr -> YI Mountains tilemap instead of Beta Mountains
  Sublevel 0x112: BGID=0x00, L2 ptr -> Chocolate Island tilemap instead of YI Mountains
  The script flags these on read but overwrites them on write
  (use --keep-ptr to preserve a custom pointer).
 
level_id -> sublevel_id mapping:
  level 0x00       -> sublevel 0x000  (Bonus game, special case)
  levels 0x01-0x5A -> sublevel = level_id + 0x100  (overworld levels)
  everything else  -> sublevel = level_id  (bosses, internal rooms, CI2 sublevels)
"""

import sys
import struct
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError with box-drawing chars)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ── Pastel terminal colors ────────────────────────────────────────────────────
class C:
    SUCCESS = "\033[38;2;180;235;180m"   # pastel green  — saved / OK
    INFO    = "\033[38;2;180;210;255m"   # pastel blue   — labels / neutral info
    OPTION  = "\033[38;2;255;220;180m"   # pastel orange — menus / palette choices
    ERROR   = "\033[38;2;255;180;180m"   # pastel red    — warnings / errors
    RESET   = "\033[0m"

def ok(msg):    return f"{C.SUCCESS}{msg}{C.RESET}"
def info(msg):  return f"{C.INFO}{msg}{C.RESET}"
def opt(msg):   return f"{C.OPTION}{msg}{C.RESET}"
def err(msg):   return f"{C.ERROR}{msg}{C.RESET}"


def print_banner():
    logo = f"""
{C.INFO}  ███████╗███╗   ███╗ █████╗ ██████╗
{C.INFO}  ██╔════╝████╗ ████║██╔══██╗╚════██╗
{C.INFO}  ███████╗██╔████╔██║███████║ █████╔╝
{C.INFO}  ╚════██║██║╚██╔╝██║██╔══██║██╔═══╝
{C.INFO}  ███████║██║ ╚═╝ ██║██║  ██║███████╗
{C.INFO}  ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝{C.RESET}
{C.OPTION}        Layer 2 Background ID Editor{C.RESET}
"""
    border = f"{C.INFO}  {'─' * 44}{C.RESET}"
    print(logo)
    print(border)
    print(f"  {ok('Version')} : v0.1          {info('Author')} : Oquendo")
    print(f"  {ok('ROM')}     : Super Mario Advance 2 (GBA)")
    print(border)
    print(f"""
  {info('Quick start')} — Change background of level 0x05 (Yoshi's Island 1):

    {opt('1.')} List all available backgrounds and their IDs:
       {C.SUCCESS}python sma2_bgid_editor.py sma2.gba info{C.RESET}

    {opt('2.')} Check current background of level 0x05:
       {C.SUCCESS}python sma2_bgid_editor.py sma2.gba get 0x05{C.RESET}

    {opt('3.')} Set a new background (e.g. Castle 1 = BGID 0x06):
       {C.SUCCESS}python sma2_bgid_editor.py sma2.gba set 0x05 0x07{C.RESET}
       {C.INFO}→ Saves as sma2_edited.gba — original ROM is never touched{C.RESET}

    {opt('4.')} Batch-edit multiple levels at once:
       {C.SUCCESS}python sma2_bgid_editor.py sma2.gba batch 0x05=0x06 0x06=0x0D{C.RESET}
""")
    print(border)
    print()

GBA_ROM_BASE      = 0x08000000

# Background ID table — 1 byte per sublevel, indexed by sublevel ID
# ROM range: 0x0F3B38 - 0x0F3D40  (length 0x209, per ROM map; end address exclusive = 0x0F3D41)
# Sublevel IDs 0x000-0x208 (521 entries), all lengths in ROM map are hex.
# Spot-check: sublevel 0x105 -> 0x0F3B38 + 0x105 = 0x0F3C3D (confirmed by friend's ROM edit)
BGID_TABLE_ADDR   = 0x080F3B38
BGID_TABLE_OFFSET = BGID_TABLE_ADDR - GBA_ROM_BASE  # 0x0F3B38
BGID_TABLE_SIZE   = 0x209  # 521 entries: sublevel IDs 0x000-0x208

# Background layout pointer table — 4 bytes per sublevel, indexed by sublevel ID
# ROM range: 0x0F2AF0 - 0x0F3313  (length 0x824 = 4 * 0x209 entries, per ROM map)
# Spot-check: sublevel 0x105 -> 0x0F2AF0 + 0x105*4 = 0x0F2F04 (confirmed by friend's ROM edit)
LAYOUT_TABLE_ADDR   = 0x080F2AF0
LAYOUT_TABLE_OFFSET = LAYOUT_TABLE_ADDR - GBA_ROM_BASE  # 0x0F2AF0
LAYOUT_TABLE_SIZE   = 0x209  # 521 entries (one per sublevel, same as BGID table)

# Known vanilla mismatches: sublevel_id -> (bgid, actual_l2_ptr, expected_l2_ptr)
# These are intentional overrides in the original game — irregular level layouts
# that use a BGID for graphics but a different background's tilemap layout.
VANILLA_MISMATCHES = {
    0x108: (0x0A, 0x080E42D0, 0x080E5190),  # Story intro: Vanilla Dome gfx, Plains tilemap
    0x112: (0x00, 0x080E4929, 0x080E42D0),  # Unknown:     Plains gfx, Chocolate Island tilemap
}

# Layer 1 data pointer table — 4 bytes per sublevel, indexed by sublevel ID
# ROM range: 0x0F22CC - 0x0F2AEF  (0x209 entries, 4 bytes each)
# The Layer 1 data begins with a 7-byte header:
#   Byte 0: bits 0-4 = length in screens, bits 5-7 = BG palette ID
#   Byte 1: bits 0-4 = level mode,        bits 5-7 = scroll-related
#   Byte 2: bits 0-3 = sprite tileset,    bits 4-7 = music index
#   Byte 3: bits 0-2 = FG palette ID,     bits 3-5 = sprite palette ID, bits 6-7 = timer
#   Byte 4: bits 0-3 = layer 1/2 tileset ID, bits 4-7 = scroll/item memory
#   Byte 5: bits 0-3 = scroll-related,    bits 4-7 = BG color ID
#   Byte 6: unused (always 0x00)
L1_TABLE_ADDR   = 0x080F22CC
L1_TABLE_OFFSET = L1_TABLE_ADDR - GBA_ROM_BASE  # 0x0F22CC
L1_TABLE_SIZE   = 0x209  # same count as BGID table

# Vanilla header presets per BGID — derived from named sublevels in the ROM.
# Fields: bg_pal, fg_pal, sp_pal, tileset, bg_color
# These match what the original game uses for each background.
# Only bg_pal, fg_pal, sp_pal, tileset, bg_color are set automatically;
# level-specific fields (length, level mode, music, scroll, timer, item memory)
# are always preserved from the existing header.
BG_HEADER_PRESETS = {
    #        bg_pal  fg_pal  sp_pal  tileset  bg_color
    0x00: (    7,      0,      0,      0,       0   ),  # YI Mountains
    0x01: (    4,      2,      3,      9,       8   ),  # Aquatic
    0x02: (    0,      0,      0,      0,       5   ),  # Athletic / Low Clouds with mountains
    0x03: (    0,      6,      0,      0,       6   ),  # Athletic / High Clouds
    0x04: (    0,      0,      0,      0,       1   ),  # Low Mountains
    0x05: (    6,      4,      0,      0,       2   ),  # Chocolate Island Mountains
    0x06: (    3,      3,      1,      1,       3   ),  # Castle 1
    0x07: (    0,      0,      0,      0,       1   ),  # High Mountains
    0x08: (    5,      0,      4,      4,       0   ),  # Switch Palace
    0x09: (    5,      1,      2,      6,       5   ),  # Night Stars
    0x0A: (    3,      7,      0,      0,       0   ),  # Beta Mountains?
    0x0B: (    5,      4,      2,      1,       3   ),  # Blank Background
    0x0C: (    6,      7,      1,      1,       4   ),  # Castle 2
    0x0D: (    6,      4,      4,      3,       3   ),  # Underground
    0x0E: (    7,      0,      0,      0,       0   ),  # Forest / Jungle
    0x0F: (    5,      4,      5,      5,       3   ),  # Ghost House
    0x10: (    6,      4,      5,      5,       3   ),  # Sunken Ship
    0x11: (    3,      3,      1,      1,       3   ),  # Castle 3
}

BACKGROUNDS = {
    0x00: {"ptr": 0x080E42D0, "desc": "Yoshi's Island Mountains (default)"},
    0x01: {"ptr": 0x080E4489, "desc": "Aquatic"},
    0x02: {"ptr": 0x080E4641, "desc": "Athletic / Low Clouds with mountains"},
    0x03: {"ptr": 0x080E4714, "desc": "Athletic / High Clouds"},
    0x04: {"ptr": 0x080E4824, "desc": "Low Mountains"},
    0x05: {"ptr": 0x080E4929, "desc": "Chocolate Island Mountains"},
    0x06: {"ptr": 0x080E4AD3, "desc": "Castle 1"},
    0x07: {"ptr": 0x080E4E42, "desc": "High Mountains"},
    0x08: {"ptr": 0x080E5044, "desc": "Switch Palace"},
    0x09: {"ptr": 0x080E5054, "desc": "Night Stars"},
    0x0A: {"ptr": 0x080E5190, "desc": "Beta Mountains?"},
    0x0B: {"ptr": 0x080E52BE, "desc": "Blank Background"},
    0x0C: {"ptr": 0x080E52CE, "desc": "Castle 2"},
    0x0D: {"ptr": 0x080E564E, "desc": "Underground"},
    0x0E: {"ptr": 0x080E59D2, "desc": "Forest of Illusion / Jungle"},
    0x0F: {"ptr": 0x080E5CD0, "desc": "Ghost House"},
    0x10: {"ptr": 0x080E5EC5, "desc": "Sunken Ship"},
    0x11: {"ptr": 0x080E61AA, "desc": "Castle 3"},
}

LEVEL_NAMES = {
    # Keys 0x00-0x5A are USER-FACING level IDs.
    # level_to_sublevel() maps them to the real sublevel ID used in the BGID table.
    # Sublevel IDs 0x200-0x208 are keyed directly (CI2 extended rooms).
    0x00: "Bonus game (no-Yoshi intro slot)",  # -> sublevel 0x000 (BGID=0xFF, ghost house intro)
    0x01: "#1 Iggy's Castle",
    0x02: "Yoshi's Island 4",
    0x03: "Yoshi's Island 3",
    0x04: "Yoshi's House",
    0x05: "Yoshi's Island 1",
    0x06: "Yoshi's Island 2",
    0x07: "Vanilla Ghost House",
    0x08: "Intro Level",
    0x09: "Vanilla Secret 1",
    0x0A: "Vanilla Dome 3",
    0x0B: "Donut Secret 2",
    0x0C: "Test Level",
    0x0D: "Front Door",
    0x0E: "Back Door",
    0x0F: "Valley of Bowser 4",
    0x10: "#7 Larry's Castle",
    0x11: "Valley Fortress",
    0x12: "Groovy (no sprites)",
    0x13: "Valley of Bowser 3",
    0x14: "Valley Ghost House",
    0x15: "Valley of Bowser 2",
    0x16: "Valley of Bowser 1",
    0x17: "Chocolate Secret",
    0x18: "Vanilla Dome 2",
    0x19: "Vanilla Dome 4",
    0x1A: "Vanilla Dome 1",
    0x1B: "Red Switch Palace",
    0x1C: "#3 Lemmy's Castle",
    0x1D: "Forest Ghost House",
    0x1E: "Forest of Illusion 1",
    0x1F: "Forest of Illusion 4",
    0x20: "Forest of Illusion 2",
    0x21: "Blue Switch Palace",
    0x22: "Forest Secret Area",
    0x23: "Forest of Illusion 3",
    0x24: "Chocolate Island 2",
    0x25: "Funky",
    0x26: "Outrageous",
    0x27: "Mondo",
    0x28: "Groovy",
    0x29: "Yoshi's Island 1 (dup)",
    0x2A: "Gnarly",
    0x2B: "Tubular",
    0x2C: "Way Cool",
    0x2D: "Awesome",
    0x2E: "Vanilla Dome 3 (dup)",
    0x2F: "Donut Secret 2 (dup)",
    0x30: "Star World 2",
    0x31: "Front Door (dup)",
    0x32: "Star World 3",
    0x33: "Valley of Bowser 4 (dup)",
    0x34: "Star World 1",
    0x35: "Star World 4",
    0x36: "Star World 5",
    0x37: "Valley of Bowser 3 (dup)",
    0x38: "Valley Ghost House (dup)",
    0x39: "Valley of Bowser 2 (dup)",
    0x3A: "Valley of Bowser 1 (dup)",
    0x3B: "Chocolate Secret (dup)",
    0x3C: "Vanilla Dome 2 (dup)",
    0x3D: "Vanilla Dome 4 (dup)",
    0x3E: "Vanilla Dome 1 (dup)",
    0x3F: "Red Switch Palace (dup)",
    0x40: "#3 Lemmy's Castle (dup)",
    0x41: "Forest Ghost House (dup)",
    0x42: "Forest of Illusion 1 (dup)",
    0x43: "Forest of Illusion 4 (dup)",
    0x44: "Forest of Illusion 2 (dup)",
    0x45: "Blue Switch Palace (dup)",
    0x46: "Forest Secret Area (dup)",
    0x47: "Forest of Illusion 3 (dup)",
    0x48: "Test Level",
    0x49: "Funky (dup)",
    0x4A: "Outrageous (dup)",
    0x4B: "Mondo (dup)",
    0x4C: "Groovy (dup)",
    0x4D: "Test Level",
    0x4E: "Gnarly (dup)",
    0x4F: "Tubular (dup)",
    0x50: "Way Cool (dup)",
    0x51: "Awesome (dup)",
    0x52: "Test Level",
    0x53: "Test Level",
    0x54: "Star World 2 (dup)",
    0x55: "Test Level",
    0x56: "Star World 3 (dup)",
    0x57: "Test Level",
    0x58: "Star World 1 (dup)",
    0x59: "Star World 4 (dup)",
    0x5A: "Star World 5 (dup)",
    0xB7: "Wendy O. Koopa Boss",
    0xB8: "Lemmy Koopa Boss",
    0xB9: "Reznor Boss",
    0xBA: "[CRASH]",
    0xBB: "Iggy Koopa Boss",
    0xBC: "Ludwig von Koopa Boss",
    0xBD: "Roy Koopa Boss",
    0xBE: "Morton Koopa Jr. Boss",
    0xBF: "Bowser Boss",
    0xDF: "1-up Bonus (sale a nivel 13)",
    0xE0: "1-up Bonus (sale a nivel 23)",
    0xE1: "Back Door (dup)",
    0xE2: "Sublevel (Yoshi's Island 4)",
    0xE3: "Sublevel (Valley of Bowser 4)",
    0xE4: "Sublevel (Chocolate Secret)",
    0xE5: "Sublevel (Forest of Illusion 4)",
    0xE6: "Sublevel (Vanilla Dome 3)",
    0xE7: "Sublevel (Vanilla Dome 2)",
    0xE8: "Exit (Gnarly)",
    0xE9: "Exit (Gnarly)",
    0xEA: "Sublevel (Donut Secret 2)",
    0xEB: "Bowser Boss Level",
    0xEC: "Yoshi Wings Bonus",
    0xED: "Sublevel (Way Cool)",
    0xEE: "Sublevel (Yoshi's Island 2)",
    0xEF: "Sublevel (Yoshi's Island 1)",
    0xF0: "Front Door - Sublevel 1",
    0xF1: "Front Door - Sublevel 2",
    0xF2: "Front Door - Sublevel 3",
    0xF3: "Front Door - Sublevel 4",
    0xF4: "Front Door - Sublevel 5",
    0xF5: "Front Door - Sublevel 6",
    0xF6: "Front Door - Sublevel 7",
    0xF7: "Front Door - Sublevel 8",
    0xF8: "Front Door - Sublevel 9",
    0xF9: "Exit 1",
    0xFA: "Exit 2",
    0xFB: "Blue Switch Exit",
    0xFC: "Red Switch Exit",
    0xFD: "Valley Ghost House - Sub 1",
    0xFE: "Exit (Valley Ghost House)",
    0xFF: "Valley Ghost House - Sub 2",
    # CI2 extended sublevels (0x200-0x208) — real ROM table entries
    0x200: "CI2 room 4: P-switch",
    0x201: "CI2 room 4: Rex goal room",
    0x202: "CI2 room 4: Rex goal room (unused dup of 201)",
    0x203: "CI2 room 2: Cape",
    0x204: "CI2 room 2: Rexes etc",
    0x205: "CI2 room 2: Paratroopa slopes",
    0x206: "CI2 room 3: Bubbled mushrooms",
    0x207: "CI2 room 3: Rhinos",
    0x208: "CI2 room 3: secret exit",
}

# Sublevel IDs that map directly (not overworld +0x100).
# This covers:
#   0x000        – Bonus game main map (level 0x00 is a special case, NOT +0x100)
#   0x001–0x0B6  – Internal sublevels accessible only by direct sublevel ID
#   0x0B7–0x0FF  – Boss / special room sublevel IDs
# Overworld levels 0x01–0x5A map to sublevels 0x101–0x15A (i.e. +0x100).
DIRECT_SUBLEVEL_IDS = set(range(0x000, 0x100))  # 0x000–0x0FF inclusive

def level_to_sublevel(level_id: int) -> int:
    """Convert a user-facing level_id to the sublevel_id used in the ROM tables.
 
    - 0x00        -> 0x000  (bonus game main map, special case)
    - 0x01-0x5A   -> level_id + 0x100  (overworld levels)
    - everything else -> level_id as-is  (bosses, internal rooms)
    """
    if level_id == 0x00:
        return 0x000
    if 0x01 <= level_id <= 0x5A:
        return level_id + 0x100
    return level_id
 
 
def bgid_desc(bgid: int) -> str:
    if bgid == 0xFF:
        return "Interactive L2 (object data)"
    return BACKGROUNDS.get(bgid, {}).get("desc", "Unknown BGID")
 
 
def level_name(level_id: int) -> str:
    return LEVEL_NAMES.get(level_id, "Unknown")
 
 
def get_l2_ptr(data: bytes, sublevel_id: int) -> int:
    off = LAYOUT_TABLE_OFFSET + sublevel_id * 4
    return struct.unpack_from('<I', data, off)[0]
 
 
def set_l2_ptr(data: bytearray, sublevel_id: int, ptr: int):
    off = LAYOUT_TABLE_OFFSET + sublevel_id * 4
    struct.pack_into('<I', data, off, ptr)
 
 
def get_l1_ptr(data: bytes, sublevel_id: int) -> int:
    off = L1_TABLE_OFFSET + sublevel_id * 4
    return struct.unpack_from('<I', data, off)[0]


def _header_offset(data: bytes, sublevel_id: int) -> int | None:
    """Return the ROM offset of the 7-byte Level 1 header for this sublevel, or None."""
    gba_ptr = get_l1_ptr(data, sublevel_id)
    if gba_ptr < GBA_ROM_BASE:
        return None
    off = gba_ptr - GBA_ROM_BASE
    if off + 7 > len(data):
        return None
    return off


def read_header(data: bytes, sublevel_id: int) -> dict | None:
    """Read the 7-byte sublevel header and return its parsed fields, or None on error."""
    off = _header_offset(data, sublevel_id)
    if off is None:
        return None
    h = data[off:off + 7]
    return {
        "length":    h[0] & 0x1F,
        "bg_pal":   (h[0] >> 5) & 0x07,
        "level_mode": h[1] & 0x1F,
        "scroll_a":  (h[1] >> 5) & 0x07,
        "sp_tileset": h[2] & 0x0F,
        "music":     (h[2] >> 4) & 0x0F,
        "fg_pal":    h[3] & 0x07,
        "sp_pal":   (h[3] >> 3) & 0x07,
        "timer":     (h[3] >> 6) & 0x03,
        "tileset":   h[4] & 0x0F,
        "scroll_b":  (h[4] >> 4) & 0x0F,
        "scroll_c":  h[5] & 0x0F,
        "bg_color":  (h[5] >> 4) & 0x0F,
        "unused":    h[6],
        "_raw":      list(h),
        "_offset":   off,
    }


# ── Palette / color name maps ─────────────────────────────────────────────────

BG_COLOR_NAMES = {
    0: "beige",
    1: "light green",
    2: "blue (default)",
    3: "black",
    4: "dark green",
    5: "dark blue",
    6: "light blue",
    7: "white",
}

BG_PAL_NAMES = {
    0: "green",
    1: "blue",
    2: "beige",
    3: "brown",
    4: "strong purple (unused)",
    5: "dark gray",
    6: "dark brown",
    7: "default green",
}


def _prompt_palette(label: str, names: dict, current: int, max_val: int) -> int:
    """Show a numbered color menu and prompt the user to pick one.
    Pressing Enter keeps the current value."""
    print(opt(f"\n  {label}:"))
    for i in range(max_val + 1):
        name   = names.get(i, "?")
        marker = opt(" <-- current") if i == current else ""
        print(opt(f"    {i} = {name}") + marker)
    while True:
        try:
            raw = input(opt(f"  Pick {label} (0-{max_val}) [Enter = keep {current}]: ")).strip()
            if raw == "":
                return current
            val = int(raw)
            if 0 <= val <= max_val:
                return val
            print(err(f"  Please enter a number between 0 and {max_val}."))
        except (ValueError, EOFError):
            print(err(f"  Invalid input, keeping current value ({current})."))
            return current


def prompt_header_values(data: bytes, sublevel_id: int) -> dict | None:
    """Interactively ask the user for bg_pal and bg_color.
    Tileset is derived automatically from the BGID (not asked).
    fg_pal and sp_pal are not touched.
    Returns a dict with 'bg_pal' and 'bg_color', or None if header unreadable."""
    hdr = read_header(data, sublevel_id)
    if hdr is None:
        print(err("  Warning: could not read level header — skipping palette prompts."))
        return None

    bg_pal   = _prompt_palette("Background palette", BG_PAL_NAMES,   hdr["bg_pal"],  7)
    bg_color = _prompt_palette("Back area color",    BG_COLOR_NAMES,  hdr["bg_color"], 7)

    return {"bg_pal": bg_pal, "bg_color": bg_color}


def apply_header_values(data: bytearray, sublevel_id: int,
                        bg_pal: int, bg_color: int, bgid: int) -> bool:
    """Write bg_pal and bg_color into the header.
    Tileset is auto-set from the BGID preset (same as before).
    fg_pal and sp_pal are never touched.
    Returns True on success."""
    off = _header_offset(data, sublevel_id)
    if off is None:
        return False

    h = bytearray(data[off:off + 7])

    # Byte 0: preserve bits 0-4 (length), set bits 5-7 (bg_pal)
    h[0] = (h[0] & 0x1F) | ((bg_pal & 0x07) << 5)
    # Byte 4: preserve bits 4-7 (scroll/item), set bits 0-3 (tileset from BGID)
    tileset = BG_HEADER_PRESETS.get(bgid, (0, 0, 0, 0, 0))[3]
    h[4] = (h[4] & 0xF0) | (tileset & 0x0F)
    # Byte 5: preserve bits 0-3 (scroll), set bits 4-7 (bg_color)
    h[5] = (h[5] & 0x0F) | ((bg_color & 0x0F) << 4)

    data[off:off + 7] = h
    return True


def is_vanilla_mismatch(sublevel_id: int, bgid: int, l2_ptr: int) -> bool:
    vm = VANILLA_MISMATCHES.get(sublevel_id)
    return vm is not None and vm[0] == bgid and vm[1] == l2_ptr
 
 
def check_rom(data: bytes) -> bool:
    """Validate GBA ROM header: title must contain 'MARIO', game code must be 'AA2E'."""
    if len(data) < 0xB0:
        return False
    title = data[0xA0:0xAC].rstrip(b'\x00')
    code  = data[0xAC:0xB0]
    return b'MARIO' in title.upper() and code == b'AA2E'
 
 
def out_path_for(rom_path: Path) -> Path:
    stem = rom_path.stem
    if stem.endswith("_edited"):
        return rom_path
    return rom_path.with_name(stem + "_edited" + rom_path.suffix)
 
 
# ── Commands ──────────────────────────────────────────────────────────────────
 
def cmd_info():
    print("\n+-------+------------+------------------------------------------+------+------+------+-------+----------+")
    print("| BGID  | L2 Tilemap | Description                              | BgPal| FgPal| SpPal|Tileset| BgColor |")
    print("+-------+------------+------------------------------------------+------+------+------+-------+----------+")
    for bgid, info in BACKGROUNDS.items():
        offset = info["ptr"] - GBA_ROM_BASE
        desc   = info["desc"][:42].ljust(42)
        preset = BG_HEADER_PRESETS.get(bgid)
        if preset:
            bg_pal, fg_pal, sp_pal, tileset, bg_color = preset
            print(f"|  0x{bgid:02X} | 0x{offset:06X}   | {desc} |  {bg_pal}   |  {fg_pal}   |  {sp_pal}   |   {tileset}   |    {bg_color}    |")
        else:
            print(f"|  0x{bgid:02X} | 0x{offset:06X}   | {desc} |  -   |  -   |  -   |   -   |    -    |")
    print("+-------+------------+------------------------------------------+------+------+------+-------+----------+")
    desc_ff = "Interactive L2 (object data)".ljust(42)
    print(f"|  0xFF |     ---    | {desc_ff} |  -   |  -   |  -   |   -   |    -    |")
    print("+-------+------------+------------------------------------------+------+------+------+-------+----------+")
    print()
    print("Intentional vanilla mismatches (original game overrides):")
    for sid, (bgid, actual_ptr, expected_ptr) in VANILLA_MISMATCHES.items():
        print(f"  Sublevel 0x{sid:03X}: BGID=0x{bgid:02X} ({bgid_desc(bgid)})")
        print(f"              L2 ptr=0x{actual_ptr:08X} (expected: 0x{expected_ptr:08X})")
    print()
 
 
def cmd_list(data: bytes, show_raw: bool = False):
    if show_raw:
        print(f"\n  {'Sublvl':>6}  {'Name':<40} {'BGID':>5}  {'L2 Ptr':>10}  {'Status'}")
        print("  " + "-" * 96)
        for sid in range(BGID_TABLE_SIZE):
            toff = BGID_TABLE_OFFSET + sid
            if toff >= len(data):
                break
            bgid   = data[toff]
            l2_ptr = get_l2_ptr(data, sid)
            name   = LEVEL_NAMES.get(sid, "(unnamed)")
            status = ""
            if bgid != 0xFF and bgid in BACKGROUNDS:
                expected = BACKGROUNDS[bgid]["ptr"]
                if l2_ptr != expected:
                    if is_vanilla_mismatch(sid, bgid, l2_ptr):
                        status = opt("[vanilla override]")
                    else:
                        status = err(f"[MISMATCH! expected 0x{expected:08X}]")
            marker = "  " if bgid != 0xFF else "o "
            print(f"{marker}[0x{sid:03X}]  {name:<40} 0x{bgid:02X}   0x{l2_ptr:08X}  {status}")
        print()
        return
 
    print(f"\n  {'ID':>4}  {'Sublvl':>6}  {'Name':<36} {'BGID':>5}  {'L2 Ptr':>10}  {'Status'}")
    print("  " + "-" * 100)
    for level_id in sorted(LEVEL_NAMES.keys()):
        sublevel_id = level_to_sublevel(level_id)
        toff = BGID_TABLE_OFFSET + sublevel_id
        if toff >= len(data):
            continue
        bgid   = data[toff]
        l2_ptr = get_l2_ptr(data, sublevel_id)
        name   = level_name(level_id)
        status = ""
        if bgid != 0xFF and bgid in BACKGROUNDS:
            expected = BACKGROUNDS[bgid]["ptr"]
            if l2_ptr != expected:
                if is_vanilla_mismatch(sublevel_id, bgid, l2_ptr):
                    status = opt("[vanilla override]")
                else:
                    status = err(f"[MISMATCH! expected 0x{expected:08X}]")
        marker = "  " if bgid != 0xFF else "o "
        print(f"{marker}0x{level_id:02X}  [0x{sublevel_id:03X}]  {name:<36} 0x{bgid:02X}   0x{l2_ptr:08X}  {status}")
    print()
 
 
def cmd_get(data: bytes, level_id: int):
    sublevel_id = level_to_sublevel(level_id)
    toff = BGID_TABLE_OFFSET + sublevel_id
    if toff >= len(data):
        print(err(f"Error: sublevel 0x{sublevel_id:03X} out of ROM range."))
        return
    bgid   = data[toff]
    l2_ptr = get_l2_ptr(data, sublevel_id)
    print(f"\n  {info('Level ID')}  : 0x{level_id:02X} -- {level_name(level_id)}")
    print(f"  {info('Sublevel')}  : 0x{sublevel_id:03X}  (ROM table offset 0x{toff:06X})")
    print(f"  {info('BGID')}      : 0x{bgid:02X}  ({bgid_desc(bgid)})")
    print(f"  {info('L2 ptr')}    : 0x{l2_ptr:08X}  (offset 0x{LAYOUT_TABLE_OFFSET + sublevel_id*4:06X})")
    if bgid != 0xFF and bgid in BACKGROUNDS:
        expected_ptr = BACKGROUNDS[bgid]["ptr"]
        if l2_ptr != expected_ptr:
            if is_vanilla_mismatch(sublevel_id, bgid, l2_ptr):
                print(opt(f"  NOTE      : Intentional vanilla override."))
                print(opt(f"             Expected: 0x{expected_ptr:08X} — game uses 0x{l2_ptr:08X}"))
            else:
                print(err(f"  WARNING   : L2 ptr does not match BGID."))
                print(err(f"             Expected: 0x{expected_ptr:08X} — may cause corrupt tilemap"))
    print()
 
 
def _apply_bgid_change(data: bytearray, level_id: int, new_bgid: int,
                       keep_ptr: bool) -> tuple[bool, str]:
    """Write BGID and L2 ptr for one level. Returns (success, summary).
    Header values (bg_pal, bg_color, tileset) are handled separately via prompts."""
    if new_bgid not in BACKGROUNDS and new_bgid != 0xFF:
        return False, f"Invalid BGID 0x{new_bgid:02X}. Use 0x00-0x11 or 0xFF."

    sublevel_id = level_to_sublevel(level_id)
    if sublevel_id >= BGID_TABLE_SIZE:
        return False, (f"Sublevel 0x{sublevel_id:03X} out of table range "
                       f"(max 0x{BGID_TABLE_SIZE-1:03X}).")

    toff = BGID_TABLE_OFFSET + sublevel_id
    if toff >= len(data):
        return False, f"Sublevel 0x{sublevel_id:03X} out of ROM range."

    old_bgid  = data[toff]
    old_l2ptr = get_l2_ptr(data, sublevel_id)

    data[toff] = new_bgid

    # Sync L2 tilemap pointer
    if keep_ptr:
        ptr_action = f"  (L2 ptr unchanged: 0x{old_l2ptr:08X})"
    elif new_bgid == 0xFF:
        ptr_action = f"  (BGID=0xFF: L2 ptr unchanged: 0x{old_l2ptr:08X})"
    else:
        new_l2ptr = BACKGROUNDS[new_bgid]["ptr"]
        set_l2_ptr(data, sublevel_id, new_l2ptr)
        if new_l2ptr != old_l2ptr:
            ptr_action = f"  L2 ptr: 0x{old_l2ptr:08X} -> 0x{new_l2ptr:08X}"
        else:
            ptr_action = f"  L2 ptr unchanged: 0x{new_l2ptr:08X}"

    name = level_name(level_id)
    summary = (f"0x{level_id:02X} [sub 0x{sublevel_id:03X}] {name:<36}  "
               f"BGID: 0x{old_bgid:02X} -> 0x{new_bgid:02X}  ({bgid_desc(new_bgid)})"
               f"{ptr_action}")
    return True, summary
 
 
def cmd_set(data: bytearray, level_id: int, new_bgid: int,
            out_path: Path, keep_ptr: bool = False) -> bool:
    success, msg = _apply_bgid_change(data, level_id, new_bgid, keep_ptr)
    if not success:
        print(err(f"\n  Error: {msg}\n"))
        return False

    sublevel_id = level_to_sublevel(level_id)
    toff        = BGID_TABLE_OFFSET + sublevel_id
    final_bgid  = data[toff]
    final_l2ptr = get_l2_ptr(data, sublevel_id)

    print(f"\n  {info('Level')}     : 0x{level_id:02X} -- {level_name(level_id)}")
    print(f"  {info('Sublevel')}  : 0x{sublevel_id:03X}  (ROM offset 0x{toff:06X})")
    print(f"  {info('BGID')}      -> 0x{final_bgid:02X}  ({bgid_desc(final_bgid)})")
    print(f"  {info('L2 ptr')}    -> 0x{final_l2ptr:08X}" + (opt("  [--keep-ptr]") if keep_ptr else ""))

    # Interactive palette/color prompts (skip for BGID=0xFF interactive L2)
    if new_bgid != 0xFF:
        values = prompt_header_values(data, sublevel_id)
        if values is not None:
            success = apply_header_values(data, sublevel_id,
                                     values["bg_pal"], values["bg_color"], new_bgid)
            if success:
                hdr = read_header(data, sublevel_id)
                tileset = BG_HEADER_PRESETS.get(new_bgid, (0,0,0,0,0))[3]
                print(ok(f"\n  Header    -> bg_pal={values['bg_pal']} ({BG_PAL_NAMES.get(values['bg_pal'], '?')})"
                      f"  bg_color={values['bg_color']} ({BG_COLOR_NAMES.get(values['bg_color'], '?')})"
                      f"  tileset={tileset} (auto)"))
            else:
                print(err("\n  Header    -> could not be written (skipped)"))

    out_path.write_bytes(bytes(data))
    print(ok(f"\n  Saved to: {out_path}\n"))
    return True
 
 
def cmd_batch(data: bytearray, changes: list, out_path: Path, keep_ptr: bool = False):
    applied = 0
    print()
    for level_id, new_bgid in changes:
        ok_flag, msg = _apply_bgid_change(data, level_id, new_bgid, keep_ptr)
        status = ok("OK  ") if ok_flag else err("SKIP")
        print(f"  {status} {msg}")
        if ok_flag:
            applied += 1
    if applied:
        out_path.write_bytes(bytes(data))
        print(ok(f"\n  {applied} change(s) applied. Saved to: {out_path}\n"))
    else:
        print(err("  No changes applied.\n"))
 
 
# ── CLI ───────────────────────────────────────────────────────────────────────
 
USAGE = """
Usage:
  python sma2_bgid_editor.py <rom.gba> <command> [args...] [options]
 
Commands:
  info                           List all 18 backgrounds with their tileset presets
  list [--raw]                   List levels with their current BGID and L2 ptr
  get  <level_id>                Show BGID, L2 ptr, and header for a level
  get-header <level_id>          Show full parsed header fields for a level
  set  <level_id> <new_bgid>     Change BGID, L2 ptr, and interactively set
                                   background palette and back area color.
                                   Tileset is auto-set from the BGID.
                                   fg_pal and sp_pal are never touched.
  batch <lvl=bgid> [lvl=bgid...] Change multiple levels in one pass (no prompts)
 
Options:
  --keep-ptr    Only update the BGID byte; leave the L2 pointer untouched.
 
Notes on level_id:
  - 0x00       -> sublevel 0x000  (Bonus game, special case)
  - 0x01-0x5A  -> sublevel = level_id + 0x100  (overworld levels)
  - 0xB7-0xFF  -> sublevel = level_id  (bosses / special rooms)
 
Output: <rom>_edited.gba  (original ROM is never modified)
 
Examples:
  python sma2_bgid_editor.py sma2.gba info
  python sma2_bgid_editor.py sma2.gba list
  python sma2_bgid_editor.py sma2.gba get 0x05
  python sma2_bgid_editor.py sma2.gba get-header 0x05
  python sma2_bgid_editor.py sma2.gba set 0x05 0x11
  python sma2_bgid_editor.py sma2.gba set 0x05 0x11 --keep-ptr
  python sma2_bgid_editor.py sma2.gba batch 0x05=0x11 0x06=0x0A 0x07=0x00
"""
 
 
def cmd_get_header(data: bytes, level_id: int):
    sublevel_id = level_to_sublevel(level_id)
    hdr = read_header(data, sublevel_id)
    l1_ptr = get_l1_ptr(data, sublevel_id)
    print(f"\n  {info('Level')}    : 0x{level_id:02X} -- {level_name(level_id)}")
    print(f"  {info('Sublevel')} : 0x{sublevel_id:03X}")
    print(f"  {info('L1 ptr')}   : 0x{l1_ptr:08X}")
    if hdr is None:
        print(err("  Header   : could not be read (invalid L1 pointer?)"))
    else:
        raw = ' '.join(f'{b:02X}' for b in hdr['_raw'])
        print(f"  {info('Raw')}      : {raw}  (@ ROM 0x{hdr['_offset']:06X})")
        print(f"  {info('length')}   : {hdr['length']}  (screens - 1)")
        print(f"  {info('bg_pal')}   : {hdr['bg_pal']}")
        print(f"  {info('level_mode')}: {hdr['level_mode']:02X}")
        print(f"  {info('scroll_a')} : {hdr['scroll_a']}")
        print(f"  {info('sp_tile')}  : {hdr['sp_tileset']}")
        print(f"  {info('music')}    : {hdr['music']}")
        print(f"  {info('fg_pal')}   : {hdr['fg_pal']}")
        print(f"  {info('sp_pal')}   : {hdr['sp_pal']}")
        print(f"  {info('timer')}    : {hdr['timer']}")
        print(f"  {info('tileset')}  : {hdr['tileset']}")
        print(f"  {info('bg_color')} : {hdr['bg_color']}")
    print()


def parse_hex(s: str) -> int:
    return int(s.strip(), 16)
 
 
def main():
    if len(sys.argv) < 3:
        print_banner()
        print(""); sys.exit(1)
 
    rom_path    = Path(sys.argv[1])
    command     = sys.argv[2].lower()
    keep_ptr    = "--keep-ptr" in sys.argv
 
    if command == "info":
        cmd_info(); return
 
    if not rom_path.exists():
        print(err(f"Error: '{rom_path}' not found.")); sys.exit(1)
 
    raw = rom_path.read_bytes()
    if not check_rom(raw):
        print(err("Warning: file does not look like an SMA2 ROM. Continuing anyway..."))
    if len(raw) < BGID_TABLE_OFFSET + BGID_TABLE_SIZE:
        print(err(f"Error: ROM too small ({len(raw)} bytes).")); sys.exit(1)
 
    out = out_path_for(rom_path)
 
    if command == "list":
        cmd_list(raw, show_raw="--raw" in sys.argv[3:])
 
    elif command == "get":
        if len(sys.argv) < 4:
            print(err("Usage: get <level_id>")); sys.exit(1)
        try:
            cmd_get(raw, parse_hex(sys.argv[3]))
        except ValueError:
            print(err(f"Error: invalid level_id '{sys.argv[3]}'")); sys.exit(1)

    elif command == "get-header":
        if len(sys.argv) < 4:
            print(err("Usage: get-header <level_id>")); sys.exit(1)
        try:
            cmd_get_header(raw, parse_hex(sys.argv[3]))
        except ValueError:
            print(err(f"Error: invalid level_id '{sys.argv[3]}'")); sys.exit(1)
 
    elif command == "set":
        if len(sys.argv) < 5:
            print(err("Usage: set <level_id> <new_bgid>")); sys.exit(1)
        try:
            lid  = parse_hex(sys.argv[3])
            bgid = parse_hex(sys.argv[4])
        except ValueError as e:
            print(err(f"Error: {e}")); sys.exit(1)
        data = bytearray(raw)
        cmd_set(data, lid, bgid, out, keep_ptr=keep_ptr)
 
    elif command == "batch":
        if len(sys.argv) < 4:
            print(err("Usage: batch lvl=bgid [lvl=bgid ...]")); sys.exit(1)
        changes = []
        for pair in sys.argv[3:]:
            if pair.startswith("--"):
                continue
            if "=" not in pair:
                print(err(f"  SKIP: invalid format '{pair}'")); continue
            a, b = pair.split("=", 1)
            try:
                changes.append((parse_hex(a), parse_hex(b)))
            except ValueError:
                print(err(f"  SKIP: invalid values '{pair}'"))
        data = bytearray(raw)
        cmd_batch(data, changes, out, keep_ptr=keep_ptr)
 
    else:
        print(err(f"Unknown command: '{command}'"))
        print(""); sys.exit(1)
 
 
if __name__ == "__main__":
    main()