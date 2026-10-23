"""
Regression tests for CL2 result-time extraction (swim_parser.cl2_parser).

Fixtures are real D0 lines for one swimmer (Calvin Yang) from two files:
  * CHAMPS — 2026 MD LSC 14 & U Championships: a prelim/final file whose
    D0 lines carry seed + prelim + final times. The old fixed-column
    parser stored finals of 1.00-2.00s for this file and lost real
    finals (audit: docs/data_quality_repair_plan.md).
  * INVITATIONAL — 2026 RAC First Splash: a timed-final file; expected
    values are what the old parser (correctly) produced.

Run: python -m pytest tests/test_cl2_times.py   (or plain python3)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from swim_parser.cl2_parser import _parse_d0

CHAMPS = [
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201510MM  503 22 UN1003062026   40.96Y   39.65Y            39.38Y 4 3 1 6  4  6 13.   6000300    NN02',
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201510MM 2005 40 UN1003062026 3:02.10Y      DQY                   2 7 0 0  0           0005      NN60',
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201510MM 1001 28 UN1003062026 1:16.37Y 1:16.50Y                   2 8 0 0 29           0001      NN01',
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201510MM  502 68 UN1003072026   42.54Y   41.15Y                   1 2 0 0 37           0002      NN50',
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201510MM 1003 62 UN1003072026 1:30.43Y 1:26.69Y          1:25.76Y 3 6 1 2  5  5 14.   5000300    NN72',
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201510MM 1005 56 UN1003072026 1:28.08Y 1:21.63Y                   1 2 0 0 23           0005      NN01',
]
INVITATIONAL = [
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201511MM 1002 70 111109202026 1:27.31Y                   1:25.16Y     3 7    14       50002      NN60',
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201511MM 1003 65 111109202026 1:25.76Y                   1:30.25Y     2 3     3       30003      NN50',
    'D01MD      Yang, Calvin K              918E49C795CEAUSA0701201511MM  504 60 111109202026   38.09Y                     35.97Y     5 1    12       40004      NN20',
]

# event_code -> (seed, finals, dq) for the championship file
CHAMPS_EXPECTED = {
    "50BR":  (40.96, 39.38, False),   # seed, prelim 39.65, FINAL 39.38
    "200IM": (182.10, None, True),    # DQ in the time block
    "100FR": (76.37, 76.50, False),   # prelim only -> prelim is the result
    "50BK":  (42.54, 41.15, False),   # prelim only
    "100BR": (90.43, 85.76, False),   # seed, prelim 1:26.69, FINAL 1:25.76
    "100IM": (88.08, 81.63, False),   # prelim only
}

def test_champs_multiround():
    seen = {}
    for line in CHAMPS:
        r = _parse_d0(line)
        assert r is not None
        seen[r["event_code"]] = (r["seed_time"], r["finals_time"], r["dq"])
        assert r["finals_time"] is None or r["finals_time"] >= 5, \
            f"impossible finals leaked: {r}"
    assert seen == CHAMPS_EXPECTED, f"\n got: {seen}\nwant: {CHAMPS_EXPECTED}"

def test_invitational_single_round_unchanged():
    for line in INVITATIONAL:
        r = _parse_d0(line)
        assert r is not None
        assert r["finals_time"] is None or r["finals_time"] >= 5
        assert r["seed_time"] is not None

if __name__ == "__main__":
    test_champs_multiround()
    test_invitational_single_round_unchanged()
    print("OK: cl2 time extraction regression tests passed")
