#!/usr/bin/env python3
"""
Destiny 2 Legendary Weapon Extractor  v3
─────────────────────────────────────────
Key fix in v3
  The socket type whitelist approach (reading DestinySocketTypeDefinition's
  plugWhitelist identifiers) reliably classified barrels and magazines but
  returned "unknown" for trait sockets on almost every weapon, because Bungie
  uses generic or empty whitelist entries for those sockets.

  Fix: classify sockets primarily by reading the plug ITEMS' own
  plug.plugCategoryIdentifier field (e.g. "v400.weapon.mod_guns.trait").
  Each plug in the manifest carries its own category string — that is the
  ground truth for what kind of plug it is. The socket type whitelist is
  now used only as a fallback when no plugs are available.

  This also fixes the "traits landing in Origin Trait" problem: genuine
  origin perks (Veist Stinger, Bray Legacy, etc.) carry origin category
  identifiers on the plug item; regular trait perks carry trait identifiers.

Other fixes carried from v2
  • Deduplication by season number (highest = most recent version)
  • Season column in output
  • "Empty Origins Socket" and other placeholder names filtered out
  • Full perk pool (currentlyCanRoll not filtered)
"""

import requests
import zipfile
import sqlite3
import json
import csv
import os
import io
from collections import defaultdict

# ── Configuration ──────────────────────────────────────────────────────────────

# Load user configuration from config.py (never committed to git)
try:
    from config import API_KEY, OUTPUT_DIR
except ImportError:
    raise SystemExit(
        "\n  config.py not found.\n"
        "  Copy config.example.py to config.py and add your API key.\n"
        "  See README.md for setup instructions.\n"
    )

BASE_URL     = "https://www.bungie.net"
OUTPUT_CSV   = os.path.join(OUTPUT_DIR, "d2_legendary_weapons.csv")
MANIFEST_DB  = os.path.join(OUTPUT_DIR, "manifest.content")
VERSION_FILE = os.path.join(OUTPUT_DIR, "manifest_version.txt")

CURRENT_POWER_CAP = 550
MIN_TIER_TYPE     = 3     # tierType > 3 → Legendary (4) and Exotic (5)

HEADERS = {"X-API-Key": API_KEY}

# ── Weapon sub-type names ──────────────────────────────────────────────────────

SUB_TYPE_NAMES = {
    6:  "Auto Rifle",       7:  "Shotgun",          8:  "Machine Gun",
    9:  "Hand Cannon",      10: "Rocket Launcher",  11: "Fusion Rifle",
    12: "Sniper Rifle",     13: "Pulse Rifle",       14: "Scout Rifle",
    17: "Sidearm",          18: "Sword",             22: "Linear Fusion Rifle",
    23: "Grenade Launcher", 24: "Submachine Gun",    25: "Trace Rifle",
    31: "Combat Bow",       33: "Glaive",
}

# Plug display names that indicate an empty / placeholder socket.
EMPTY_PLUG_NAMES = {
    "Empty Origins Socket", "Default Ornament", "Locked Armor Ornament",
    "Default Shader", "Default Catalyst", "Default Grip", "Default Stock",
    "Empty Mod Socket", "Empty Intrinsic Traits", "No Artifact Bonus",
    "Default Tracker",
}

# ── CSV columns ────────────────────────────────────────────────────────────────

COLUMNS = [
    "Name", "Type", "Slot", "Energy", "Rarity", "Season",
    "Intrinsic",
    "Barrel / Scope",
    "Magazine / Battery",
    "Trait 1",
    "Trait 2",
    "Origin Trait",
    "My Trait 1 Pick",
    "My Trait 2 Pick",
    "Notes",
]

# ── Hash utility ───────────────────────────────────────────────────────────────

def to_signed(h):
    return h - 2**32 if h >= 2**31 else h

# ── Manifest download & caching ────────────────────────────────────────────────

def get_manifest_db():
    print("Checking manifest version...")
    r = requests.get(f"{BASE_URL}/Platform/Destiny2/Manifest/", headers=HEADERS)
    r.raise_for_status()
    response = r.json()["Response"]
    version  = response["version"]

    if os.path.exists(VERSION_FILE) and os.path.exists(MANIFEST_DB):
        with open(VERSION_FILE) as f:
            if f.read().strip() == version:
                print(f"  Manifest up to date (v{version}) — using cached copy.")
                return MANIFEST_DB

    dl_path = BASE_URL + response["mobileWorldContentPaths"]["en"]
    print(f"  Downloading manifest v{version} — this may take a minute...")
    r = requests.get(dl_path, headers=HEADERS)
    r.raise_for_status()

    print("  Extracting SQLite database...")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        inner = z.namelist()[0]
        with z.open(inner) as src, open(MANIFEST_DB, "wb") as dst:
            dst.write(src.read())

    with open(VERSION_FILE, "w") as f:
        f.write(version)
    print("  Manifest ready.")
    return MANIFEST_DB

# ── Manifest table loaders ─────────────────────────────────────────────────────

def load_table(conn, table_name):
    rows = conn.execute(f"SELECT id, json FROM {table_name}").fetchall()
    return {row_id: json.loads(blob) for row_id, blob in rows}

def build_damage_type_map(conn):
    t = load_table(conn, "DestinyDamageTypeDefinition")
    return {k: v.get("displayProperties", {}).get("name", "Unknown") for k, v in t.items()}

def build_power_cap_map(conn):
    t = load_table(conn, "DestinyPowerCapDefinition")
    return {k: v.get("powerCap", 0) for k, v in t.items()}

def build_slot_map(conn):
    t = load_table(conn, "DestinyEquipmentSlotDefinition")
    return {k: v.get("displayProperties", {}).get("name", "Unknown") for k, v in t.items()}

def build_plugset_map(conn):
    """
    {signed_hash: [plugItemHash, ...]}
    currentlyCanRoll intentionally not filtered — older weapons have all plugs
    marked false, which was causing blank trait columns.
    """
    t = load_table(conn, "DestinyPlugSetDefinition")
    result = {}
    for k, v in t.items():
        result[k] = [p["plugItemHash"] for p in v.get("reusablePlugItems", [])]
    return result

def build_socket_type_map(conn):
    """Fallback only: {signed_hash: [plugCategoryIdentifier, ...]}"""
    t = load_table(conn, "DestinySocketTypeDefinition")
    result = {}
    for k, v in t.items():
        result[k] = [e.get("categoryIdentifier", "") for e in v.get("plugWhitelist", [])]
    return result

def build_season_map(conn):
    try:
        t = load_table(conn, "DestinySeasonDefinition")
        return {k: v.get("seasonNumber", 0) for k, v in t.items()}
    except Exception:
        print("  Warning: DestinySeasonDefinition unavailable — season will show as 0.")
        return {}

# ── Socket classification ──────────────────────────────────────────────────────

def classify_identifier(il):
    """
    Core classification logic applied to a single lower-cased identifier string.
    Used by both the plug-item-based and socket-type-based classifiers.

    Returns one of: 'intrinsic', 'barrel', 'magazine', 'origin', 'trait',
                    'masterwork', 'skip', 'unknown'
    """
    # Physical attachments — explicit skip before generic "mod" catch
    if any(k in il for k in ("stock", "grip", "blade", "guard", "bowstring", "haft")):
        return "skip"
    # Intrinsic frame — check before "perk" (weapon_perks_intrinsic contains both)
    if "intrinsic" in il:
        return "intrinsic"
    # Barrel / sight / scope
    if any(k in il for k in ("barrel", "sight", "scope")):
        return "barrel"
    # Magazine / battery / arrows (bows)
    if any(k in il for k in ("magazine", "battery", "batteries", "arrow")):
        return "magazine"
    # Origin — MUST come before "perk" because origin identifiers end in "_origin_perk"
    if "origin" in il:
        return "origin"
    # Traits / player-chosen perks
    # "frames" is the plugCategoryIdentifier Bungie uses for weapon trait sockets
    # (confirmed via manifest inspection — both the socket type whitelist and the
    # plug items themselves use "frames", not "trait" or "perk")
    if any(k in il for k in ("trait", "perk", "frames", "frame_option", "misc")):
        return "trait"
    # Masterworks
    if "masterwork" in il:
        return "masterwork"
    # Remaining mod sockets (catalysts, cosmetics, etc.)
    if "mod" in il:
        return "skip"
    return "unknown"


def classify_by_plug_items(plug_hashes, item_defs):
    """
    PRIMARY classifier.

    Reads the plug.plugCategoryIdentifier field directly off each candidate
    plug item definition.  This is the ground truth for what a plug IS —
    e.g. a "Headstone" perk item carries plugCategoryIdentifier =
    "v400.weapon.mod_guns.trait", while "Veist Stinger" carries an origin
    identifier.  We sample up to the first 5 plugs and return the first
    non-unknown classification.
    """
    for ph in plug_hashes[:5]:
        plug_item = item_defs.get(to_signed(ph), {})
        cat = plug_item.get("plug", {}).get("plugCategoryIdentifier", "").lower()
        if cat:
            result = classify_identifier(cat)
            if result != "unknown":
                return result
    return "unknown"


def classify_by_socket_type(socket_type_hash, socket_type_map):
    """
    FALLBACK classifier (used when no plugs are available).

    Reads the DestinySocketTypeDefinition plugWhitelist identifiers.
    Reliable for barrels and magazines; unreliable for traits (many trait
    sockets have empty or generic whitelists — that was the root cause of
    the blank Trait 1 / Trait 2 columns).
    """
    for ident in socket_type_map.get(to_signed(socket_type_hash), []):
        result = classify_identifier(ident.lower())
        if result != "unknown":
            return result
    return "unknown"

# ── Perk name resolution ───────────────────────────────────────────────────────

def resolve_plug_names(plug_hashes, item_defs):
    seen, names = set(), []
    for ph in plug_hashes:
        item = item_defs.get(to_signed(ph), {})
        name = item.get("displayProperties", {}).get("name", "").strip()
        if name and name not in seen and name not in EMPTY_PLUG_NAMES:
            seen.add(name)
            names.append(name)
    return names

# ── Per-weapon perk extraction ─────────────────────────────────────────────────

def extract_perks(item, item_defs, plugset_map, socket_type_map):
    """
    Walks the weapon's sockets and fills five perk buckets.

    Classification order:
      1. Collect plug hashes for this socket.
      2. Classify by reading the first plug item's plugCategoryIdentifier
         (primary — this is the ground truth).
      3. Fall back to socket type whitelist identifiers if no plugs found.
      4. Skip the socket if still unknown.
    """
    socket_entries = item.get("sockets", {}).get("socketEntries", [])

    buckets = {
        "intrinsic": [],
        "barrel":    [],
        "magazine":  [],
        "traits":    [],   # accumulate; split into Trait 1 / Trait 2 later
        "origin":    [],
    }

    for entry in socket_entries:

        # ── Step 1: collect plug hashes ────────────────────────────────────────
        plug_hashes = []
        rand_hash   = entry.get("randomizedPlugSetHash")
        reuse_hash  = entry.get("reusablePlugSetHash")
        single_hash = entry.get("singleInitialItemHash")

        if rand_hash:
            plug_hashes = plugset_map.get(to_signed(rand_hash), [])
        elif reuse_hash:
            plug_hashes = plugset_map.get(to_signed(reuse_hash), [])
        elif single_hash and single_hash != 0:
            plug_hashes = [single_hash]

        # ── Step 2: classify (plug items primary, socket type fallback) ────────
        if plug_hashes:
            kind = classify_by_plug_items(plug_hashes, item_defs)
        else:
            kind = "unknown"

        if kind == "unknown":
            kind = classify_by_socket_type(
                entry.get("socketTypeHash", 0), socket_type_map
            )

        if kind in ("masterwork", "skip", "unknown"):
            continue

        # ── Step 3: resolve perk names and fill buckets ────────────────────────
        names = resolve_plug_names(plug_hashes, item_defs)
        if not names:
            continue

        if   kind == "intrinsic" and not buckets["intrinsic"]:
            buckets["intrinsic"] = names
        elif kind == "barrel"    and not buckets["barrel"]:
            buckets["barrel"]    = names
        elif kind == "magazine"  and not buckets["magazine"]:
            buckets["magazine"]  = names
        elif kind == "origin"    and not buckets["origin"]:
            buckets["origin"]    = names
        elif kind == "trait":
            buckets["traits"].append(names)

    t = buckets["traits"]
    return {
        "Intrinsic":          " | ".join(buckets["intrinsic"]),
        "Barrel / Scope":     " | ".join(buckets["barrel"]),
        "Magazine / Battery": " | ".join(buckets["magazine"]),
        "Trait 1":            " | ".join(t[0]) if len(t) > 0 else "",
        "Trait 2":            " | ".join(t[1]) if len(t) > 1 else "",
        "Origin Trait":       " | ".join(buckets["origin"]),
    }

# ── Main extraction ────────────────────────────────────────────────────────────

def extract_weapons(db_path):
    print("\nOpening manifest database...")
    conn = sqlite3.connect(db_path)

    print("Loading lookup tables...")
    damage_map      = build_damage_type_map(conn)
    power_cap_map   = build_power_cap_map(conn)
    slot_map        = build_slot_map(conn)
    plugset_map     = build_plugset_map(conn)
    socket_type_map = build_socket_type_map(conn)
    season_map      = build_season_map(conn)

    print("Loading DestinyInventoryItemDefinition (largest table — give it a moment)...")
    item_defs = load_table(conn, "DestinyInventoryItemDefinition")
    print(f"  {len(item_defs):,} total entries.")

    raw_weapons = []

    for item_id, item in item_defs.items():

        if item.get("itemType") != 3:
            continue
        if item.get("redacted", False):
            continue

        inventory = item.get("inventory", {})
        if inventory.get("tierType", 0) <= MIN_TIER_TYPE:
            continue

        name = item.get("displayProperties", {}).get("name", "").strip()
        if not name:
            continue

        # Sunset filter
        versions = item.get("quality", {}).get("versions", [])
        if versions:
            max_cap = max(
                power_cap_map.get(to_signed(v.get("powerCapHash", 0)), 0)
                for v in versions
            )
            if max_cap != 999999 and max_cap <= CURRENT_POWER_CAP:
                continue

        # Season number
        season_hash = item.get("seasonHash", 0)
        season_num  = season_map.get(to_signed(season_hash), 0) if season_hash else 0

        # Core fields
        sub_type    = item.get("itemSubType", 0)
        weapon_type = SUB_TYPE_NAMES.get(sub_type, item.get("itemTypeDisplayName", "Unknown"))
        tier_name   = inventory.get("tierTypeName", "Unknown")

        dmg_hash = item.get("defaultDamageTypeHash", 0)
        energy   = damage_map.get(to_signed(dmg_hash), "Kinetic") if dmg_hash else "Kinetic"

        slot_hash = item.get("equippingBlock", {}).get("equipmentSlotTypeHash", 0)
        slot      = slot_map.get(to_signed(slot_hash), "Unknown") if slot_hash else "Unknown"

        perks = extract_perks(item, item_defs, plugset_map, socket_type_map)

        raw_weapons.append({
            "Name":            name,
            "Type":            weapon_type,
            "Slot":            slot,
            "Energy":          energy,
            "Rarity":          tier_name,
            "Season":          season_num,
            **perks,
            "My Trait 1 Pick": "",
            "My Trait 2 Pick": "",
            "Notes":           "",
        })

    conn.close()
    print(f"  {len(raw_weapons):,} raw entries before deduplication.")

    # Dedup: same name → keep highest season; break ties by perk richness
    by_name = defaultdict(list)
    for w in raw_weapons:
        by_name[w["Name"]].append(w)

    weapons = []
    for name, variants in by_name.items():
        best = max(
            variants,
            key=lambda w: (
                w["Season"],
                len(w["Trait 1"]) + len(w["Trait 2"]) + len(w["Barrel / Scope"])
            )
        )
        weapons.append(best)

    weapons.sort(key=lambda w: (w["Type"], w["Name"]))

    # Summary stats
    t1 = sum(1 for w in weapons if w["Trait 1"])
    t2 = sum(1 for w in weapons if w["Trait 2"])
    print(f"  {len(weapons):,} unique weapons after deduplication.")
    print(f"  Trait 1 populated: {t1}  |  Trait 2 populated: {t2}")
    return weapons

# ── CSV export ─────────────────────────────────────────────────────────────────

def save_csv(weapons, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(weapons)
    print(f"\n✓ CSV saved → {path}")

# ── Debug helper ───────────────────────────────────────────────────────────────

def debug_weapon(name_fragment, db_path):
    """
    Prints each socket's plug category identifiers and classification for a
    named weapon.  Use this if a specific weapon still has blank trait columns
    after running the main script — paste the output here and we can add any
    missing identifier patterns.

    Uncomment the call at the bottom of this file to use it.
    """
    conn = sqlite3.connect(db_path)
    socket_type_map = build_socket_type_map(conn)
    plugset_map     = build_plugset_map(conn)
    item_defs       = load_table(conn, "DestinyInventoryItemDefinition")
    conn.close()

    matches = [
        item for item in item_defs.values()
        if name_fragment.lower() in item.get("displayProperties", {}).get("name", "").lower()
        and item.get("itemType") == 3
        and not item.get("redacted", False)
    ][:2]

    if not matches:
        print(f"No weapons matched '{name_fragment}'")
        return

    for item in matches:
        iname = item["displayProperties"]["name"]
        print(f"\n{'='*70}\n  {iname}\n{'='*70}")

        for i, entry in enumerate(item.get("sockets", {}).get("socketEntries", [])):

            plug_hashes = []
            rand_hash   = entry.get("randomizedPlugSetHash")
            reuse_hash  = entry.get("reusablePlugSetHash")
            single_hash = entry.get("singleInitialItemHash")
            if rand_hash:
                plug_hashes = plugset_map.get(to_signed(rand_hash), [])
            elif reuse_hash:
                plug_hashes = plugset_map.get(to_signed(reuse_hash), [])
            elif single_hash and single_hash != 0:
                plug_hashes = [single_hash]

            # Show plug category identifiers from the actual plug items
            plug_cats = []
            for ph in plug_hashes[:3]:
                plug_item = item_defs.get(to_signed(ph), {})
                cat = plug_item.get("plug", {}).get("plugCategoryIdentifier", "")
                name = plug_item.get("displayProperties", {}).get("name", "?")
                if cat:
                    plug_cats.append(f"{name} → {cat}")

            kind_plug   = classify_by_plug_items(plug_hashes, item_defs) if plug_hashes else "no_plugs"
            kind_socket = classify_by_socket_type(entry.get("socketTypeHash", 0), socket_type_map)

            print(f"  [{i:2d}] plug_kind={kind_plug:<12} socket_kind={kind_socket:<12} "
                  f"n_plugs={len(plug_hashes)}")
            for pc in plug_cats:
                print(f"        {pc}")

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    db_path = get_manifest_db()
    weapons = extract_weapons(db_path)
    save_csv(weapons, OUTPUT_CSV)
    print("\nAll done!  Import d2_legendary_weapons.csv into Google Sheets.")
    print("Tip: File → Import → Upload → Replace spreadsheet.")

    # Uncomment to inspect a specific weapon's socket classification:
    # debug_weapon("Adamantite", db_path)
