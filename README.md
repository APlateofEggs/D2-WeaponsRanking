# D2 Weapon Database

A two-part tool for Destiny 2 players: a Python script that pulls every active Legendary and Exotic weapon from the Bungie API, and a standalone browser-based viewer for browsing weapons, searching perk rolls, and displaying god roll recommendations.

\---

## What it does

**The extractor** (`d2\_weapon\_extractor.py`) connects to the Bungie API manifest, downloads the full weapon database, and exports a CSV with:

* Weapon name, type, slot, element, rarity, and archetype
* Full barrel, magazine, Trait 1, Trait 2, and origin trait perk pools
* Columns for your own god roll picks and notes

**The viewer** (`d2\_weapon\_viewer.html`) is a self-contained HTML file — open it in any browser, load your CSV, and you get:

* Searchable, sortable weapon table with element and tier color coding
* Weapon detail modal with all perk options displayed as tags
* AegisRelic recommendation highlighting (teal = recommended perk, gold = user personal pick if they choose to edit the csv)
* Tier badge (S/A/B/C/D/E/F) if ranking data is present in your CSV
* Perk search — type any perk name and see every weapon that can roll it, with a ★ if it's also an AegisRelic-recommended roll

\---

## Requirements

* Python 3.8 or higher
* The `requests` library (`pip install requests`)
* A free Bungie API key — register at [bungie.net/en/Application](https://www.bungie.net/en/Application)

\---

## Setup

**1. Clone the repository**

```bash
git clone https://github.com/yourusername/d2-weapon-database.git
cd d2-weapon-database
```

**2. Install dependencies**

```bash
pip install requests
```

**3. Create your config file**

Copy the example config and fill in your values:

```bash
cp config.example.py config.py
```

Then open `config.py` and add your Bungie API key and the folder path where you want the CSV output saved:

```python
API\_KEY    = "your-api-key-here"
OUTPUT\_DIR = r"C:\\Users\\YourName\\Desktop\\D2Weapons"   # Windows
# OUTPUT\_DIR = "/home/yourname/d2weapons"             # Mac / Linux
```

`config.py` is listed in `.gitignore` and will never be committed.

\---

## Usage

**Run the extractor**

```bash
python d2\_weapon\_extractor.py
```

On first run it downloads the Bungie manifest (\~80MB). Subsequent runs check the version and skip the download if nothing has changed — so re-running after a game update automatically pulls fresh data.

The script will prints a summary when complete so you aren't left hanging:

```
✓ Extracted 1,215 active legendary/exotic weapons
✓ CSV saved → C:\\Users\\YourName\\Desktop\\D2Weapons\\d2\_legendary\_weapons.csv
```

**Open the viewer**

Open `d2\_weapon\_viewer.html` in Chrome or Firefox. Click **Choose File** (or drag and drop) to load the CSV the script just generated. Everything runs locally — no data leaves your machine.

\---

## Adding god roll recommendations (Aegis columns)

The viewer will automatically highlight recommended perks if your CSV contains these extra columns:

|Column|Content|
|-|-|
|`Aegis Barrel`|Recommended barrel(s), pipe-separated|
|`Aegis Mag`|Recommended magazine(s), pipe-separated|
|`Aegis Trait 1`|Recommended Trait 1 perk(s), pipe-separated|
|`Aegis Trait 2`|Recommended Trait 2 perk(s), pipe-separated|
|`Aegis Notes`|Free-text notes about the weapon|
|`Aegis Rank`|Numeric rank for sorting|
|`Aegis Tier`|Tier rating: S, A, B, C, D, E, F, or NR|

Add these columns to the CSV after running the extractor (e.g. in Google Sheets), then reload the CSV in the viewer. Weapons without Aegis data display normally.

\---

## Troubleshooting

**`config.py not found`** — Run `cp config.example.py config.py` and fill in your API key.

**Manifest download is slow** — First run only. The Bungie manifest is \~80MB. Subsequent runs use the cached copy.

**Trait 1 / Trait 2 columns are blank for some weapons** — Run `d2\_diagnose.py` with a weapon name to inspect its socket data. Old or unusual weapons occasionally use non-standard manifest identifiers. Open an issue with the weapon name and the diagnose output and we can add support.

**`Edge` browser blocks the file** — Use Chrome or Firefox when opening the HTML file locally. Edge applies stricter restrictions to local HTML files.

\---

## How it works

Bungie manifest is a SQLite database (\~80MB) containing everything in Destiny 2. The extractor queries `DestinyInventoryItemDefinition`, filters for active non-sunset Legendary and Exotic weapons (Rare's can slip in. Still fixing), and resolves perk names by reading each plug item's own `plug.plugCategoryIdentifier` field — which turned out to be the reliable approach after the socket type whitelist method proved inconsistent across weapon generations.

Sunset detection uses `quality.versions\[].powerCapHash` → `DestinyPowerCapDefinition.powerCap`. Weapons whose highest power cap is at or below the current game cap are excluded.

Deduplication keeps the highest-season entry when multiple manifest entries share the same weapon name (common with reissued weapons).

\---

## Contributing

Pull requests welcome. If a weapon is missing perks or has perks in the wrong column, run `d2\_diagnose.py` against it and include the output in your issue — that shows the exact socket identifiers the manifest uses for that weapon.

\---

## Disclaimer

This project is not affiliated with or endorsed by Bungie. Destiny 2 and all associated content are property of Bungie, Inc. Usage of the Bungie API is subject to the [Bungie API Terms of Use](https://www.bungie.net/en/Legal/Terms).

