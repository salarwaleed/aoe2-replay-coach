import struct, zlib, sys, os

FOLDER = r"D:\Program Files (x86)\Microsoft Games\Age of Empires II\Voobly Mods\AOC\Data Mods\v1.6 Game Data\SaveGame"

def get_header(path):
    with open(path, 'rb') as f:
        raw = f.read()
    header_len = struct.unpack('<I', raw[:4])[0]
    last_err = None
    for start in (8, 4, 12):
        try:
            data = zlib.decompress(raw[start:4+header_len], -zlib.MAX_WBITS)
            return data, start, raw, header_len
        except Exception as e:
            last_err = e
    raise last_err

if __name__ == '__main__':
    files = sys.argv[1:]
    if not files:
        files = ['rec.20260531-235412.mgz', 'rec.20260605-201901.mgz', 'rec.20260627-012029.mgz']
    for fn in files:
        path = os.path.join(FOLDER, fn)
        data, start, raw, header_len = get_header(path)
        print(f"=== {fn} === start={start} header_len={header_len} decompressed_len={len(data)}")
        outpath = os.path.join(os.path.dirname(__file__), fn + '.header.bin')
        with open(outpath, 'wb') as f:
            f.write(data)
        print(f"  saved -> {outpath}")
        print(f"  game_version (first bytes): {data[:8]!r}")
