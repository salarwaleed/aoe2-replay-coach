"""
Quick test — run this to verify mgz can read your recordings.
  python test_mgz.py
"""
import glob, os

SAVEGAME_PATHS = [
    r"D:\Program Files (x86)\Microsoft Games\Age of Empires II\SaveGame",
    r"D:\Program Files (x86)\Microsoft Games\Age of Empires II\Voobly Mods\AOC\Data Mods\v1.6 Game Data\SaveGame",
]

files = []
for p in SAVEGAME_PATHS:
    files.extend(glob.glob(os.path.join(p, "*.mgz")))
files = sorted(files)

print(f"Found {len(files)} recordings\n")

try:
    from mgz.summary import Summary
except ImportError:
    print("ERROR: mgz not installed. Run:  pip install mgz")
    raise SystemExit(1)

for f in files:
    try:
        with open(f, "rb") as fh:
            s = Summary(fh)
            players  = s.get_players() or []
            duration = s.get_duration()
            map_info = s.get_map()

            map_name = "Unknown"
            if isinstance(map_info, dict):
                map_name = map_info.get("name", "Unknown")
            elif map_info:
                map_name = str(map_info)

            dur_min = round(duration / 60000, 1) if duration else "?"
            winner  = next((p["name"] for p in players if p.get("winner")), "?")
            pnames  = " vs ".join(
                f"{p.get('name','?')} ({str(p.get('civilization','?')).title()})"
                for p in players
            )
            print(f"✅ {os.path.basename(f)}")
            print(f"   Map: {map_name}  |  Duration: {dur_min} min  |  Winner: {winner}")
            print(f"   Players: {pnames}\n")

    except Exception as e:
        print(f"❌ {os.path.basename(f)}  →  {e}\n")
