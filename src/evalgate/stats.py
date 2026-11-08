"""집계: 지표별 평균·표준오차, 기준선 대비 변화, 잡음 판정.

표준오차는 케이스 단위로 계산한다(Miller 2024 "Adding Error Bars to Evals"의 군집 표준오차):
  1) 케이스마다 반복 점수를 평균 → 케이스 점수
  2) 케이스 점수들의 표본 표준편차 / sqrt(케이스 수)
같은 케이스를 여러 번 돌린 것은 독립 표본이 아니므로 반복 횟수로 나누면 오차를 과소평가한다.
"""

import math
import statistics

PASS_LINE = 0.5  # 케이스 평균이 이 값 이상이면 그 지표에서 "통과"로 본다(새로 실패/새로 통과 판정용)


def case_scores(samples: list[dict]) -> dict[str, dict[str, float]]:
    """{케이스: {지표: 반복 평균}}"""
    acc: dict[str, dict[str, list[float]]] = {}
    for s in samples:
        for metric, r in s["scores"].items():
            acc.setdefault(s["case"], {}).setdefault(metric, []).append(r["score"])
    return {c: {m: sum(v) / len(v) for m, v in ms.items()} for c, ms in acc.items()}


def stderr(values: list[float]) -> float:
    return statistics.stdev(values) / math.sqrt(len(values)) if len(values) >= 2 else 0.0


def summarize(samples: list[dict]) -> dict:
    """{"metrics": {지표: {mean, se, n}}, "cases": {케이스: {지표: 점수}}}"""
    cases = case_scores(samples)
    by_metric: dict[str, list[float]] = {}
    for scores in cases.values():
        for m, v in scores.items():
            by_metric.setdefault(m, []).append(v)
    metrics = {m: {"mean": sum(v) / len(v), "se": stderr(v), "n": len(v)} for m, v in by_metric.items()}
    return {"metrics": metrics, "cases": cases}


def compare(summary: dict, baseline: dict | None) -> dict:
    """기준선 대비 지표별 변화와 케이스별 새로 실패/새로 통과.

    delta     = 현재 평균 - 기준선 평균
    noise     = |delta| ≤ 2 × (같은 케이스끼리 짝지은 차이의 표준오차) 이면 True → "잡음 범위"
    """
    out = {"metrics": {}, "cases": {}}
    if not baseline:
        return out
    for m, cur in summary["metrics"].items():
        base = baseline.get("metrics", {}).get(m)
        if base is None:
            continue
        diffs = [summary["cases"][c][m] - baseline["cases"][c][m]
                 for c in summary["cases"] if c in baseline.get("cases", {}) and m in summary["cases"][c] and m in baseline["cases"][c]]
        delta = cur["mean"] - base["mean"]
        se_diff = stderr(diffs)
        out["metrics"][m] = {"baseline": base["mean"], "delta": delta, "se_diff": se_diff,
                             "same": abs(delta) < 1e-9, "noise": abs(delta) >= 1e-9 and abs(delta) <= 2 * se_diff}
    for c, scores in summary["cases"].items():
        flips = {}
        for m, v in scores.items():
            b = baseline.get("cases", {}).get(c, {}).get(m)
            if b is None:
                continue
            if b >= PASS_LINE > v:
                flips[m] = "new_fail"
            elif v >= PASS_LINE > b:
                flips[m] = "new_pass"
        if flips:
            out["cases"][c] = flips
    return out
