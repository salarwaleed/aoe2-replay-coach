import struct, zlib, os, sys, re

DIR = r"D:\Program Files (x86)\Microsoft Games\Age of Empires II\Voobly Mods\AOC\Data Mods\v1.6 Game Data\SaveGame"
SKIP = {"rec.20260621-015219.mgz", "rec.20260625-204143.mgz"}

CIV_ID_TO_NAME = {
    0:"Gaia",1:"Aztecs",2:"Britons",3:"Byzantines",4:"Celts",5:"Chinese",6:"Franks",7:"Goths",8:"Huns",
    9:"Japanese",10:"Koreans",11:"Mayans",12:"Mongols",13:"Persians",14:"Saracens",15:"Spanish",16:"Teutons",
    17:"Turkish",18:"Vikings",19:"Italians",20:"Hindustani",21:"Incas",22:"Magyars",23:"Slavs",24:"Portuguese",
    25:"Ethiopians",26:"Malians",27:"Berbers",28:"Khmer",29:"Malay",30:"Burmese",31:"Vietnamese",32:"Cumans",
    33:"Lithuanians",34:"Bulgarians",35:"Tatars",36:"Burgundians",37:"Sicilians",38:"Poles",39:"Bohemians",
    40:"Dravidians",41:"Bengalis",42:"Gurjaras",43:"Romans",44:"Armenians",45:"Georgians",
}


def get_header(raw):
    header_len = struct.unpack("<I", raw[:4])[0]
    last_err = None
    for start in (8, 4, 12):
        try:
            data = zlib.decompress(raw[start:4 + header_len], -zlib.MAX_WBITS)
            return data
        except Exception as e:
            last_err = e
    raise last_err


def find_name_candidates(data):
    """Find player_name occurrences inside the `attributes` struct: an Int16ul
    length field (name_len_including_terminator) immediately followed by
    ASCII text of length (name_len - 1), then a 0x00 terminator byte."""
    n = len(data)
    out = []
    i = 0
    while i < n - 2:
        ln = struct.unpack_from("<H", data, i)[0]
        if 2 <= ln <= 24:
            s = data[i + 2:i + 2 + ln - 1]
            term_ok = (i + 2 + ln - 1) < n and data[i + 2 + ln - 1] == 0
            if term_ok and len(s) == ln - 1 and all(32 <= b < 127 for b in s) and re.search(rb"[A-Za-z0-9]", s):
                name = s.decode("ascii")
                if name.upper() != "GAIA":
                    out.append((i + 2, name))
        i += 1
    return out


def parse_player_attr(data, name_off, namelen_field_off):
    """Walk forward from a confirmed player_name occurrence through the
    rest of the `attributes` struct (per mgz/header/initial.py) to recover
    civilization id, player color, and spawn location. Returns None if the
    walk runs out of bounds or hits implausible values (sanity-checked)."""
    n = len(data)
    namelen = struct.unpack_from("<H", data, namelen_field_off)[0]
    pos = name_off + (namelen - 1)
    try:
        pos += 1  # pad 0x00
        pos += 1  # pad 0x16
        if pos + 4 > n:
            return None
        num_header_data = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        pos += 1  # pad 0x21
        if num_header_data < 0 or num_header_data > 2000:
            return None
        pos += num_header_data * 4  # player_stats block
        pos += 1  # trailing pad
        if pos + 8 > n:
            return None
        camx = struct.unpack_from("<f", data, pos)[0]
        pos += 4
        camy = struct.unpack_from("<f", data, pos)[0]
        pos += 4
        if pos + 4 > n:
            return None
        num_saved_views = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        if num_saved_views < 0 or num_saved_views > 100:
            return None
        if num_saved_views > 0:
            pos += num_saved_views * 8
        if pos + 8 > n:
            return None
        sx = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        sy = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        culture = data[pos]; pos += 1
        civ = data[pos]; pos += 1
        game_status = data[pos]; pos += 1
        resigned = data[pos]; pos += 1
        pos += 1
        color = data[pos]; pos += 1
    except (struct.error, IndexError):
        return None

    return {
        "civ_id": civ,
        "civ_name": CIV_ID_TO_NAME.get(civ, f"Civ{civ}"),
        "color": color,
        "culture": culture,
        "spawn": (sx, sy),
        "cam": (round(camx, 1), round(camy, 1)),
        "game_status": game_status,
        "resigned": resigned,
    }


def sane(rec, sx_max=300):
    if rec is None:
        return False
    sx, sy = rec["spawn"]
    if not (0 < sx < sx_max and 0 < sy < sx_max):
        return False
    if not (0 <= rec["civ_id"] <= 90):
        return False
    if not (0 <= rec["color"] <= 8):
        return False
    return True


def extract_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    data = get_header(raw)
    candidates = find_name_candidates(data)

    results = []
    seen_names = set()
    for name_off, name in candidates:
        namelen_field_off = name_off - 2
        rec = parse_player_attr(data, name_off, namelen_field_off)
        ok = sane(rec)
        key = (name, rec["spawn"] if rec else None)
        if key in seen_names:
            continue
        seen_names.add(key)
        results.append({
            "name": name,
            "ok": ok,
            "rec": rec,
        })
    return results


def main():
    files = sorted(
        fn for fn in os.listdir(DIR)
        if fn.lower().endswith(".mgz") and fn not in SKIP
    )
    total_files = 0
    files_with_clean_extraction = 0
    summary_lines = []

    for fn in files:
        total_files += 1
        path = os.path.join(DIR, fn)
        try:
            results = extract_file(path)
        except Exception as e:
            summary_lines.append(f"{fn}: ERROR {e}")
            continue

        good = [r for r in results if r["ok"]]
        line = f"{fn}: {len(good)} clean / {len(results)} candidates"
        summary_lines.append(line)
        if good:
            files_with_clean_extraction += 1
        for r in results:
            tag = "OK " if r["ok"] else "BAD"
            rec = r["rec"]
            if rec:
                print(f"  [{tag}] {fn:35s} name={r['name']:16s} civ={rec['civ_name']:12s}(id={rec['civ_id']:2d}) "
                      f"color={rec['color']} spawn={rec['spawn']}")
            else:
                print(f"  [{tag}] {fn:35s} name={r['name']:16s} (parse failed)")

    print("\n=== SUMMARY ===")
    for line in summary_lines:
        print(line)
    print(f"\nFiles processed: {total_files}")
    print(f"Files with >=1 clean player extraction: {files_with_clean_extraction}")


if __name__ == "__main__":
    main()
