"""AC-1·2·4·5·9: mock 모드 종단 테스트. 저장소에 커밋된 실제 녹화로 전체 경로(생성→채점→집계→기준선→게이트→보고서)를 돈다."""

import json
import re
import socket
import time

import pytest

from evalgate import cli
from conftest import ROOT


def test_demo_exit0_and_outputs(project, capsys):
    t0 = time.time()
    assert cli.main(["demo"]) == 0
    out = capsys.readouterr().out
    for word in ("baseline", "improved", "regressed", "FAIL", "PASS"):
        assert word in out
    assert (project / "reports" / "demo.html").is_file()
    assert time.time() - t0 < 60


def block_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("mock 모드에서 네트워크를 쓰면 안 됩니다")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)


def test_mock_is_deterministic_and_offline(project, monkeypatch):
    block_network(monkeypatch)
    for name in ("a", "b"):
        assert cli.main(["run", "--mode", "mock", "--prompt", "prompts/improved.txt", "--name", name]) == 0
    a = json.loads((project / "reports" / "a.json").read_text())
    b = json.loads((project / "reports" / "b.json").read_text())
    a.pop("generated_at"), b.pop("generated_at")
    assert a == b


@pytest.mark.parametrize("prompt,code", [("baseline", 0), ("improved", 0), ("regressed", 1)])
def test_gate_exit_codes(project, capsys, prompt, code):
    rc = cli.main(["run", "--mode", "mock", "--prompt", f"prompts/{prompt}.txt", "--gate"])
    out = capsys.readouterr().out
    assert rc == code
    if code == 1:
        assert re.search(r"지표 \w+: \d\.\d\d < 하한 \d\.\d\d", out)


def test_missing_cassette_is_exit_2(project, capsys):
    p = project / "prompts" / "new.txt"
    p.write_text("완전히 새로운 프롬프트", encoding="utf-8")
    assert cli.main(["run", "--mode", "mock", "--prompt", "prompts/new.txt", "--gate"]) == 2
    err = capsys.readouterr().err
    assert "녹화에 없는 요청" in err and "--mode record" in err


@pytest.mark.parametrize("flag,value", [("--repeats", "0"), ("--repeats", "-1"), ("--workers", "0")])
def test_nonpositive_repeats_workers_is_exit_2(project, capsys, flag, value):
    rc = cli.main(["--lang", "en", "run", "--mode", "mock", flag, value, "--gate"])
    cap = capsys.readouterr()
    assert rc == 2
    assert cap.err.startswith("Error:") and "1 or more" in cap.err and "Traceback" not in cap.err
    assert cap.out == ""
    reports = project / "reports"
    assert not reports.exists() or not list(reports.iterdir())


def test_workers_env_zero_is_exit_2(project, monkeypatch, capsys):
    monkeypatch.setenv("EVALGATE_WORKERS", "0")
    assert cli.main(["--lang", "en", "run", "--mode", "mock"]) == 2
    assert "run.workers" in capsys.readouterr().err


def test_gate_and_baseline_commands(project, capsys):
    cli.main(["run", "--mode", "mock", "--prompt", "prompts/regressed.txt", "--name", "latest"])
    assert cli.main(["gate"]) == 1
    assert cli.main(["baseline"]) == 2  # 실패 결과는 기준선이 될 수 없다
    cli.main(["run", "--mode", "mock", "--prompt", "prompts/improved.txt", "--name", "latest"])
    assert cli.main(["gate"]) == 0
    assert cli.main(["baseline"]) == 0
    assert json.loads((project / "evals" / "baseline.json").read_text())["prompt_file"] == "improved.txt"


def test_github_annotations_and_step_summary(project, monkeypatch, capsys):
    summary = project / "reports" / "summary.md"
    summary.parent.mkdir()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert cli.main(["run", "--mode", "mock", "--prompt", "prompts/regressed.txt", "--gate"]) == 1
    assert "::error" in capsys.readouterr().out
    text = summary.read_text()
    assert "| 지표 |" in text and "FAIL" in text


def test_report_self_contained(project):
    cli.main(["demo"])
    html = (project / "reports" / "demo.html").read_text()
    assert not re.search(r'(src|href)="https?:', html) and "http://" not in html and "https://" not in html
    assert "<link" not in html and "<script" not in html and "@import" not in html and "url(" not in html
    for marker in ('id="summary"', 'id="chart"', "<svg", 'class="metric"', 'class="case-row"', "새로 실패", "채점기 불일치", "심판:"):
        assert marker in html
    assert html.count("<html") == 1


def test_workflows_have_required_steps():
    wf = (ROOT / ".github" / "workflows" / "eval-gate.yml").read_text()
    for needle in ("pytest", "--mode mock", "--gate", "prompts/regressed.txt", "upload-artifact", "actionlint", "gitleaks"):
        assert needle in wf
    assert "secrets." not in wf  # 비밀값 없이 돈다
    assert "workflow_dispatch" in (ROOT / ".github" / "workflows" / "regression-demo.yml").read_text()


def _elsewhere(project, tmp_path_factory, monkeypatch):
    """프로젝트 복사본 밖의 빈 폴더로 이동하고, 설정 파일 경로를 돌려준다."""
    other = tmp_path_factory.mktemp("elsewhere")
    monkeypatch.chdir(other)
    return project / "evalgate.toml", other


def test_config_in_other_folder_run_and_demo(project, tmp_path_factory, monkeypatch):
    cfg, _ = _elsewhere(project, tmp_path_factory, monkeypatch)
    assert cli.main(["--config", str(cfg), "run", "--mode", "mock", "--gate"]) == 0
    assert cli.main(["--config", str(cfg), "demo"]) == 0


def test_prompt_flag_is_relative_to_cwd(project, tmp_path_factory, monkeypatch):
    cfg, other = _elsewhere(project, tmp_path_factory, monkeypatch)
    (other / "mine.txt").write_text((project / "prompts" / "baseline.txt").read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["--config", str(cfg), "run", "--mode", "mock", "--prompt", "mine.txt"]) == 0
    assert cli.main(["--config", str(cfg), "run", "--mode", "mock", "--prompt", "prompts/baseline.txt"]) == 2


@pytest.mark.parametrize("lang,text", [("en", "Prompt file not found:"), ("ko", "프롬프트 파일이 없습니다:")])
def test_missing_prompt_file_is_translated_exit_2(project, capsys, lang, text):
    rc = cli.main(["--lang", lang, "run", "--mode", "mock", "--prompt", "prompts/nope.txt"])
    err = capsys.readouterr().err
    assert rc == 2 and text in err and "[Errno" not in err
