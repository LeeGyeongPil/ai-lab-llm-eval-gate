"""AC-6: 평균·표준오차(케이스 군집)·기준선 대비 변화·잡음 판정."""

import math

from evalgate import gate, stats


def samples(table):
    """table = {케이스: [반복별 점수...]} → 샘플 목록(지표 하나 m)."""
    return [{"case": c, "repeat": i, "answer": "", "scores": {"m": {"score": v, "detail": ""}}}
            for c, vals in table.items() for i, v in enumerate(vals)]


def test_mean_and_clustered_stderr_with_repeats():
    s = stats.summarize(samples({"a": [1, 1], "b": [0, 1], "c": [0, 0], "d": [1, 1]}))  # 케이스 평균 1, .5, 0, 1
    m = s["metrics"]["m"]
    assert math.isclose(m["mean"], 0.625)
    case_means = [1, 0.5, 0, 1]
    sd = (sum((x - 0.625) ** 2 for x in case_means) / 3) ** 0.5
    assert math.isclose(m["se"], sd / 2)  # 반복 횟수가 아니라 케이스 수(4)로 나눈다


def test_change_inside_noise_is_flagged():
    base = stats.summarize(samples({"a": [1, 1], "b": [1, 0], "c": [0, 1], "d": [1, 1]}))
    cur = stats.summarize(samples({"a": [1, 1], "b": [1, 1], "c": [0, 1], "d": [1, 0]}))  # 평균은 같고 케이스만 바뀜
    cmp = stats.compare(cur, base)["metrics"]["m"]
    assert cmp["same"] and not cmp["noise"]


def test_small_delta_is_noise_and_large_delta_is_not():
    base = stats.summarize(samples({c: [v, v] for c, v in zip("abcdefgh", [1, 1, 1, 1, 0, 0, 1, 0])}))
    noisy = stats.summarize(samples({c: [v, v] for c, v in zip("abcdefgh", [1, 1, 1, 1, 1, 0, 1, 0])}))  # 한 케이스만 상승
    assert stats.compare(noisy, base)["metrics"]["m"]["noise"] is True
    big = stats.summarize(samples({c: [0, 0] for c in "abcdefgh"}))
    c = stats.compare(big, base)["metrics"]["m"]
    assert c["delta"] < 0 and c["noise"] is False


def test_new_fail_and_new_pass_cases():
    base = stats.summarize(samples({"a": [1, 1], "b": [0, 0]}))
    cur = stats.summarize(samples({"a": [0, 0], "b": [1, 1]}))
    flips = stats.compare(cur, base)["cases"]
    assert flips["a"] == {"m": "new_fail"} and flips["b"] == {"m": "new_pass"}


def test_gate_floor_and_drop_messages():
    base = stats.summarize(samples({"a": [1, 1], "b": [1, 1]}))
    cur = stats.summarize(samples({"a": [0, 0], "b": [1, 0]}))  # 평균 0.25
    cmp = stats.compare(cur, base)
    fails = gate.evaluate(cur, cmp, {"min_scores": {"m": 0.85}, "max_drop": 0.2})
    assert any("지표 m: 0.25 < 하한 0.85" in f for f in fails)
    assert any("허용 하락폭" in f for f in fails)
    assert gate.evaluate(base, stats.compare(base, base), {"min_scores": {"m": 0.85}, "max_drop": 0.2}) == []
