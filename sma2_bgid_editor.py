"""
SMA2 (Super Mario Advance 2) - Layer 2 / Background ID Editor by Oquendo
=========================================================================================
Reads and modifies the Layer 2 BGID for each sublevel in the ROM.
When changing a BGID, also updates the L2 tilemap pointer AND the
level header (BG palette, FG palette, sprite palette, tileset ID,
BG color) to match the new background automatically.
Use --keep-ptr to skip the L2 pointer update.

ROM tables (verified against ROM map and real edits):
  BGID table   : 0x0F3B38 - 0x0F3D40  (0x209 entries, 1 byte each)
                 GBA: 0x080F3B38 | sublevel IDs 0x000-0x208
                 Spot-check: sublevel 0x105 -> offset 0x0F3C3D
  Layout ptrs  : 0x0F2AF0 - 0x0F3313  (0x209 entries, 4 bytes each)
                 GBA: 0x080F2AF0 | same sublevel index
                 Spot-check: sublevel 0x105 -> offset 0x0F2F04

Intentional vanilla mismatches (original game overrides):
  Sublevel 0x108: BGID=0x0A, L2 ptr -> YI Mountains tilemap instead of Beta Mountains
  Sublevel 0x112: BGID=0x00, L2 ptr -> Chocolate Island tilemap instead of YI Mountains
  The script flags these on read but overwrites them on write
  (use --keep-ptr to preserve a custom pointer).
"""

import sys
import struct
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

class C:
    SUCCESS = "\033[38;2;180;230;210m"   # pastel mint / teal-green
    INFO    = "\033[38;2;255;200;220m"   # pastel rose / pink
    OPTION  = "\033[38;2;255;235;150m"   # pastel golden yellow
    ERROR   = "\033[38;2;255;160;130m"   # pastel coral / salmon
    HEADER  = "\033[38;2;150;220;255m"   # pastel sky blue
    RESET   = "\033[0m"

def ok(msg):   return f"{C.SUCCESS}{msg}{C.RESET}"
def info(msg): return f"{C.INFO}{msg}{C.RESET}"
def opt(msg):  return f"{C.OPTION}{msg}{C.RESET}"
def err(msg):  return f"{C.ERROR}{msg}{C.RESET}"
def hdr(msg):  return f"{C.HEADER}{msg}{C.RESET}"


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
    print(f"  {ok('Version')} : v0.3          {info('Author')} : Oquendo")
    print(f"  {ok('ROM')}     : Super Mario Advance 2 (GBA)")
    print(border)
    print(f"""
  {hdr('Quick start')} — Change background of sublevel 0x105 (Yoshi's Island 1):

    {opt('1.')} List all available backgrounds and their IDs:
       {C.SUCCESS}python sma2_bgid_editor.py sma2.gba info{C.RESET}

    {opt('2.')} Check current background of sublevel 0x105:
       {C.SUCCESS}python sma2_bgid_editor.py sma2.gba get 0x105{C.RESET}

    {opt('3.')} Set a new background (e.g. Castle 3 = BGID 0x11):
       {C.SUCCESS}python sma2_bgid_editor.py sma2.gba set 0x105 0x11{C.RESET}
       {C.INFO}→ Edits sma2.gba directly in-place{C.RESET}

    {opt('4.')} Batch-edit multiple sublevels at once:
       {C.SUCCESS}python sma2_bgid_editor.py sma2.gba batch 0x105=0x11 0x106=0x0D{C.RESET}
""")
    print(border)
    print()


GBA_ROM_BASE      = 0x08000000

BGID_TABLE_ADDR   = 0x080F3B38
BGID_TABLE_OFFSET = BGID_TABLE_ADDR - GBA_ROM_BASE
BGID_TABLE_SIZE   = 0x209

LAYOUT_TABLE_ADDR   = 0x080F2AF0
LAYOUT_TABLE_OFFSET = LAYOUT_TABLE_ADDR - GBA_ROM_BASE

L1_TABLE_ADDR   = 0x080F22CC
L1_TABLE_OFFSET = L1_TABLE_ADDR - GBA_ROM_BASE

VANILLA_MISMATCHES = {
    0x108: (0x0A, 0x080E42D0, 0x080E5190),
    0x112: (0x00, 0x080E4929, 0x080E42D0),
}

BG_HEADER_PRESETS = {
    0x00: (    7,      0,      0,      0,       0   ),  # YI Mountains
    0x01: (    4,      2,      3,      9,       8   ),  # Aquatic
    0x02: (    0,      0,      0,      0,       5   ),  # Athletic / Low Clouds
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
    # Keys are full sublevel IDs (0x000–0x208).
    0x000: "Bonus game (no-Yoshi intro slot)",
    0x001: "Infinite Bonus game",
    0x002: "Vanilla Secret 2",
    0x003: "Vanilla Secret 3",
    0x004: "Top Secret Area",
    0x005: "Donut Ghost House",
    0x006: "Donut Plains 3",
    0x007: "Donut Plains 4",
    0x008: "#2 Morton's Castle",
    0x009: "Green Switch Palace",
    0x00A: "Donut Plains 2",
    0x00B: "Donut Secret 1",
    0x00C: "Vanilla Fortress",
    0x00D: "Butter Bridge 1",
    0x00E: "Butter Bridge 2",
    0x00F: "#4 Ludwig's Castle",
    0x010: "Cheese Bridge Area",
    0x011: "Cookie Mountain",
    0x012: "Soda Lake",
    0x013: "Test Level",
    0x014: "Donut Secret House",
    0x015: "Yellow Switch Palace",
    0x016: "Donut Plains 1",
    0x017: "Donut Plains 1 (Duplicate)",
    0x018: "Donut Plains 1 (Duplicate 2)",
    0x019: "Sunken Ghost Ship",
    0x01A: "Test Level 2",
    0x01B: "#6 Wendy's Castle",
    0x01C: "Chocolate Fortress",
    0x01D: "Chocolate Island 5",
    0x01E: "Chocolate Island 4",
    0x01F: "Test Level 3",
    0x020: "Forest Fortress",
    0x021: "#5 Roy's Castle",
    0x022: "Choco-Ghost House",
    0x023: "Chocolate Island 1",
    0x024: "Chocolate Island 3",
    0x025: "Chocolate Island 2",

    0x026: "",
    0x027: "",
    0x028: "",
    0x029: "",
    0x02A: "",
    0x02B: "",
    0x02C: "",
    0x02D: "",
    0x02E: "",
    0x02F: "",
    0x030: "",
    0x031: "",
    0x032: "",
    0x033: "",
    0x034: "",
    0x035: "",
    0x036: "",
    0x037: "",
    0x038: "",
    0x039: "",
    0x03A: "",
    0x03B: "",
    0x03C: "",
    0x03D: "",
    0x03E: "",
    0x03F: "",
    0x040: "",
    0x041: "",
    0x042: "",
    0x043: "",
    0x044: "",
    0x045: "",
    0x046: "",
    0x047: "",
    0x048: "",
    0x049: "",
    0x04A: "",
    0x04B: "",
    0x04C: "",
    0x04D: "",
    0x04E: "",
    0x04F: "",
    0x050: "",
    0x051: "",
    0x052: "",
    0x053: "",
    0x054: "",
    0x055: "",
    0x056: "",
    0x057: "",
    0x058: "",
    0x059: "",
    0x05A: "",
    0x05B: "",
    0x05C: "",
    0x05D: "",
    0x05E: "",
    0x05F: "",
    0x060: "",
    0x061: "",
    0x062: "",
    0x063: "",
    0x064: "",
    0x065: "",
    0x066: "",
    0x067: "",
    0x068: "",
    0x069: "",
    0x06A: "",
    0x06B: "",
    0x06C: "",
    0x06D: "",
    0x06E: "",
    0x06F: "",
    0x070: "",
    0x071: "",
    0x072: "",
    0x073: "",
    0x074: "",
    0x075: "",
    0x076: "",
    0x077: "",
    0x078: "",
    0x079: "",
    0x07A: "",
    0x07B: "",
    0x07C: "",
    0x07D: "",
    0x07E: "",
    0x07F: "",
    0x080: "",
    0x081: "",
    0x082: "",
    0x083: "",
    0x084: "",
    0x085: "",
    0x086: "",
    0x087: "",
    0x088: "",
    0x089: "",
    0x08A: "",
    0x08B: "",
    0x08C: "",
    0x08D: "",
    0x08E: "",
    0x08F: "",
    0x090: "",
    0x091: "",
    0x092: "",
    0x093: "",
    0x094: "",
    0x095: "",
    0x096: "",
    0x097: "",
    0x098: "",
    0x099: "",
    0x09A: "",
    0x09B: "",
    0x09C: "",
    0x09D: "",
    0x09E: "",
    0x09F: "",
    0x0A0: "",
    0x0A1: "",
    0x0A2: "",
    0x0A3: "",
    0x0A4: "",
    0x0A5: "",
    0x0A6: "",
    0x0A7: "",
    0x0A8: "",
    0x0A9: "",
    0x0AA: "",
    0x0AB: "",
    0x0AC: "",
    0x0AD: "",
    0x0AE: "",
    0x0AF: "",
    0x0B0: "",
    0x0B1: "",
    0x0B2: "",
    0x0B3: "",
    0x0B4: "",
    0x0B5: "",
    0x0B6: "",
    0x0B7: "Wendy O. Koopa Boss",
    0x0B8: "Lemmy Koopa Boss",
    0x0B9: "Reznor Boss",
    0x0BA: "[CRASH]",
    0x0BB: "Iggy Koopa Boss",
    0x0BC: "Ludwig von Koopa Boss",
    0x0BD: "Roy Koopa Boss",
    0x0BE: "Morton Koopa Jr. Boss",
    0x0BF: "Bowser Boss",

    0x0C0: "BONUS STAGE (CI5)",
    0x0C1: "",
    0x0C2: "Secret Stage (CBA)",
    0x0C3: "Secret Stage (CI5)",
    0x0C4: "",
    0x0C5: "Secret Stage (DS1)",
    0x0C6: "Secret Stage (DP4)",
    0x0C7: "Ghost House Exit",
    0x0C8: "Welcome to Dinosaourland",
    0x0C9: "Big Mountains Exit",
    0x0CA: "Title screen",
    0x0CB: "Flying Yoshi's Bonus Stage",
    0x0CC: "Green Switch Palace Room",
    0x0CD: "Yellow Switch Palace Room",
    0x0CE: "Big Clouds Exit",
    0x0CF: "",
    0x0D0: "CI2 room 4 4+: P-switch",
    0x0D1: "CI2 room 3 0-229: Bubbled mushrooms",
    0x0D2: "CI2 room 2 20+: Cape",
    0x0D3: "",
    0x0D4: "DP4 Secret Stage",
    0x0D5: "Wendy's Boss Room",
    0x0D6: "Castle Before Wendy's Boss Room",
    0x0D7: "",
    0x0D8: "CI3 Bonus Room",
    0x0D9: "Vanilla Secret 1 Bonus Room",
    0x0DA: "",
    0x0DB: "",
    0x0DC: "",
    0x0DD: "",
    0x0DE: "",
    0x0DF: "1-up Bonus (sale a nivel 13)",
    0x0E0: "1-up Bonus (sale a nivel 23)",
    0x0E1: "Back Door (dup)",
    0x0E2: "Sublevel (Yoshi's Island 4)",
    0x0E3: "Sublevel (Valley of Bowser 4)",
    0x0E4: "Sublevel (Chocolate Secret)",
    0x0E5: "Sublevel (Forest of Illusion 4)",
    0x0E6: "Sublevel (Vanilla Dome 3)",
    0x0E7: "Sublevel (Vanilla Dome 2)",
    0x0E8: "Exit (Gnarly)",
    0x0E9: "Exit (Gnarly)",
    0x0EA: "Sublevel (Donut Secret 2)",
    0x0EB: "Bowser Boss Level",
    0x0EC: "Yoshi Wings Bonus",
    0x0ED: "Sublevel (Way Cool)",
    0x0EE: "Sublevel (Yoshi's Island 2)",
    0x0EF: "Sublevel (Yoshi's Island 1)",
    0x0F0: "Front Door - Sublevel 1",
    0x0F1: "Front Door - Sublevel 2",
    0x0F2: "Front Door - Sublevel 3",
    0x0F3: "Front Door - Sublevel 4",
    0x0F4: "Front Door - Sublevel 5",
    0x0F5: "Front Door - Sublevel 6",
    0x0F6: "Front Door - Sublevel 7",
    0x0F7: "Front Door - Sublevel 8",
    0x0F8: "Front Door - Sublevel 9",
    0x0F9: "Exit 1",
    0x0FA: "Exit 2",
    0x0FB: "Blue Switch Exit",
    0x0FC: "Red Switch Exit",
    0x0FD: "Valley Ghost House - Sub 1",
    0x0FE: "Exit (Valley Ghost House)",
    0x0FF: "Valley Ghost House - Sub 2",

    0x100: "Bonus game, submaps",
    0x101: "#1 Iggy's Castle",
    0x102: "Yoshi's Island 4",
    0x103: "Yoshi's Island 3",
    0x104: "Yoshi's House",
    0x105: "Yoshi's Island 1",
    0x106: "Yoshi's Island 2",
    0x107: "Vanilla Ghost House",
    0x108: "Intro Cutscene",
    0x109: "Vanilla Secret 1",
    0x10A: "Vanilla Dome 3",
    0x10B: "Donut Secret 2",
    0x10C: "Test Level 4",
    0x10D: "Front Door (Bowser's Castle)",
    0x10E: "Back Door (Bowser's Castle)",
    0x10F: "Valley of Bowser 4",
    0x110: "#7 Larry's Castle",
    0x111: "Valley Fortress",
    0x112: "Test Level 5",
    0x113: "Valley of Bowser 3",
    0x114: "Valley Ghost House",
    0x115: "Valley of Bowser 2",
    0x116: "Valley of Bowser 1",
    0x117: "Chocolate Secret",
    0x118: "Vanilla Dome 2",
    0x119: "Vanilla Dome 4",
    0x11A: "Vanilla Dome 1",
    0x11B: "Red Switch Palace",
    0x11C: "#3 Lemmy's Switch Palace",
    0x11D: "Forest Ghost House",
    0x11E: "Forest of Illusion 1",
    0x11F: "Forest of Illusion 4",
    0x120: "Forest of Illusion 2",
    0x121: "Blue Switch Palace",
    0x122: "Forest Secret Area",
    0x123: "Forest of Illusion 3",
    0x124: "Test Level 6",
    0x125: "Funky",
    0x126: "Outrageous",
    0x127: "Mondo",
    0x128: "Groovy",
    0x129: "Test Level 7",
    0x12A: "Gnarly",
    0x12B: "Tubular",
    0x12C: "Way Cool",
    0x12D: "Awesome",
    0x12E: "Test Level 8",
    0x12F: "Test Level 9",
    0x130: "Star World 2",
    0x131: "Test Level 10",
    0x132: "Star World 3",
    0x133: "Test Level 11",
    0x134: "Star World 1",
    0x135: "Star World 4",
    0x136: "Star World 5",
    0x137: "Test Level 12",
    0x138: "Test Level 13",
    0x139: "Test Level 14",
    0x13A: "Test Level 15",
    0x13B: "Test Level 16",
    0x13C: "",
    0x13D: "",
    0x13E: "",
    0x13F: "",
    0x140: "",
    0x141: "",
    0x142: "",
    0x143: "",
    0x144: "",
    0x145: "",
    0x146: "",
    0x147: "",
    0x148: "",
    0x149: "",
    0x14A: "",
    0x14B: "",
    0x14C: "",
    0x14D: "",
    0x14E: "",
    0x14F: "",
    0x150: "",
    0x151: "",
    0x152: "",
    0x153: "",
    0x154: "",
    0x155: "",
    0x156: "",
    0x157: "",
    0x158: "",
    0x159: "",
    0x15A: "",

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


def level_name(sublevel_id: int) -> str:
    name = LEVEL_NAMES.get(sublevel_id, "")
    if name:
        return name
    return f"(sublevel 0x{sublevel_id:03X})"


def bgid_desc(bgid: int) -> str:
    if bgid == 0xFF:
        return "Interactive L2 (object data)"
    return BACKGROUNDS.get(bgid, {}).get("desc", "Unknown BGID")


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
    gba_ptr = get_l1_ptr(data, sublevel_id)
    if gba_ptr < GBA_ROM_BASE:
        return None
    off = gba_ptr - GBA_ROM_BASE
    if off + 7 > len(data):
        return None
    return off


def read_header(data: bytes, sublevel_id: int) -> dict | None:
    off = _header_offset(data, sublevel_id)
    if off is None:
        return None
    h = data[off:off + 7]
    return {
        "length":      h[0] & 0x1F,
        "bg_pal":     (h[0] >> 5) & 0x07,
        "level_mode":   h[1] & 0x1F,
        "scroll_a":   (h[1] >> 5) & 0x07,
        "sp_tileset":  h[2] & 0x0F,
        "music":      (h[2] >> 4) & 0x0F,
        "fg_pal":      h[3] & 0x07,
        "sp_pal":     (h[3] >> 3) & 0x07,
        "timer":       (h[3] >> 6) & 0x03,
        "tileset":     h[4] & 0x0F,
        "scroll_b":   (h[4] >> 4) & 0x0F,
        "scroll_c":    h[5] & 0x0F,
        "bg_color":   (h[5] >> 4) & 0x0F,
        "unused":      h[6],
        "_raw":        list(h),
        "_offset":     off,
    }


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
    hdr = read_header(data, sublevel_id)
    if hdr is None:
        print(err("  Warning: could not read level header — skipping palette prompts."))
        return None

    bg_pal    = _prompt_palette("Background palette", BG_PAL_NAMES,    hdr["bg_pal"],   7)
    bg_color  = _prompt_palette("Back area color",    BG_COLOR_NAMES,  hdr["bg_color"], 7)

    return {"bg_pal": bg_pal, "bg_color": bg_color}


def apply_header_values(data: bytearray, sublevel_id: int,
                        bg_pal: int, bg_color: int, bgid: int) -> bool:
    off = _header_offset(data, sublevel_id)
    if off is None:
        return False

    h = bytearray(data[off:off + 7])

    h[0] = (h[0] & 0x1F) | ((bg_pal & 0x07) << 5)
    tileset = BG_HEADER_PRESETS.get(bgid, (0, 0, 0, 0, 0))[3]
    h[4] = (h[4] & 0xF0) | (tileset & 0x0F)
    h[5] = (h[5] & 0x0F) | ((bg_color & 0x0F) << 4)

    data[off:off + 7] = h
    return True


def is_vanilla_mismatch(sublevel_id: int, bgid: int, l2_ptr: int) -> bool:
    vm = VANILLA_MISMATCHES.get(sublevel_id)
    return vm is not None and vm[0] == bgid and vm[1] == l2_ptr


def check_rom(data: bytes) -> bool:
    if len(data) < 0xB0:
        return False
    title = data[0xA0:0xAC].rstrip(b'\x00')
    code  = data[0xAC:0xB0]
    return b'MARIO' in title.upper() and code == b'AA2E'


def out_path_for(rom_path: Path) -> Path:
    return rom_path


def cmd_info():
    print("\n  +-------+------------+------------------------------------------+------+------+------+-------+----------+")
    print("  | BGID  | L2 Tilemap | Description                              | BgPal| FgPal| SpPal|Tileset| BgColor |")
    print("  +-------+------------+------------------------------------------+------+------+------+-------+----------+")
    for bgid, info in BACKGROUNDS.items():
        offset = info["ptr"] - GBA_ROM_BASE
        desc   = info["desc"][:42].ljust(42)
        preset = BG_HEADER_PRESETS.get(bgid)
        if preset:
            bg_pal, fg_pal, sp_pal, tileset, bg_color = preset
            print(f"  |  0x{bgid:02X} | 0x{offset:06X}   | {desc} |  {bg_pal}   |  {fg_pal}   |  {sp_pal}   |   {tileset}   |    {bg_color}    |")
        else:
            print(f"  |  0x{bgid:02X} | 0x{offset:06X}   | {desc} |  -   |  -   |  -   |   -   |    -    |")
    print("  +-------+------------+------------------------------------------+------+------+------+-------+----------+")
    desc_ff = "Interactive L2 (object data)".ljust(42)
    print(f"  |  0xFF |     ---    | {desc_ff} |  -   |  -   |  -   |   -   |    -    |")
    print("  +-------+------------+------------------------------------------+------+------+------+-------+----------+")
    print()
    print("  Intentional vanilla mismatches (original game overrides):")
    for sid, (bgid, actual_ptr, expected_ptr) in VANILLA_MISMATCHES.items():
        print(f"    Sublevel 0x{sid:03X}: BGID=0x{bgid:02X} ({bgid_desc(bgid)})")
        print(f"                L2 ptr=0x{actual_ptr:08X} (expected: 0x{expected_ptr:08X})")
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

    print(f"\n  {'Sublvl':>6}  {'Name':<36} {'BGID':>5}  {'L2 Ptr':>10}  {'Status'}")
    print("  " + "-" * 90)
    for sublevel_id in sorted(LEVEL_NAMES.keys()):
        toff = BGID_TABLE_OFFSET + sublevel_id
        if toff >= len(data):
            continue
        bgid   = data[toff]
        l2_ptr = get_l2_ptr(data, sublevel_id)
        name   = level_name(sublevel_id)
        status = ""
        if bgid != 0xFF and bgid in BACKGROUNDS:
            expected = BACKGROUNDS[bgid]["ptr"]
            if l2_ptr != expected:
                if is_vanilla_mismatch(sublevel_id, bgid, l2_ptr):
                    status = opt("[vanilla override]")
                else:
                    status = err(f"[MISMATCH! expected 0x{expected:08X}]")
        marker = "  " if bgid != 0xFF else "o "
        print(f"{marker}0x{sublevel_id:03X}  {name:<36} 0x{bgid:02X}   0x{l2_ptr:08X}  {status}")
    print()


def cmd_get(data: bytes, sublevel_id: int):
    toff = BGID_TABLE_OFFSET + sublevel_id
    if toff >= len(data):
        print(err(f"\n  Error: sublevel 0x{sublevel_id:03X} out of ROM range.\n"))
        return
    bgid   = data[toff]
    l2_ptr = get_l2_ptr(data, sublevel_id)
    print(f"\n  {hdr('─' * 54)}")
    print(f"  {info('Sublevel')} : 0x{sublevel_id:03X}  ({level_name(sublevel_id)})")
    print(f"  {info('L1 ptr')}   : 0x{get_l1_ptr(data, sublevel_id):08X}  (ROM 0x{toff:06X})")
    print(f"  {info('BGID')}      : 0x{bgid:02X}  ({bgid_desc(bgid)})")
    print(f"  {info('L2 ptr')}    : 0x{l2_ptr:08X}")
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


def _apply_bgid_change(data: bytearray, sublevel_id: int, new_bgid: int,
                       keep_ptr: bool) -> tuple[bool, str]:
    if new_bgid not in BACKGROUNDS and new_bgid != 0xFF:
        return False, f"Invalid BGID 0x{new_bgid:02X}. Use 0x00-0x11 or 0xFF."

    if sublevel_id >= BGID_TABLE_SIZE:
        return False, (f"Sublevel 0x{sublevel_id:03X} out of table range "
                       f"(max 0x{BGID_TABLE_SIZE-1:03X}).")

    toff = BGID_TABLE_OFFSET + sublevel_id
    if toff >= len(data):
        return False, f"Sublevel 0x{sublevel_id:03X} out of ROM range."

    old_bgid  = data[toff]
    old_l2ptr = get_l2_ptr(data, sublevel_id)

    data[toff] = new_bgid

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

    name = level_name(sublevel_id)
    summary = (f"0x{sublevel_id:03X}  {name:<36}  "
               f"BGID: 0x{old_bgid:02X} -> 0x{new_bgid:02X}  ({bgid_desc(new_bgid)})"
               f"{ptr_action}")
    return True, summary


def cmd_set(data: bytearray, sublevel_id: int, new_bgid: int,
            out_path: Path, keep_ptr: bool = False) -> bool:
    success, msg = _apply_bgid_change(data, sublevel_id, new_bgid, keep_ptr)
    if not success:
        print(err(f"\n  Error: {msg}\n"))
        return False

    toff        = BGID_TABLE_OFFSET + sublevel_id
    final_bgid  = data[toff]
    final_l2ptr = get_l2_ptr(data, sublevel_id)

    print(f"\n  {ok('✓')} Sublevel 0x{sublevel_id:03X}  ({level_name(sublevel_id)})")
    print(f"    {info('BGID')}      -> 0x{final_bgid:02X}  ({bgid_desc(final_bgid)})")
    print(f"    {info('L2 ptr')}    -> 0x{final_l2ptr:08X}" + (opt("  [--keep-ptr]") if keep_ptr else ""))

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
    print(ok(f"\n  Modified in-place: {out_path}\n"))
    return True


def cmd_batch(data: bytearray, changes: list, out_path: Path, keep_ptr: bool = False):
    applied = 0
    print()
    for sublevel_id, new_bgid in changes:
        ok_flag, msg = _apply_bgid_change(data, sublevel_id, new_bgid, keep_ptr)
        status = ok("OK  ") if ok_flag else err("SKIP")
        print(f"  {status} {msg}")
        if ok_flag:
            applied += 1
    if applied:
        out_path.write_bytes(bytes(data))
        print(ok(f"\n  {applied} change(s) applied. Modified in-place: {out_path}\n"))
    else:
        print(err("  No changes applied.\n"))


def cmd_get_header(data: bytes, sublevel_id: int):
    hdr = read_header(data, sublevel_id)
    l1_ptr = get_l1_ptr(data, sublevel_id)
    print(f"\n  {hdr('─' * 54)}")
    print(f"  {info('Sublevel')} : 0x{sublevel_id:03X}  ({level_name(sublevel_id)})")
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


def print_advanced_help():
    border = f"{C.INFO}  {'─' * 52}{C.RESET}"
    print(f"""
{border}
  {hdr('Commands')}
{border}

  {info('info')}
     List all 18 backgrounds with their tileset presets.
     {C.SUCCESS}python sma2_bgid_editor.py sma2.gba info{C.RESET}

  {info('list [--raw]')}
     List all named sublevels with their current BGID and L2 ptr.
     {C.SUCCESS}python sma2_bgid_editor.py sma2.gba list{C.RESET}
     {C.HEADER}→ Shows only named sublevels (those with a known name).{C.RESET}
     {C.SUCCESS}python sma2_bgid_editor.py sma2.gba list --raw{C.RESET}
     {C.HEADER}→ Dumps all 521 sublevel slots (0x000–0x208), including unnamed.{C.RESET}

  {info('get <sublevel_id>')}
     Show BGID, L2 ptr, and header info for a single sublevel.
     {C.SUCCESS}python sma2_bgid_editor.py sma2.gba get 0x105{C.RESET}
     {C.HEADER}→ Shows BGID, L2 pointer, and flags mismatches.{C.RESET}

  {info('get-header <sublevel_id>')}
     Show full parsed 7-byte header fields for a sublevel.
     {C.SUCCESS}python sma2_bgid_editor.py sma2.gba get-header 0x105{C.RESET}
     {C.HEADER}→ Shows length, bg_pal, level_mode, tileset, bg_color, etc.{C.RESET}

  {info('set <sublevel_id> <new_bgid> [--keep-ptr]')}
     Change BGID and L2 pointer, interactively set palette and color.
     {C.SUCCESS}python sma2_bgid_editor.py sma2.gba set 0x105 0x11{C.RESET}
     {C.HEADER}→ Changes sublevel 0x105 (Yoshi's Island 1) to Castle 3 background.{C.RESET}
     {C.HEADER}→ Prompts for background palette and back area color.{C.RESET}
     {C.SUCCESS}python sma2_bgid_editor.py sma2.gba set 0x105 0x11 --keep-ptr{C.RESET}
     {C.HEADER}→ Same but preserves the existing L2 pointer.{C.RESET}

  {info('batch <sub=bgid> [sub=bgid...] [--keep-ptr]')}
     Change multiple sublevels in one pass. No interactive prompts.
     {C.SUCCESS}python sma2_bgid_editor.py sma2.gba batch 0x105=0x11 0x106=0x0D{C.RESET}
     {C.HEADER}→ Changes multiple sublevels at once.{C.RESET}

{border}
  {info('Options')}
{border}

  {opt('--keep-ptr')}
     Only update the BGID byte; leave the L2 tilemap pointer untouched.
     Useful to replicate intentional vanilla overrides.

{border}
  {info('Background Palette')}
{border}

  0 = green       4 = strong purple (unused)
  1 = blue        5 = dark gray
  2 = beige       6 = dark brown
  3 = brown       7 = default green

{border}
  {info('Back Area Color')}
{border}

  0 = beige       4 = dark green
  1 = light green 5 = dark blue
  2 = blue        6 = light blue
  3 = black       7 = white

{border}
""")
    print()


def main():
    if len(sys.argv) < 3:
        print_banner()
        print("")
        sys.exit(1)

    rom_path = Path(sys.argv[1])
    command  = sys.argv[2].lower()

    if command in ("help", "--help", "-h", "advanced"):
        print_advanced_help()
        sys.exit(0)

    if command == "info":
        if not rom_path.exists():
            print(err(f"Error: '{rom_path}' not found.")); sys.exit(1)
        cmd_info()
        return

    if not rom_path.exists():
        print(err(f"Error: '{rom_path}' not found.")); sys.exit(1)

    raw = rom_path.read_bytes()
    if not check_rom(raw):
        print(err("Warning: file does not look like an SMA2 ROM. Continuing..."))
    if len(raw) < BGID_TABLE_OFFSET + BGID_TABLE_SIZE:
        print(err(f"Error: ROM too small ({len(raw)} bytes).")); sys.exit(1)

    out = out_path_for(rom_path)

    if command == "list":
        cmd_list(raw, show_raw="--raw" in sys.argv[3:])

    elif command == "get":
        if len(sys.argv) < 4:
            print(err("Usage: get <sublevel_id>")); sys.exit(1)
        try:
            cmd_get(raw, parse_hex(sys.argv[3]))
        except ValueError:
            print(err(f"Error: invalid sublevel_id '{sys.argv[3]}'")); sys.exit(1)

    elif command == "get-header":
        if len(sys.argv) < 4:
            print(err("Usage: get-header <sublevel_id>")); sys.exit(1)
        try:
            cmd_get_header(raw, parse_hex(sys.argv[3]))
        except ValueError:
            print(err(f"Error: invalid sublevel_id '{sys.argv[3]}'")); sys.exit(1)

    elif command == "set":
        if len(sys.argv) < 5:
            print(err("Usage: set <sublevel_id> <new_bgid>")); sys.exit(1)
        try:
            sid  = parse_hex(sys.argv[3])
            bgid = parse_hex(sys.argv[4])
        except ValueError as e:
            print(err(f"Error: {e}")); sys.exit(1)
        data = bytearray(raw)
        cmd_set(data, sid, bgid, out, keep_ptr="--keep-ptr" in sys.argv)

    elif command == "batch":
        if len(sys.argv) < 4:
            print(err("Usage: batch sub=bgid [sub=bgid ...]")); sys.exit(1)
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
        cmd_batch(data, changes, out, keep_ptr="--keep-ptr" in sys.argv)

    else:
        print(err(f"\n  Unknown command: '{command}'"))
        print(f"  Run without arguments to see the main commands.")
        print(f"  Run with 'help' to see all advanced commands.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
