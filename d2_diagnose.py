#!/usr/bin/env python3
"""
d2_diagnose.py  —  Socket Inspector
────────────────────────────────────
Run this to find out exactly why Trait 1 / Trait 2 are blank.

It reads your already-cached manifest (no API call), picks a few weapons,
and for every socket entry prints:
  • The raw hash values in the entry
  • The first 3 plug items that resolve from the plugset
  • Each plug item's  plug.plugCategoryIdentifier  field
  • What our classifier would label it

Paste the output back and we'll know exactly what to fix.

Usage:
    python d2_diagnose.py
"""

import sqlite3, json, os

try:
    from config import OUTPUT_DIR
except ImportError:
    raise SystemExit("Copy config.example.py to config.py first. See README.md.")
import os
MANIFEST_DB = os.path.join(OUTPUT_DIR, "manifest.content")
WEAPONS_TO_CHECK = ["Duty Bound", "Chroma Rush", "Gnawing Hunger"]  # Change if you like

# ── helpers ────────────────────────────────────────────────────────────────────

def to_signed(h):
    return h - 2**32 if h >= 2**31 else h

def load_table(conn, table):
    rows = conn.execute(f"SELECT id, json FROM {table}").fetchall()
    return {rid: json.loads(b) for rid, b in rows}

def classify_identifier(il):
    if any(k in il for k in ("stock","grip","blade","guard","bowstring","haft")):
        return "skip"
    if "intrinsic" in il: return "intrinsic"
    if any(k in il for k in ("barrel","sight","scope")): return "barrel"
    if any(k in il for k in ("magazine","battery","batteries","arrow")): return "magazine"
    if "origin" in il: return "origin"
    if any(k in il for k in ("trait","perk","frame_option","misc")): return "trait"
    if "masterwork" in il: return "masterwork"
    if "mod" in il: return "skip"
    return "unknown"

# ── main ───────────────────────────────────────────────────────────────────────

print(f"Loading manifest from {MANIFEST_DB} ...")
conn = sqlite3.connect(MANIFEST_DB)

print("Loading tables (takes a few seconds)...")
item_defs = load_table(conn, "DestinyInventoryItemDefinition")
plugsets   = {}
for k, v in load_table(conn, "DestinyPlugSetDefinition").items():
    plugsets[k] = [p["plugItemHash"] for p in v.get("reusablePlugItems", [])]

socket_type_whitelist = {}
for k, v in load_table(conn, "DestinySocketTypeDefinition").items():
    socket_type_whitelist[k] = [e.get("categoryIdentifier","") for e in v.get("plugWhitelist",[])]

# Socket categories
socket_cat_names = {}
try:
    for k, v in load_table(conn, "DestinySocketCategoryDefinition").items():
        socket_cat_names[k] = v.get("displayProperties",{}).get("name","")
except:
    print("  (DestinySocketCategoryDefinition not found)")

conn.close()
print(f"Loaded {len(item_defs):,} items, {len(plugsets):,} plugsets\n")

# ── per-weapon inspection ──────────────────────────────────────────────────────

for weapon_name in WEAPONS_TO_CHECK:
    matches = [
        item for item in item_defs.values()
        if item.get("displayProperties",{}).get("name","").lower() == weapon_name.lower()
        and item.get("itemType") == 3
        and not item.get("redacted", False)
    ]

    if not matches:
        print(f"\n[!] No weapon found named '{weapon_name}'\n")
        continue

    item = matches[0]  # take first match
    print(f"\n{'='*70}")
    print(f"  WEAPON: {item['displayProperties']['name']}")
    print(f"{'='*70}")

    # Print socket categories on this weapon
    sock_cats = item.get("sockets",{}).get("socketCategories",[])
    if sock_cats:
        print("\n  socketCategories on this weapon:")
        for sc in sock_cats:
            cat_hash = sc.get("socketCategoryHash", 0)
            cat_name = socket_cat_names.get(to_signed(cat_hash), f"hash:{cat_hash}")
            indexes  = sc.get("socketIndexes", [])
            print(f"    [{cat_name}]  indexes={indexes}")

    print()
    socket_entries = item.get("sockets",{}).get("socketEntries",[])

    for i, entry in enumerate(socket_entries):
        rand_h   = entry.get("randomizedPlugSetHash")
        reuse_h  = entry.get("reusablePlugSetHash")
        single_h = entry.get("singleInitialItemHash")

        # Collect plugs
        plug_hashes = []
        source = "none"
        if rand_h:
            plug_hashes = plugsets.get(to_signed(rand_h), [])
            source = f"randomized={rand_h}  ({len(plug_hashes)} plugs in set)"
        elif reuse_h:
            plug_hashes = plugsets.get(to_signed(reuse_h), [])
            source = f"reusable={reuse_h}  ({len(plug_hashes)} plugs in set)"
        elif single_h and single_h != 0:
            plug_hashes = [single_h]
            source = f"single={single_h}"

        # Socket type whitelist labels
        sth       = entry.get("socketTypeHash", 0)
        wl_labels = socket_type_whitelist.get(to_signed(sth), [])
        wl_kind   = "unknown"
        for lbl in wl_labels:
            k = classify_identifier(lbl.lower())
            if k != "unknown":
                wl_kind = k
                break

        print(f"  Socket {i:2d} | socketTypeHash={sth}  source={source}")
        print(f"           | socketType whitelist labels = {wl_labels}  → kind={wl_kind}")

        if not plug_hashes:
            print(f"           | NO PLUGS RESOLVED")
        else:
            for j, ph in enumerate(plug_hashes[:3]):
                pdef = item_defs.get(to_signed(ph), None)
                if pdef is None:
                    print(f"           | plug[{j}] hash={ph}  → NOT FOUND in item_defs")
                    continue
                pname   = pdef.get("displayProperties",{}).get("name","(no name)")
                plug_f  = pdef.get("plug", None)
                plug_cat = plug_f.get("plugCategoryIdentifier","(field missing)") if plug_f else "(plug field absent)"
                cat_kind = classify_identifier(plug_cat.lower()) if plug_f else "unknown"
                print(f"           | plug[{j}] '{pname}'  plugCategoryIdentifier='{plug_cat}'  → {cat_kind}")

            if len(plug_hashes) > 3:
                print(f"           | ... and {len(plug_hashes)-3} more plugs")

        print()
