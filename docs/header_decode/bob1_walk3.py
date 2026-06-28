"""
Use mgz's own GotoObjectsEnd heuristic (regex-based, not dependent on full object parsing)
to skip from one player's objects to the next player's attributes block, for ALL players,
manually decoding `attributes` fields up to player_name/civilization/player_color (which
is everything we need) while AVOIDING player_stats's fixed-size assumption -- instead we
locate camera_x/spawn_location/civilization/player_color by finding the *next* player's
construct marker independently, via GotoObjectsEnd's own marker-search logic ported here.
"""
import sys, os, struct, io, re
sys.path.insert(0, os.path.dirname(__file__))
from decompress import get_header

from mgz.util import get_version, get_save_version

FOLDER = r"D:\Program Files (x86)\Microsoft Games\Age of Empires II\Voobly Mods\AOC\Data Mods\v1.6 Game Data\SaveGame"

START_OF_OBJECTS_MARKER = re.compile(re.escape(b'\x0b\x00').replace(b'\\\x0b\\\x00', b'\x0b\x00') )

def find_start_of_objects(data, off):
    """Replicates mgz Find([b'\\x0b\\x00.\\x00\\x00\\x00\\x02\\x00\\x00'], None) -- regex with '.' wildcard."""
    pattern = re.compile(rb'\x0b\x00.\x00\x00\x00\x02\x00\x00', re.DOTALL)
    m = pattern.search(data, off)
    if not m:
        return None
    return m.end()

def goto_objects_end(data, search_start, num_players, marker_num, save_version, is_last_guess_backtrack=None):
    """Port of mgz.util.GotoObjectsEnd._parse logic (regex-based heuristic)."""
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

def decode_attributes(data, off, num_players, save_version, version):
    """Decode just the header part of `attributes`: diplomacy arrays, name, num_header_data.
    Returns (dict_of_fields, offset_after_num_header_data_and_pad21).
    """
    start = off
    their_dip = data[off:off+num_players]; off += num_players
    n_mydip = num_players if save_version >= 61.5 else 9
    my_dip = struct.unpack(f'<{n_mydip}i', data[off:off+4*n_mydip]); off += 4*n_mydip
    allied_los = struct.unpack('<I', data[off:off+4])[0]; off += 4
    allied_victory = data[off]; off += 1
    name_len = struct.unpack('<H', data[off:off+2])[0]; off += 2
    name = data[off:off+name_len-1]; off += (name_len-1)
    off += 1  # pad 0x00
    pad16 = data[off]; off += 1
    num_header_data = struct.unpack('<I', data[off:off+4])[0]; off += 4
    pad21 = data[off]; off += 1
    return {
        'name': name, 'name_len': name_len, 'num_header_data': num_header_data,
        'pad16': pad16, 'pad21': pad21, 'allied_los': allied_los, 'allied_victory': allied_victory,
        'player_stats_start': off
    }, off

def main(fn):
    path = os.path.join(FOLDER, fn)
    data, start, raw, header_len = get_header(path)

    end = data.index(b'\x00', 0)
    game_version = data[0:end].decode('latin1')
    off = end+1
    save_version = round(struct.unpack('<f', data[off:off+4])[0], 2)
    off += 4
    version = get_version(game_version, save_version, None)
    print(f"=== {fn} === game_version={game_version} save_version={save_version} version={version}")

    from mgz.header.ai import ai
    from mgz.header.replay import replay
    from mgz.header.map_info import map_info
    from construct import Container
    stream = io.BytesIO(data)
    stream.seek(off)
    ai.parse_stream(stream)
    replay_obj = replay.parse_stream(stream, _=Container(version=version, save_version=save_version), version=version, save_version=save_version)
    map_info_obj = map_info.parse_stream(stream, _=Container(version=version, save_version=save_version), version=version, save_version=save_version)
    num_players = replay_obj.num_players
    off = stream.tell()

    restore_time = struct.unpack('<I', data[off:off+4])[0]; off += 4
    num_particles = struct.unpack('<I', data[off:off+4])[0]; off += 4
    off += num_particles*27
    identifier = struct.unpack('<I', data[off:off+4])[0]; off += 4
    print(f"num_players(incl GAIA)={num_players} restore_time={restore_time} identifier={identifier} players_start={hex(off)}")

    for p in range(num_players):
        p_start = off
        ptype = data[off]; off += 1
        unk = data[off]; off += 1
        attr_fields, off = decode_attributes(data, off, num_players, save_version, version)
        print(f"\nplayer[{p}] @ {hex(p_start)} type={ptype} unk={unk}")
        print(f"  name={attr_fields['name']!r} num_header_data={attr_fields['num_header_data']} pad16={attr_fields['pad16']:#x} pad21={attr_fields['pad21']:#x}")

        # Find the start_of_objects marker for THIS player from current offset
        sobj = find_start_of_objects(data, off)
        if sobj is None:
            print("  could not find start_of_objects marker, aborting")
            break
        print(f"  start_of_objects ends at {hex(sobj)} (player_stats+camera+spawn+civ+color region was {sobj-off} bytes)")

        if p == num_players - 1:
            print("  (last player -- no more to decode)")
            break

        # Use GotoObjectsEnd heuristic to jump to next player's attributes start
        next_marker_num = None  # we don't know next player's num_header_data yet; mgz uses CURRENT player's num_header_data per its own code (ctx.attributes.num_header_data is THIS player's)
        marker_num = attr_fields['num_header_data']
        end_off = goto_objects_end(data, sobj, num_players, marker_num, save_version)
        print(f"  GotoObjectsEnd heuristic -> next player attributes/type-byte should start at {hex(end_off)}")
        off = end_off

if __name__ == '__main__':
    for fn in sys.argv[1:]:
        main(fn)
        print()
