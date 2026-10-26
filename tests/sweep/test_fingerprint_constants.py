"""Tip behavior constants from upstream #90."""

from slskd_importer.sweep.fingerprint import FAR_SIMILARITY, SAME_RECORDING_SIMILARITY


def test_far_below_same():
    assert FAR_SIMILARITY == 0.6
    assert SAME_RECORDING_SIMILARITY == 0.85
    assert FAR_SIMILARITY < SAME_RECORDING_SIMILARITY
