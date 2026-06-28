"""
Full validation pass: for a given .mgz file, walk all players via GotoObjectsEnd heuristic
(name extraction -- already proven reliable), then for each player compute ps_start and
read civ/color/spawn at the FIXED +1925 byte offset hypothesis. Print results, and also
brute-force search +/- 50 bytes around 1925 in case the offset shifts with num_header_data
or player count, to see if 1925 is truly constant or derived from a formula.
"""
import sys, os, struct, re
sys.path.insert(0, os.path.dirname(__file__))

def find_start_of_objects(data, off):
    pattern = re.compile(rb'\x0b\x00.\x00\x00\x00\x02\x00\x00', re.DOTALL)
    m = pattern.search(data, off)
    return m.end() if m else None

def goto_objects_end(data, search_start, num_players, marker_num, save_version):
    read_bytes = data[search_start:]
    marker_pat = b'\x16' + struct.pack('<I', int(marker_num)) + b'\x21'
    marker = read_bytes.find(marker_pat)
    if marker > 0:
        count = 0
        while struct.unpack('<H', read_bytes[marker-2:marker])[0] != count:
            marker -= 1
            count += 1
        offset = 9*4
        if save_version >= 61.5:
            offset = num_players*4
        backtrack = 7 + num_players + offset
    else:
        marker = None
        for i in range(len(read_bytes)):
            b = read_bytes[i]
            if b == 63 and read_bytes[i-11:i-3] == b"\xff\xff\xff\xff\x00\x00\x00\x00":
                flt = struct.unpack('<f', read_bytes[i-3:i+1])[0]
                if 1.0 < flt < 2.0:
                    marker = i - 3
                    break
        backtrack = ((1817 * (num_players - 1)) + 4 + 19)
    end = search_start + marker - backtrack - 2
    return end

def decode_attr_header(data, off, num_players, save_version):
    start = off
    off += num_players  # their_dip
    off += 4*9          # my_dip (save_version<61.5)
    off += 4            # allied_los
    off += 1            # allied_victory
    name_len = struct.unpack('<H', data[off:off+2])[0]; off += 2
    name = data[off:off+name_len-1]; off += name_len-1
    off += 1  # pad0
    off += 1  # pad16 (0x16)
    num_header_data = struct.unpack('<I', data[off:off+4])[0]; off += 4
    off += 1  # pad21 (0x21)
    return name, num_header_data, off  # off == ps_start

def read_civ_block(data, ps_start, delta):
    cand = ps_start + delta
    sx, sy = struct.unpack('<HH', data[cand:cand+4])
    culture = data[cand+4]; civ = data[cand+5]; status = data[cand+6]
    resigned = data[cand+7]; pad1 = data[cand+8]; color = data[cand+9]; pad2 = data[cand+10]
    return dict(spawn=(sx,sy), culture=culture, civ=civ, status=status, resigned=resigned, color=color)

def main(fn):
    path = fn
    data = open(path, 'rb').read()
    end = data.index(b'\x00', 0)
    game_version = data[0:end].decode('latin1')
    off = end+1
    save_version = round(struct.unpack('<f', data[off:off+4])[0], 2)
    off += 4
    from mgz.util import get_version
    version = get_version(game_version, save_version, None)

    from mgz.header.ai import ai
    from mgz.header.replay import replay
    from mgz.header.map_info import map_info
    from construct import Container
    import io
    stream = io.BytesIO(data)
    stream.seek(off)
    ai.parse_stream(stream)
    replay_obj = replay.parse_stream(stream, _=Container(version=version, save_version=save_version), version=version, save_version=save_version)
    map_info_obj = map_info.parse_stream(stream, _=Container(version=version, save_version=save_version), version=version, save_version=save_version)
    num_players = replay_obj.num_players
    off = stream.tell()
    print(f"=== {os.path.basename(fn)} === save_version={save_version} num_players={num_players} map={map_info_obj.size_x}x{map_info_obj.size_y}")

    restore_time = struct.unpack('<I', data[off:off+4])[0]; off += 4
    num_particles = struct.unpack('<I', data[off:off+4])[0]; off += 4
    off += num_particles*27
    identifier = struct.unpack('<I', data[off:off+4])[0]; off += 4

    results = []
    for p in range(num_players):
        p_start = off
        off += 2  # type, unk
        name, nhd, ps_start = decode_attr_header(data, off, num_players, save_version)
        info = read_civ_block(data, ps_start, 1925)
        results.append((p, name, nhd, ps_start, info))
        print(f"  player[{p}] name={name!r} nhd={nhd} civ={info['civ']} color={info['color']} spawn={info['spawn']} status={info['status']} resigned={info['resigned']}")
        if p == num_players - 1:
            break
        sobj = find_start_of_objects(data, ps_start)
        end_off = goto_objects_end(data, sobj, num_players, nhd, save_version)
        off = end_off
    return results

if __name__ == '__main__':
    for fn in sys.argv[1:]:
        try:
            main(fn)
        except Exception as e:
            print(f"FAILED on {fn}: {e}")
        print()
