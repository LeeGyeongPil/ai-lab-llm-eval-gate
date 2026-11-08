"""AC-7·AC-8: 요청 형식, 환경변수 반영, 생각 제거, 녹화→재생 왕복. 실제 모델 없이 HTTP 스텁 서버로 검증한다."""

import json

import pytest

from evalgate import cli
from evalgate.config import load_config
from evalgate.providers import CassetteMiss, CassetteProvider, HttpProvider, RecordingProvider, make_provider, request_key, strip_think

REQ = {"model": "m1", "messages": [{"role": "user", "content": "안녕"}], "temperature": 0.6, "top_p": 0.95, "seed": 5, "max_tokens": 50}


def test_request_key_is_stable_and_sensitive():
    assert request_key("chat", REQ) == request_key("chat", dict(reversed(list(REQ.items()))))  # 키 순서 무관
    assert request_key("chat", REQ) != request_key("chat", {**REQ, "seed": 6})
    assert request_key("chat", REQ, 0) != request_key("chat", REQ, 1)


def test_strip_think():
    assert strip_think("생각...\n</think>\n최종 답\n") == "최종 답"
    assert strip_think("  그냥 답  ") == "그냥 답"


def test_http_request_format_and_reasoning_not_in_answer(stub):
    http = HttpProvider(stub.url, "k-123", timeout=5)
    out = http.chat(REQ)
    sent = stub.requests[0]
    assert sent["path"] == "/v1/chat/completions" and sent["auth"] == "Bearer k-123"
    assert sent["body"]["model"] == "m1" and sent["body"]["seed"] == 5
    assert out == "분류: 배송\n결제 후 2영업일 이내 출고됩니다." and "숨은 생각" not in out


def test_env_override_and_think_strip(stub, project, monkeypatch):
    monkeypatch.setenv("EVALGATE_BASE_URL", stub.url)
    monkeypatch.setenv("EVALGATE_MODEL", "other-model")
    monkeypatch.setenv("EVALGATE_API_KEY", "env-key")
    cfg = load_config("evalgate.toml", {"run": {"mode": "real"}})
    provider = make_provider(cfg)
    req = {**REQ, "model": cfg["model"]["name"], "messages": [{"role": "user", "content": "THINK 테스트"}]}
    assert provider.chat(req) == "분류: 배송\n최종 답"  # </think> 앞부분 제거
    sent = stub.requests[-1]
    assert sent["body"]["model"] == "other-model" and sent["auth"] == "Bearer env-key"
    assert cfg["model"]["judge"] == "other-model"  # 심판 모델 기본값은 피평가 모델을 따라간다


def test_record_then_replay_roundtrip(stub, tmp_path):
    path = tmp_path / "c.jsonl"
    rec = RecordingProvider(HttpProvider(stub.url, "k", 5), path)
    a = rec.chat(REQ)
    v = rec.embed({"model": "e", "input": "텍스트"})
    assert rec.chat(REQ) == a  # 이미 녹화된 키는 다시 부르지 않는다
    assert len(stub.requests) == 2
    mock = CassetteProvider(path)
    assert mock.chat(REQ) == a and mock.embed({"model": "e", "input": "텍스트"}) == v
    assert v[2] == 0.123457  # 소수 6자리 반올림
    entry = json.loads(path.read_text().splitlines()[0])
    assert "숨은 생각" not in json.dumps(entry, ensure_ascii=False)  # 생각 과정은 저장하지 않는다
    with pytest.raises(CassetteMiss) as e:
        mock.chat({**REQ, "seed": 99}, label="c03 반복1 생성")
    assert "--mode record" in str(e.value) and "c03" in str(e.value)


def test_http_failure_is_provider_error_with_timeout():
    from evalgate.providers import ProviderError
    http = HttpProvider("http://127.0.0.1:9/v1", "k", timeout=1)
    http.RETRIES = 0
    with pytest.raises(ProviderError):
        http.chat(REQ)


def test_record_cli_then_mock_gives_same_scores(stub, project, monkeypatch, capsys):
    """CLI 전체 왕복(AC-7): 스텁으로 record → 같은 명령을 mock 으로 → 같은 점수. 녹화에 없는 프롬프트는 exit 2."""
    (project / "cassettes" / "qwen3-4b.jsonl").unlink()
    monkeypatch.setenv("EVALGATE_BASE_URL", stub.url)
    assert cli.main(["run", "--mode", "record", "--prompt", "prompts/baseline.txt", "--repeats", "1", "--name", "rec"]) == 0
    rec = json.loads((project / "reports" / "rec.json").read_text())
    n_calls = len(stub.requests)
    assert n_calls > 0
    assert cli.main(["run", "--mode", "mock", "--prompt", "prompts/baseline.txt", "--repeats", "1", "--name", "rep"]) == 0
    rep = json.loads((project / "reports" / "rep.json").read_text())
    assert len(stub.requests) == n_calls  # mock 은 서버를 부르지 않는다
    assert rec["summary"] == rep["summary"]
    capsys.readouterr()
    assert cli.main(["run", "--mode", "mock", "--prompt", "prompts/regressed.txt", "--repeats", "1"]) == 2
    assert "--mode record" in capsys.readouterr().err


def test_record_warns_when_every_request_was_already_recorded(stub, project, monkeypatch, capsys):
    """예시 녹화를 그대로 둔 채 record 를 돌리면 모델을 부르지 않는다 — 성공처럼 보이지 않게 경고한다."""
    monkeypatch.setenv("EVALGATE_BASE_URL", stub.url)
    assert cli.main(["run", "--mode", "record", "--prompt", "prompts/baseline.txt", "--repeats", "2", "--name", "rec"]) == 0
    captured = capsys.readouterr()
    assert "경고: 모델을 한 번도 부르지 않았습니다" in captured.err
    assert len(stub.requests) == 0
