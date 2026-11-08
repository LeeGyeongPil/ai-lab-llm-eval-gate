"""AC-3: 채점기 5종과 정규화·심판 파서."""

from evalgate.scorers import cosine, normalize, parse_judge, run_scorer

CASE = {"id": "t1", "input": "문의", "expected": {"label": "배송", "word": "서울", "facts": "사실", "reference": "기준 문장"}}


def ctx(embed=None, chat=None, scorers=None):
    class P:
        def embed(self, req, label=""):
            return embed[req["input"]]

        def chat(self, req, repeat=0, label=""):
            return chat

    cfg = {"scorers": scorers or {}, "model": {"embed": "e", "judge": "j", "temperature": 0.6, "top_p": 0.95, "judge_seed": 7, "max_tokens": 100}}
    return {"cfg": cfg, "provider": P(), "repeat": 0}


def test_normalize_handles_markdown_punctuation_and_subscripts():
    assert normalize("**서울**입니다.") == normalize("서울입니다")
    assert normalize("H₂O") == normalize("h2o")
    assert normalize("  Hello,\n World! ") == "helloworld"


def test_exact_with_normalization():
    sc = {"x": {"type": "exact", "expected": "word"}}
    assert run_scorer("x", CASE, "**서울**.", ctx(scorers=sc))["score"] == 1.0
    assert run_scorer("x", CASE, "부산", ctx(scorers=sc))["score"] == 0.0


def test_exact_with_extract_regex():
    sc = {"x": {"type": "exact", "extract": r"\A\s*분류\s*:\s*(\S+)", "expected": "label"}}
    assert run_scorer("x", CASE, "분류: 배송\n답변", ctx(scorers=sc))["score"] == 1.0
    assert run_scorer("x", CASE, "분류: 환불\n답변", ctx(scorers=sc))["score"] == 0.0
    r = run_scorer("x", CASE, "형식 없는 답", ctx(scorers=sc))
    assert r["score"] == 0.0 and "추출 실패" in r["detail"]


def test_regex_and_contains():
    sc = {"r": {"type": "regex", "pattern": r"\A분류: (배송|환불)\n"}, "c": {"type": "contains", "expected": "word"}}
    assert run_scorer("r", CASE, "분류: 배송\nx", ctx(scorers=sc))["score"] == 1.0
    assert run_scorer("r", CASE, "분류: 기타\nx", ctx(scorers=sc))["score"] == 0.0
    assert run_scorer("c", CASE, "여기는 **서울** 입니다", ctx(scorers=sc))["score"] == 1.0
    assert run_scorer("c", CASE, "부산", ctx(scorers=sc))["score"] == 0.0


def test_similarity_threshold_and_strip():
    sc = {"s": {"type": "similarity", "reference": "reference", "threshold": 0.9, "strip": r"\A분류:[^\n]*\n?"}}
    emb = {"본문": [1.0, 0.0], "기준 문장": [1.0, 0.1], "먼 본문": [0.0, 1.0]}
    assert cosine([1, 0], [0, 1]) == 0.0
    assert run_scorer("s", CASE, "분류: 배송\n본문", ctx(embed=emb, scorers=sc))["score"] == 1.0  # cos≈0.995
    assert run_scorer("s", CASE, "먼 본문", ctx(embed=emb, scorers=sc))["score"] == 0.0
    assert run_scorer("s", CASE, "분류: 배송\n", ctx(embed=emb, scorers=sc))["detail"] == "빈 답변"


def test_judge_pass_fail_and_parse_error():
    assert parse_judge("판정: PASS\n이유: 맞음") == (1.0, "PASS: 맞음")
    assert parse_judge("판정: FAIL\n이유: 틀림")[0] == 0.0
    assert parse_judge("PASS")[0] == 1.0
    score, detail = parse_judge("글쎄요, 잘 모르겠습니다")  # PASS/FAIL 외 응답
    assert score == 0.0 and detail.startswith("parse_error")
    score, detail = parse_judge("")
    assert score == 0.0 and detail.startswith("parse_error")


def test_judge_scorer_uses_provider_and_records_parse_error():
    sc = {"j": {"type": "judge", "criteria": "facts", "reference": "reference"}}
    assert run_scorer("j", CASE, "답", ctx(chat="판정: PASS\n이유: ok", scorers=sc))["score"] == 1.0
    r = run_scorer("j", CASE, "답", ctx(chat="모르겠음", scorers=sc))
    assert r["score"] == 0.0 and "parse_error" in r["detail"]
    assert run_scorer("j", CASE, "  ", ctx(chat="판정: PASS", scorers=sc))["score"] == 0.0  # 빈 답변은 호출 없이 FAIL
