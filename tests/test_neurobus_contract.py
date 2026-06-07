from aegis.nexus.neurobus import NeuroState


EXPECTED_VEC_LEN = 6
EXPECTED_REWARD_CLAMPED = 1.0
EXPECTED_THREAT_CLAMPED = -1.0


def test_neurostate_vec_length():
    assert len(NeuroState().vec()) == EXPECTED_VEC_LEN


def test_neurostate_clamp_bounds():
    s = NeuroState(reward=9.0, threat=-9.0)
    s.clamp()
    assert s.reward == EXPECTED_REWARD_CLAMPED
    assert s.threat == EXPECTED_THREAT_CLAMPED
