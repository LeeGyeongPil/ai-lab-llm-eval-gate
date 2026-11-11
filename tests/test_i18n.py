"""화면 언어(en/ko): 메시지 표 일치, 언어 결정 순서, CLI·오류·보고서의 언어 전환, 불변 항목."""

import json
import re

import pytest

from evalgate import cli
from evalgate.i18n import MESSAGES, LocalizedError, placeholders, resolve_lang, t

HANGUL = re.compile("[가-힣]")


# ── 메시지 표 ─────────────────────────────────────────────────

def test_message_tables_have_identical_keys_and_placeholders():
    en, ko = MESSAGES["en"], MESSAGES["ko"]
    assert set(en) == set(ko)
    for key in en:
        assert placeholders(en[key]) == placeholders(ko[key]), key


def test_english_messages_contain_no_hangul():
    assert [k for k, v in MESSAGES["en"].items() if HANGUL.search(v)] == []


def test_every_message_renders_with_its_placeholders():
    for lang in MESSAGES:
        for key, text in MESSAGES[lang].items():
            t(key, lang, **{name: "x" for name in placeholders(text)})


# ── 언어 결정 순서 ────────────────────────────────────────────

@pytest.mark.parametrize("cli_value,env,expected", [
    ("en", {"EVALGATE_LANG": "ko", "LANG": "ko_KR.UTF-8"}, "en"),            # --lang 이 가장 강하다
    ("ko", {"EVALGATE_LANG": "en", "LC_ALL": "en_US.UTF-8"}, "ko"),
    (None, {"EVALGATE_LANG": "ko", "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"}, "ko"),  # EVALGATE_LANG > LC_ALL
    (None, {"LC_ALL": "ko_KR.UTF-8", "LC_MESSAGES": "en_US.UTF-8", "LANG": "en_US.UTF-8"}, "ko"),  # LC_ALL > LC_MESSAGES
    (None, {"LC_MESSAGES": "ko_KR.UTF-8", "LANG": "en_US.UTF-8"}, "ko"),     # LC_MESSAGES > LANG
    (None, {"LANG": "ko_KR.UTF-8"}, "ko"),
    (None, {"LANG": "ko"}, "ko"),
    (None, {"LANG": "en_US.UTF-8"}, "en"),
    (None, {"LANG": "C"}, "en"),
    (None, {"LANG": "POSIX"}, "en"),
    (None, {"LANG": "ja_JP.UTF-8"}, "en"),
    (None, {"EVALGATE_LANG": "klingon"}, "en"),     # 잘못된 값은 영어
    (None, {"EVALGATE_LANG": "", "LANG": "ko_KR.UTF-8"}, "ko"),  # 빈 값은 "설정 안 함"
    (None, {}, "en"),
])
def test_resolve_lang_priority(cli_value, env, expected):
    assert resolve_lang(cli_value, env) == expected


def test_localized_error_str_is_english_and_render_picks_language():
    e = LocalizedError("cfg_missing", path="x.toml")
    assert str(e) == "Config file not found: x.toml"
    assert e.render("ko") == "설정 파일이 없습니다: x.toml"


# ── 화면 언어 전환 ────────────────────────────────────────────

def run_cli(capsys, *argv):
    rc = cli.main(list(argv))
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_english_demo_has_no_korean_ui_text(project, capsys):
    rc, out, err = run_cli(capsys, "--lang", "en", "demo")
    assert rc == 0
    assert "Gate passed: baseline" in out and "Gate failed: regressed" in out and "Report: reports/demo.html" in out
    assert "floor 0.85" in out and "(± standard error" in out
    assert not HANGUL.search(out) and not HANGUL.search(err)  # 데이터 유래 문구는 demo 출력에 없다


def test_korean_demo_matches_previous_output(project, capsys):
    rc, out, _ = run_cli(capsys, "--lang", "ko", "demo")
    assert rc == 0
    assert "게이트 통과: baseline" in out and "게이트 실패: regressed" in out
    assert "  - 지표 format: 0.00 < 하한 0.85" in out
    assert "evalgate demo — mock 모드(녹화 재생), 케이스 8개 × 반복 2회, 모델 qwen3:4b\n\n" in out
    assert out.rstrip().endswith("보고서: reports/demo.html")


def test_run_summary_in_both_languages(project, capsys):
    _, en, _ = run_cli(capsys, "--lang", "en", "run", "--prompt", "prompts/improved.txt")
    _, ko, _ = run_cli(capsys, "--lang", "ko", "run", "--prompt", "prompts/improved.txt")
    assert en.startswith("Prompt improved — mock mode, 8 cases × 2 repeats, model qwen3:4b")
    assert ko.startswith("프롬프트 improved — mock 모드, 케이스 8개 × 반복 2회, 모델 qwen3:4b")


def test_env_var_selects_language_and_cli_flag_wins(project, monkeypatch, capsys):
    monkeypatch.setenv("EVALGATE_LANG", "en")
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    _, out, _ = run_cli(capsys, "run", "--prompt", "prompts/improved.txt")
    assert out.startswith("Prompt improved")
    _, out, _ = run_cli(capsys, "--lang", "ko", "run", "--prompt", "prompts/improved.txt")
    assert out.startswith("프롬프트 improved")


def test_evalgate_lang_beats_lang(project, monkeypatch, capsys):
    monkeypatch.setenv("EVALGATE_LANG", "ko")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _, out, _ = run_cli(capsys, "run", "--prompt", "prompts/improved.txt")
    assert out.startswith("프롬프트 improved")


def test_lang_falls_back_to_english_without_any_setting(project, monkeypatch, capsys):
    monkeypatch.delenv("EVALGATE_LANG")
    monkeypatch.setenv("LANG", "C")
    _, out, _ = run_cli(capsys, "run", "--prompt", "prompts/improved.txt")
    assert out.startswith("Prompt improved")


@pytest.mark.parametrize("argv", [["--lang", "fr", "demo"], ["--lang=xx", "demo"], ["demo", "--lang", "fr"]])
def test_invalid_lang_value_is_clear_error(project, capsys, argv):
    rc, out, err = run_cli(capsys, *argv)
    assert rc == 2 and out == ""
    assert "--lang" in err and "en" in err and "ko" in err


def test_lang_without_value_is_error(project, capsys):
    rc, _, err = run_cli(capsys, "--lang")
    assert rc == 2 and "--lang" in err


@pytest.mark.parametrize("lang,desc,sub", [
    ("en", "Prompt evaluation gate", "Evaluate one prompt"),
    ("ko", "프롬프트 평가 게이트", "프롬프트 하나를 평가한다"),
])
def test_help_text_follows_language(project, capsys, lang, desc, sub):
    with pytest.raises(SystemExit) as e:
        cli.main(["--lang", lang, "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert desc in out and sub in out and "--lang" in out
    if lang == "en":
        assert not HANGUL.search(out)


def test_github_annotation_format_is_stable_in_both_languages(project, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _, en, _ = run_cli(capsys, "--lang", "en", "run", "--prompt", "prompts/regressed.txt", "--gate")
    _, ko, _ = run_cli(capsys, "--lang", "ko", "run", "--prompt", "prompts/regressed.txt", "--gate")
    assert re.search(r"^::error title=evalgate gate failed \(regressed\)::metric format: 0\.00 < floor 0\.85$", en, re.M)
    assert re.search(r"^::error title=evalgate 게이트 실패 \(regressed\)::지표 format: 0\.00 < 하한 0\.85$", ko, re.M)


# ── 오류 경로: 모든 오류가 두 언어로 나오고 종료 코드 2 ─────────

def _write_cases(project, text):
    (project / "evals" / "cases.jsonl").write_text(text, encoding="utf-8")


def _edit_toml(project, old, new):
    p = project / "evalgate.toml"
    p.write_text(p.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


def _drop_expected(project):
    lines = (project / "evals" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    del first["expected"]
    lines[0] = json.dumps(first, ensure_ascii=False)
    _write_cases(project, "\n".join(lines) + "\n")


def _results_failed(project, monkeypatch):
    cli.main(["run", "--prompt", "prompts/regressed.txt", "--name", "latest"])


def _multi(project, monkeypatch):
    cli.main(["demo"])


ERROR_CASES = {
    "config-missing": (lambda p, m: None, ["--config", "nope.toml", "demo"], "Config file not found: nope.toml", "설정 파일이 없습니다: nope.toml"),
    "env-bad-workers": (lambda p, m: m.setenv("EVALGATE_WORKERS", "abc"), ["demo"], "EVALGATE_WORKERS has an invalid value: 'abc'", "EVALGATE_WORKERS 값이 올바르지 않습니다: 'abc'"),
    "mode-bad": (lambda p, m: m.setenv("EVALGATE_MODE", "bogus"), ["run"], "mode must be one of mock / real / record: 'bogus'", "mode 는 mock / real / record 중 하나여야 합니다: 'bogus'"),
    "cases-json": (lambda p, m: _write_cases(p, "{bad json\n"), ["demo"], "JSON error:", "JSON 오류:"),
    "cases-field": (lambda p, m: _write_cases(p, '{"id": "a", "input": "q"}\n'), ["demo"], "missing required field: scorers", "필수 필드 없음: scorers"),
    "cases-dup": (lambda p, m: _write_cases(p, '{"id": "a", "input": "q", "scorers": ["format"]}\n' * 2), ["demo"], "duplicate id: a", "id 중복: a"),
    "cases-scorer": (lambda p, m: _write_cases(p, '{"id": "a", "input": "q", "scorers": ["nope"]}\n'), ["demo"], "undefined scorer: ['nope']", "정의되지 않은 채점기: ['nope']"),
    "cases-empty": (lambda p, m: _write_cases(p, "\n"), ["demo"], ": no cases", ": 케이스가 없습니다"),
    "results-missing-gate": (lambda p, m: None, ["gate", "--results", "nope.json"], "Results file not found: nope.json (run evalgate run first)", "결과 파일이 없습니다: nope.json (먼저 evalgate run 을 실행하세요)"),
    "results-missing-baseline": (lambda p, m: None, ["baseline", "--results", "nope.json"], "Results file not found: nope.json", "결과 파일이 없습니다: nope.json"),
    "gate-multi": (_multi, ["gate", "--results", "reports/demo.json"], "A multi-prompt results file cannot be used with gate", "여러 프롬프트 결과 파일은 gate 에 쓸 수 없습니다"),
    "baseline-failed": (_results_failed, ["baseline"], "A gate-failed result cannot become the baseline (use --force", "게이트에 실패한 결과는 기준선으로 쓸 수 없습니다(그래도 쓰려면 --force)"),
    "cassette-miss": (lambda p, m: (p / "prompts" / "new.txt").write_text("brand new prompt", encoding="utf-8"),
                      ["run", "--prompt", "prompts/new.txt"], "Request not in the cassette: c01 repeat 1 generate", "녹화에 없는 요청입니다: c01 반복1 생성"),
    "scorer-type": (lambda p, m: _edit_toml(p, 'type = "regex"', 'type = "bogus"'), ["run"], "unknown scorer type: bogus (format)", "알 수 없는 채점기 type: bogus (format)"),
    "expected-missing": (lambda p, m: _drop_expected(p), ["run"], "case c01 has no expected.", "케이스 c01 의 expected."),
}


@pytest.mark.parametrize("name", list(ERROR_CASES))
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_every_error_path_is_localized_with_exit_2(project, monkeypatch, capsys, name, lang):
    setup, argv, en_text, ko_text = ERROR_CASES[name]
    setup(project, monkeypatch)
    capsys.readouterr()
    rc = cli.main(["--lang", lang, *argv])
    err = capsys.readouterr().err
    assert rc == 2
    assert err.startswith("Error: " if lang == "en" else "오류: ")
    assert (en_text if lang == "en" else ko_text) in err
    if lang == "en":
        assert not HANGUL.search(err)  # 영어 모드에서 한국어 안내문이 섞이지 않는다


@pytest.mark.parametrize("lang,prefix", [("en", "Error: "), ("ko", "오류: ")])
def test_oserror_keeps_os_text_and_translates_only_the_prefix(project, capsys, lang, prefix):
    _edit_toml(project, 'cases = "evals/cases.jsonl"', 'cases = "nope.jsonl"')
    rc = cli.main(["--lang", lang, "demo"])
    err = capsys.readouterr().err
    assert rc == 2 and err.startswith(prefix)
    assert "No such file or directory" in err or "nope.jsonl" in err


@pytest.mark.parametrize("lang,prefix", [("en", "Error: "), ("ko", "오류: ")])
def test_oserror_directory_as_cases_file(project, capsys, lang, prefix):
    _edit_toml(project, 'cases = "evals/cases.jsonl"', 'cases = "evals"')
    rc = cli.main(["--lang", lang, "demo"])
    assert rc == 2 and capsys.readouterr().err.startswith(prefix)


def test_scorer_error_is_still_a_keyerror(project):
    from evalgate.scorers import ScorerError
    assert issubclass(ScorerError, KeyError)
    assert str(ScorerError("sc_unknown_type", type="x", name="y")) == "unknown scorer type: x (y)"


# ── 보고서: 생성 시 언어로 고정 ───────────────────────────────

def test_html_report_language_en(project, capsys):
    cli.main(["--lang", "en", "demo"])
    html = (project / "reports" / "demo.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in html
    for marker in ("evalgate evaluation report", "Metric summary", "Why the gate failed", "newly failing", "scorer disagreement",
                   "Judge:", "Gate FAIL", "answers and scores per case", "Repeat 1"):
        assert marker in html
    for old in ("새로 실패", "채점기 불일치", "게이트 실패 이유", "지표 요약"):
        assert old not in html
    assert "<script" not in html and "localStorage" not in html  # 정적 보고서: 언어 전환 메뉴 없음


def test_html_report_language_ko(project, capsys):
    cli.main(["--lang", "ko", "demo"])
    html = (project / "reports" / "demo.html").read_text(encoding="utf-8")
    assert '<html lang="ko">' in html
    for marker in ("evalgate 평가 보고서", "지표 요약", "게이트 실패 이유", "새로 실패", "채점기 불일치", "심판:", "게이트 FAIL"):
        assert marker in html


@pytest.mark.parametrize("lang,head,gate_row", [("en", "| Metric |", "| Gate |"), ("ko", "| 지표 |", "| 게이트 |")])
def test_markdown_report_and_step_summary_language(project, monkeypatch, capsys, lang, head, gate_row):
    summary = project / "reports" / "summary.md"
    summary.parent.mkdir()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    cli.main(["--lang", lang, "run", "--prompt", "prompts/regressed.txt", "--gate"])
    for text in (summary.read_text(encoding="utf-8"), (project / "reports" / "latest.md").read_text(encoding="utf-8")):
        assert head in text and gate_row in text
    assert ("### evalgate results" if lang == "en" else "### evalgate 결과") in text


# ── 불변 항목 ────────────────────────────────────────────────

def test_json_keys_and_exit_codes_do_not_change_with_language(project, capsys):
    results = {}
    for lang in ("en", "ko"):
        rc = cli.main(["--lang", lang, "run", "--prompt", "prompts/regressed.txt", "--gate", "--name", lang])
        capsys.readouterr()
        assert rc == 1
        data = json.loads((project / "reports" / f"{lang}.json").read_text(encoding="utf-8"))
        data.pop("generated_at")
        results[lang] = data
    en, ko = results["en"], results["ko"]
    assert en.keys() == ko.keys() and en["summary"] == ko["summary"] and en["gate"]["passed"] is ko["gate"]["passed"] is False
    assert len(en["gate"]["failures"]) == len(ko["gate"]["failures"])
    assert en["gate"]["failures"] != ko["gate"]["failures"]  # 자유 문장은 선택 언어로 저장된다
    assert en["samples"][0]["answer"] == ko["samples"][0]["answer"]  # 모델 답변은 데이터다


def test_cassette_hashes_do_not_depend_on_language(project, capsys):
    """심판 프롬프트·요청 해시는 번역 대상이 아니다: 영어로 돌려도 녹화에서 전부 찾힌다(exit 0)."""
    assert cli.main(["--lang", "en", "run", "--prompt", "prompts/baseline.txt", "--gate"]) == 0
