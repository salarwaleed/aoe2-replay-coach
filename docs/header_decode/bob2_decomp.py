import struct, zlib, sys, os

DIR = r"D:\Program Files (x86)\Microsoft Games\Age of Empires II\Voobly Mods\AOC\Data Mods\v1.6 Game Data\SaveGame"
SKIP = {"rec.20260621-015219.mgz", "rec.20260625-204143.mgz"}

def get_header(path):
    with open(path, "rb") as f:
        raw = f.read()
    header_len = struct.unpack("<I", raw[:4])[0]
    last_err = None
    for start in (8, 4, 12):
        try:
            data = zlib.decompress(raw[start:4+header_len], -zlib.MAX_WBITS)
            return data, start
        except Exception as e:
            last_err = e
    raise last_err

if __name__ == "__main__":
    fn = sys.argv[1] if len(sys.argv) > 1 else "rec.20260531-235412.mgz"
    path = os.path.join(DIR, fn)
    data, start = get_header(path)
    print(f"file={fn} start_offset={start} header_decompressed_len={len(data)}")
    out = os.path.join(os.path.dirname(__file__), "header_" + fn + ".bin")
    with open(out, "wb") as f:
        f.write(data)
    print("wrote", out)
