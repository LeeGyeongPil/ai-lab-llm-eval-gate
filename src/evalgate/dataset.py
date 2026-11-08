"""평가 세트(JSONL) 로드와 검증. 한 줄 = 한 케이스.

케이스 형식:
  {"id": "c01", "input": "문의 문장",
   "expected": {"label": "...", "facts": "...", "reference": "..."},   # 채점기가 꺼내 쓰는 값들
   "scorers": ["format", "label", "judge"]}                            # evalgate.toml 의 채점기 이름
"""

import json
from pathlib import Path


class DatasetError(Exception):
    pass


def load_cases(path: str | Path, scorer_names: set[str]) -> list[dict]:
    """JSONL 을 읽고 필수 필드·채점기 이름·id 중복을 검사한 케이스 목록을 돌려준다."""
    cases, seen = [], set()
    with Path(path).open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as e:
                raise DatasetError(f"{path}:{lineno} JSON 오류: {e}") from e
            for field in ("id", "input", "scorers"):
                if field not in case:
                    raise DatasetError(f"{path}:{lineno} 필수 필드 없음: {field}")
            case.setdefault("expected", {})
            if case["id"] in seen:
                raise DatasetError(f"{path}:{lineno} id 중복: {case['id']}")
            seen.add(case["id"])
            unknown = [s for s in case["scorers"] if s not in scorer_names]
            if unknown:
                raise DatasetError(f"{path}:{lineno} 정의되지 않은 채점기: {unknown} (evalgate.toml [scorers.*] 확인)")
            cases.append(case)
    if not cases:
        raise DatasetError(f"{path}: 케이스가 없습니다")
    return cases
