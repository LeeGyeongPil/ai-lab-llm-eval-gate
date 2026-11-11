"""게이트: 집계 결과가 기준을 넘는지 판정한다. 결국 "숫자 비교 + 종료 코드" 뿐이다.

규칙 2개 (evalgate.toml 의 [gate]):
  min_scores  지표별 절대 하한. 평균이 하한보다 낮으면 실패
  max_drop    기준선 대비 허용 하락폭. 기준선보다 이만큼 넘게 떨어지면 실패
"""

import os

from .i18n import t


def evaluate(summary: dict, comparison: dict, gate_cfg: dict, lang: str | None = None) -> list[str]:
    """실패 이유 문장 목록을 돌려준다. 비어 있으면 통과."""
    failures = []
    for metric, floor in gate_cfg.get("min_scores", {}).items():
        cur = summary["metrics"].get(metric)
        if cur is None:
            failures.append(t("gate_missing_metric", lang, metric=metric))
        elif cur["mean"] < floor:
            failures.append(t("gate_floor", lang, metric=metric, value=f"{cur['mean']:.2f}", floor=f"{floor:.2f}"))
    max_drop = gate_cfg.get("max_drop")
    if max_drop is not None:
        for metric in gate_cfg.get("min_scores", {}):
            c = comparison.get("metrics", {}).get(metric)
            if c and -c["delta"] > max_drop + 1e-9:
                failures.append(t("gate_drop", lang, metric=metric, baseline=f"{c['baseline']:.2f}", delta=f"{c['delta']:+.2f}", max_drop=f"{max_drop:.2f}"))
    return failures


def _escape(s: str) -> str:
    """GitHub 워크플로 명령 값 이스케이프(%, 줄바꿈)."""
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def github_annotations(failures: list[str], name: str, lang: str | None = None) -> list[str]:
    """GITHUB_ACTIONS=true 일 때만 ::error 주석 줄을 만든다. Actions 화면에 빨간 주석으로 뜬다."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return []
    title = t("annotation_title", lang, name=_escape(name))
    return [f"::error title={title}::{_escape(f)}" for f in failures]
