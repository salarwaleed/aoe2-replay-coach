"""The civ-id table must follow AoC *release* order (not alphabetical) to match
the byte this Voobly build encodes in replay headers. This regression guards
the exact bug that was fixed after live ground-truth verification."""
from pipeline.civ_ids import CIV_ID_TO_NAME


def test_release_order_anchors():
    # Verified against aocref reference data + live test matches.
    assert CIV_ID_TO_NAME[1] == "Britons"      # NOT "Aztecs" (the old alpha bug)
    assert CIV_ID_TO_NAME[2] == "Franks"
    assert CIV_ID_TO_NAME[15] == "Aztecs"      # confirmed live via Elite Eagle Warrior
    assert CIV_ID_TO_NAME[29] == "Malay"       # confirmed live by the recording player


def test_table_is_contiguous_0_to_45():
    for i in range(0, 46):
        assert i in CIV_ID_TO_NAME, f"missing civ id {i}"
        assert CIV_ID_TO_NAME[i].strip(), f"empty name for civ id {i}"
