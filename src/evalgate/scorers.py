"""채점기 5종. 모두 (점수 0~1, 설명) 을 돌려주는 평범한 함수다.

  exact       정규화 후 정확 일치(정규식으로 답변의 일부만 꺼내 비교할 수도 있다)
  regex       정규식이 답변에 맞는가
  contains    기대 문자열이 답변에 들어 있는가(정규화 후)
  similarity  임베딩 코사인 ≥ 임계값 — 주제 이탈 감지용 보조 지표(정반대 뜻도 비슷하게 나오므로 정답 판정엔 쓰지 않는다)
  judge       LLM 심판. 정책 사실과 맞으면 PASS / 아니면 FAIL

새 채점기를 만들려면 score_xxx 함수를 하나 쓰고 SCORERS 사전에 등록하면 된다.
"""

import math
import re
import unicodedata

NORM_DROP = set("*_`~")  # Markdown 강조 기호


def normalize(text: str) -> str:
    """비교용 정규화: 호환 문자 통일(H₂O → H2O, 전각 → 반각), Markdown 강조·공백·구두점 제거, 소문자화."""
    text = unicodedata.normalize("NFKC", text).lower()
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in NORM_DROP or cat[0] in ("P", "Z", "C"):
            continue
        out.append(ch)
    return "".join(out)


def _expected(scorer: dict, case: dict, key: str = "expected") -> str:
    """채점기 설정이 가리키는 케이스의 기대값을 꺼낸다. 없으면 설정 오류로 알린다."""
    field = scorer[key]
    try:
        return str(case["expected"][field])
    except KeyError as e:
        raise KeyError(f"케이스 {case['id']} 의 expected.{field} 가 없습니다") from e


def score_exact(scorer, case, answer, ctx):
    got = answer
    if scorer.get("extract"):
        m = re.search(scorer["extract"], answer)
        if not m:
            return 0.0, "추출 실패(정규식이 맞지 않음)"
        got = m.group(1)
    want = _expected(scorer, case)
    ok = normalize(got) == normalize(want)
    return (1.0 if ok else 0.0), f"{got.strip()[:30]!r} {'==' if ok else '!='} {want!r}"


def score_regex(scorer, case, answer, ctx):
    ok = re.search(scorer["pattern"], answer) is not None
    return (1.0 if ok else 0.0), ("형식 일치" if ok else "형식 불일치")


def score_contains(scorer, case, answer, ctx):
    want = _expected(scorer, case)
    ok = normalize(want) in normalize(answer)
    return (1.0 if ok else 0.0), f"{want!r} {'포함' if ok else '없음'}"


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def score_similarity(scorer, case, answer, ctx):
    text = re.sub(scorer["strip"], "", answer).strip() if scorer.get("strip") else answer.strip()
    if not text:
        return 0.0, "빈 답변"
    model = ctx["cfg"]["model"]["embed"]
    label = f"{case['id']} 임베딩"
    # 텍스트마다 따로 요청해야 같은 기준 문장의 임베딩이 녹화에서 재사용된다
    va = ctx["provider"].embed({"model": model, "input": text}, label=label + "(답변)")
    vb = ctx["provider"].embed({"model": model, "input": _expected(scorer, case, "reference")}, label=label + "(기준)")
    cos = cosine(va, vb)
    return (1.0 if cos >= scorer["threshold"] else 0.0), f"cos={cos:.3f} (임계 {scorer['threshold']})"


JUDGE_PROMPT = """너는 채점자다. 고객 문의, 정책 사실, 봇의 답변을 보고 답변이 정책 사실과 맞는지 판정하라.
- 답변이 정책 사실과 모순되지 않고 핵심을 담고 있으면 PASS, 틀리거나 핵심이 빠졌으면 FAIL.
- 답변의 길이, 말투, '분류:' 줄 같은 형식은 보지 말고 사실 여부만 본다.

고객 문의: {question}
정책 사실: {facts}
참고 모범 답안: {reference}
봇의 답변: {answer}

아래 형식으로만 출력하라.
판정: PASS 또는 FAIL
이유: 한 줄"""

_VERDICT = re.compile(r"판정\s*[:：]\s*\**\s*(PASS|FAIL)\b", re.IGNORECASE)
_REASON = re.compile(r"이유\s*[:：]\s*(.+)")


def parse_judge(text: str) -> tuple[float, str]:
    """심판 응답에서 판정을 읽는다. 읽지 못하면 FAIL + parse_error (점수를 부풀리지 않는다)."""
    m = _VERDICT.search(text) or re.fullmatch(r"\s*\**(PASS|FAIL)\**\s*", text, re.IGNORECASE)
    if not m:
        return 0.0, f"parse_error: {text.strip()[:60]!r}"
    verdict = m.group(1).upper()
    r = _REASON.search(text)
    reason = r.group(1).strip()[:120] if r else ""
    return (1.0 if verdict == "PASS" else 0.0), f"{verdict}: {reason}" if reason else verdict


def score_judge(scorer, case, answer, ctx):
    if not answer.strip():
        return 0.0, "FAIL: 빈 답변"
    m = ctx["cfg"]["model"]
    prompt = JUDGE_PROMPT.format(
        question=case["input"], facts=_expected(scorer, case, "criteria"),
        reference=_expected(scorer, case, "reference"), answer=answer.strip())
    request = {
        "model": m["judge"], "messages": [{"role": "user", "content": prompt}],
        "temperature": m["temperature"], "top_p": m["top_p"],
        "seed": int(m["judge_seed"]) + ctx["repeat"], "max_tokens": m["max_tokens"],
    }
    text = ctx["provider"].chat(request, repeat=ctx["repeat"], label=f"{case['id']} 반복{ctx['repeat'] + 1} 심판")
    return parse_judge(text)


SCORERS = {"exact": score_exact, "regex": score_regex, "contains": score_contains,
           "similarity": score_similarity, "judge": score_judge}


def run_scorer(name: str, case: dict, answer: str, ctx: dict) -> dict:
    scorer = ctx["cfg"]["scorers"][name]
    fn = SCORERS.get(scorer["type"])
    if fn is None:
        raise KeyError(f"알 수 없는 채점기 type: {scorer['type']} ({name})")
    score, detail = fn(scorer, case, answer, ctx)
    return {"score": score, "detail": detail}
