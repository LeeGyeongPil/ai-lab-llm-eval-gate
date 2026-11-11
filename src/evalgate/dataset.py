"""평가 세트(JSONL) 로드와 검증. 한 줄 = 한 케이스.

케이스 형식:
  {"id": "c01", "input": "문의 문장",
   "expected": {"label": "...", "facts": "...", "reference": "..."},   # 채점기가 꺼내 쓰는 값들
   "scorers": ["format", "label", "judge"]}                            # evalgate.toml 의 채점기 이름
"""

import json
from pathlib import Path

from .i18n import LocalizedError


class DatasetError(LocalizedError):
    """평가 세트 오류 (메시지 코드+파라미터)."""


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
                raise DatasetError("ds_json", path=str(path), line=lineno, error=str(e)) from e
            for field in ("id", "input", "scorers"):
                if field not in case:
                    raise DatasetError("ds_field", path=str(path), line=lineno, field=field)
            case.setdefault("expected", {})
            if case["id"] in seen:
                raise DatasetError("ds_dup", path=str(path), line=lineno, id=case["id"])
            seen.add(case["id"])
            unknown = [s for s in case["scorers"] if s not in scorer_names]
            if unknown:
                raise DatasetError("ds_unknown_scorer", path=str(path), line=lineno, names=str(unknown))
            cases.append(case)
    if not cases:
        raise DatasetError("ds_empty", path=str(path))
    return cases
