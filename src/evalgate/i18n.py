"""User-facing text in English and Korean, plus language selection.

Everything a person reads (CLI output, error messages, generated reports) lives in the
MESSAGES table below, so adding a language or fixing a sentence means editing one file.

Language order: --lang en|ko  >  EVALGATE_LANG  >  LC_ALL  >  LC_MESSAGES  >  LANG.
A value starting with "ko" selects Korean; anything else (unset, C, POSIX, invalid) selects English.

NOT translated on purpose: JSON keys and structure, exit codes, the judge prompt (its text is part of
the cassette request hash), metric names, PASS/FAIL, and the data you evaluate.
"""

import os
import re

LANGS = ("en", "ko")
DEFAULT_LANG = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # --- CLI ---
        "error_line": "Error: {msg}",
        "table_legend": "(± standard error, ▲▼ change versus baseline, ~ within noise)",
        "gate_pass": "Gate passed: {name}",
        "gate_fail": "Gate failed: {name}",
        "run_summary": "Prompt {name} — {mode} mode, {cases} cases × {repeats} repeats, model {model}",
        "demo_summary": "evalgate demo — mock mode (cassette replay), {cases} cases × {repeats} repeats, model {model}",
        "report_line": "Report: {path}",
        "warn_no_model_call": (
            "Warning: the model was never called. All {reused} requests were already in the cassette ({cassette}), so they were skipped. "
            "To record fresh answers for your own evaluation set, delete the example cassette or point run.cassette at a new path; "
            "use --overwrite to record again."),
        "demo_unexpected": "Unexpected gate results (baseline and improved should pass, regressed should fail).",
        "baseline_saved": "Baseline saved: {path} (prompt {prompt})",
        # --- CLI help ---
        "help_description": "Prompt evaluation gate: score -> compare with baseline -> exit code",
        "help_lang": "Display language: en or ko (default: EVALGATE_LANG, then LC_ALL, LC_MESSAGES, LANG; otherwise en)",
        "help_config": "Config file (default evalgate.toml)",
        "help_demo": "Compare 3 prompts by replaying the cassette and write a report (no model or network needed)",
        "help_run": "Evaluate one prompt",
        "help_prompt": "Prompt file to evaluate",
        "help_mode": "mock = replay cassette (default) / real = live calls / record = live calls + record",
        "help_repeats": "Repeats per case",
        "help_workers": "Concurrent requests",
        "help_gate": "Judge with the gate rules and exit 1 on failure",
        "help_overwrite": "In record mode, record already-recorded requests again",
        "help_name": "Report file name (default latest)",
        "help_gate_cmd": "Re-judge a saved result with the current config rules",
        "help_results": "Result JSON (default reports/latest.json)",
        "help_baseline_cmd": "Save a result as the new baseline (evals/baseline.json)",
        "help_results_b": "Result JSON (default reports/latest.json)",
        "help_force": "Save a gate-failed result as the baseline too",
        "err_bad_lang": "invalid --lang value {value!r} (choose from en, ko)",
        "err_lang_missing": "--lang needs a value (choose from en, ko)",
        # --- errors: config / dataset / commands ---
        "cfg_missing": "Config file not found: {path}",
        "cfg_env_bad": "{name} has an invalid value: {value!r}",
        "cfg_mode_bad": "mode must be one of mock / real / record: {mode!r}",
        "cfg_results_missing_hint": "Results file not found: {path} (run evalgate run first)",
        "cfg_results_missing": "Results file not found: {path}",
        "cfg_multi_results": "A multi-prompt results file cannot be used with gate (pass a single run result)",
        "cfg_baseline_failed": "A gate-failed result cannot become the baseline (use --force to save it anyway)",
        "ds_json": "{path}:{line} JSON error: {error}",
        "ds_field": "{path}:{line} missing required field: {field}",
        "ds_dup": "{path}:{line} duplicate id: {id}",
        "ds_unknown_scorer": "{path}:{line} undefined scorer: {names} (check [scorers.*] in evalgate.toml)",
        "ds_empty": "{path}: no cases",
        # --- gate ---
        "gate_missing_metric": "metric {metric}: not in the results (check that the evaluation set uses this scorer)",
        "gate_floor": "metric {metric}: {value} < floor {floor}",
        "gate_drop": "metric {metric}: {delta} versus baseline {baseline} (exceeds allowed drop {max_drop})",
        "annotation_title": "evalgate gate failed ({name})",
        # --- scorers ---
        "sc_extract_fail": "extraction failed (regex did not match)",
        "sc_regex_ok": "format matches",
        "sc_regex_no": "format does not match",
        "sc_contains_yes": "{want!r} found",
        "sc_contains_no": "{want!r} not found",
        "sc_empty": "empty answer",
        "sc_cos": "cos={cos} (threshold {threshold})",
        "sc_expected_missing": "case {case} has no expected.{field}",
        "sc_unknown_type": "unknown scorer type: {type} ({name})",
        "label_generate": "{case} repeat {n} generate",
        "label_judge": "{case} repeat {n} judge",
        "label_embed": "{case} embedding",
        "label_answer": "(answer)",
        "label_reference": "(reference)",
        # --- runner ---
        "progress": "  [{done}/{total}] {case} repeat {n} done",
        # --- providers ---
        "cassette_miss": (
            "Request not in the cassette: {label} (key {key}, cassette file {file}).\n"
            "  If you changed the prompt, model or settings, record with a real model and commit the cassette file too:\n"
            "  PYTHONPATH=src uv run --no-project --python 3.14 python -m evalgate.cli run --mode record --prompt <prompt file>"),
        "http_error": "HTTP {code}: {url} (check the model name and key)",
        "call_failed": "Call failed: {url} — {error} (check that Ollama is running and the model is pulled)",
        "bad_response": "Unexpected response format ({label}): {body}",
        "bad_embed_response": "Unexpected embedding response format ({label})",
        # --- report: HTML ---
        "html_lang": "en",
        "html_title": "evalgate report",
        "html_h1": "evalgate evaluation report",
        "html_meta": "mode {mode} · model {model} · judge {judge} · {cases} cases × {repeats} repeats · notation: mean ± standard error",
        "html_h_summary": "Metric summary",
        "html_h_chart": "Score per metric",
        "html_h_cases": "Results per case",
        "html_fail_title": "Why the gate failed",
        "html_gate_badge": "Gate {state}",
        "html_no_baseline": "no baseline",
        "html_same": "= same as baseline",
        "html_delta": "{arrow} {delta} (baseline {baseline})",
        "html_noise": " · within noise",
        "html_floor": "floor {floor} {state}",
        "html_floor_met": "met",
        "html_floor_missed": "missed",
        "html_info_metric": "reference metric (not gated)",
        "html_chart_label": "Bar chart of mean score per metric",
        "html_case_summary": "{file} — answers and scores per case",
        "html_th_case": "Case",
        "html_th_answer": "Answer and scores",
        "html_repeat": "Repeat {n}",
        "html_empty_answer": "(empty answer)",
        "html_judge": "Judge: {reason}",
        "html_new_fail": "newly failing",
        "html_new_pass": "newly passing",
        "html_split": "scorer disagreement",
        "html_split_title": "The deterministic scorers and the judge disagreed.",
        # --- report: Markdown ---
        "md_title": "### evalgate results",
        "md_metric": "Metric",
        "md_gate": "Gate",
        "md_noise": ", noise",
    },
    "ko": {
        # --- CLI ---
        "error_line": "오류: {msg}",
        "table_legend": "(± 표준오차, ▲▼ 기준선 대비 변화, ~ 잡음 범위 이내)",
        "gate_pass": "게이트 통과: {name}",
        "gate_fail": "게이트 실패: {name}",
        "run_summary": "프롬프트 {name} — {mode} 모드, 케이스 {cases}개 × 반복 {repeats}회, 모델 {model}",
        "demo_summary": "evalgate demo — mock 모드(녹화 재생), 케이스 {cases}개 × 반복 {repeats}회, 모델 {model}",
        "report_line": "보고서: {path}",
        "warn_no_model_call": (
            "경고: 모델을 한 번도 부르지 않았습니다. 요청 {reused}건이 모두 기존 녹화({cassette})에 있어 건너뛰었습니다. "
            "내 평가 세트로 새로 녹화하려면 예시 녹화 파일을 지우거나 run.cassette 를 새 경로로 바꾸고, 다시 녹화하려면 --overwrite 를 쓰세요."),
        "demo_unexpected": "예상과 다른 게이트 결과입니다(baseline·improved 통과, regressed 실패가 정상).",
        "baseline_saved": "기준선 저장: {path} (프롬프트 {prompt})",
        # --- CLI help ---
        "help_description": "프롬프트 평가 게이트: 채점 → 기준선 비교 → 종료 코드",
        "help_lang": "표시 언어: en 또는 ko (기본: EVALGATE_LANG, 그다음 LC_ALL, LC_MESSAGES, LANG, 없으면 en)",
        "help_config": "설정 파일 (기본 evalgate.toml)",
        "help_demo": "녹화 재생으로 프롬프트 3종을 비교하고 보고서를 만든다 (모델·네트워크 불필요)",
        "help_run": "프롬프트 하나를 평가한다",
        "help_prompt": "평가할 프롬프트 파일",
        "help_mode": "mock=녹화 재생(기본) / real=실호출 / record=실호출+녹화",
        "help_repeats": "케이스당 반복 횟수",
        "help_workers": "동시 요청 수",
        "help_gate": "게이트 규칙으로 판정하고 실패 시 exit 1",
        "help_overwrite": "record 모드에서 이미 녹화된 요청도 다시 녹화",
        "help_name": "보고서 파일 이름(기본 latest)",
        "help_gate_cmd": "저장된 결과를 현재 설정의 규칙으로 다시 판정한다",
        "help_results": "결과 JSON (기본 reports/latest.json)",
        "help_baseline_cmd": "결과를 새 기준선(evals/baseline.json)으로 저장한다",
        "help_results_b": "결과 JSON (기본 reports/latest.json)",
        "help_force": "게이트 실패 결과도 기준선으로 저장",
        "err_bad_lang": "--lang 값이 올바르지 않습니다: {value!r} (en, ko 중 하나)",
        "err_lang_missing": "--lang 에 값이 필요합니다 (en, ko 중 하나)",
        # --- errors: config / dataset / commands ---
        "cfg_missing": "설정 파일이 없습니다: {path}",
        "cfg_env_bad": "{name} 값이 올바르지 않습니다: {value!r}",
        "cfg_mode_bad": "mode 는 mock / real / record 중 하나여야 합니다: {mode!r}",
        "cfg_results_missing_hint": "결과 파일이 없습니다: {path} (먼저 evalgate run 을 실행하세요)",
        "cfg_results_missing": "결과 파일이 없습니다: {path}",
        "cfg_multi_results": "여러 프롬프트 결과 파일은 gate 에 쓸 수 없습니다(run 결과를 지정하세요)",
        "cfg_baseline_failed": "게이트에 실패한 결과는 기준선으로 쓸 수 없습니다(그래도 쓰려면 --force)",
        "ds_json": "{path}:{line} JSON 오류: {error}",
        "ds_field": "{path}:{line} 필수 필드 없음: {field}",
        "ds_dup": "{path}:{line} id 중복: {id}",
        "ds_unknown_scorer": "{path}:{line} 정의되지 않은 채점기: {names} (evalgate.toml [scorers.*] 확인)",
        "ds_empty": "{path}: 케이스가 없습니다",
        # --- gate ---
        "gate_missing_metric": "지표 {metric}: 결과에 없음 (평가 세트에서 이 채점기를 쓰는지 확인)",
        "gate_floor": "지표 {metric}: {value} < 하한 {floor}",
        "gate_drop": "지표 {metric}: 기준선 {baseline} 대비 {delta} (허용 하락폭 {max_drop} 초과)",
        "annotation_title": "evalgate 게이트 실패 ({name})",
        # --- scorers ---
        "sc_extract_fail": "추출 실패(정규식이 맞지 않음)",
        "sc_regex_ok": "형식 일치",
        "sc_regex_no": "형식 불일치",
        "sc_contains_yes": "{want!r} 포함",
        "sc_contains_no": "{want!r} 없음",
        "sc_empty": "빈 답변",
        "sc_cos": "cos={cos} (임계 {threshold})",
        "sc_expected_missing": "케이스 {case} 의 expected.{field} 가 없습니다",
        "sc_unknown_type": "알 수 없는 채점기 type: {type} ({name})",
        "label_generate": "{case} 반복{n} 생성",
        "label_judge": "{case} 반복{n} 심판",
        "label_embed": "{case} 임베딩",
        "label_answer": "(답변)",
        "label_reference": "(기준)",
        # --- runner ---
        "progress": "  [{done}/{total}] {case} 반복{n} 완료",
        # --- providers ---
        "cassette_miss": (
            "녹화에 없는 요청입니다: {label} (key {key}, 녹화 파일 {file}).\n"
            "  프롬프트·모델·설정을 바꿨다면 실모델로 녹화한 뒤 녹화 파일을 함께 커밋하세요:\n"
            "  PYTHONPATH=src uv run --no-project --python 3.14 python -m evalgate.cli run --mode record --prompt <프롬프트 파일>"),
        "http_error": "HTTP {code}: {url} (모델 이름·키를 확인하세요)",
        "call_failed": "호출 실패: {url} — {error} (Ollama 가 켜져 있는지, 모델을 받았는지 확인하세요)",
        "bad_response": "예상과 다른 응답 형식입니다({label}): {body}",
        "bad_embed_response": "예상과 다른 임베딩 응답 형식입니다({label})",
        # --- report: HTML ---
        "html_lang": "ko",
        "html_title": "evalgate 보고서",
        "html_h1": "evalgate 평가 보고서",
        "html_meta": "모드 {mode} · 모델 {model} · 심판 {judge} · 케이스 {cases}개 × 반복 {repeats}회 · 표기: 평균 ± 표준오차",
        "html_h_summary": "지표 요약",
        "html_h_chart": "지표별 점수",
        "html_h_cases": "케이스별 결과",
        "html_fail_title": "게이트 실패 이유",
        "html_gate_badge": "게이트 {state}",
        "html_no_baseline": "기준선 없음",
        "html_same": "= 기준선과 같음",
        "html_delta": "{arrow} {delta} (기준선 {baseline})",
        "html_noise": " · 잡음 범위",
        "html_floor": "하한 {floor} {state}",
        "html_floor_met": "충족",
        "html_floor_missed": "미달",
        "html_info_metric": "참고용 지표(게이트 제외)",
        "html_chart_label": "지표별 평균 점수 막대 그래프",
        "html_case_summary": "{file} — 케이스별 답변과 채점",
        "html_th_case": "케이스",
        "html_th_answer": "답변과 채점",
        "html_repeat": "반복 {n}",
        "html_empty_answer": "(빈 답변)",
        "html_judge": "심판: {reason}",
        "html_new_fail": "새로 실패",
        "html_new_pass": "새로 통과",
        "html_split": "채점기 불일치",
        "html_split_title": "결정적 채점기와 심판의 판정이 갈렸습니다",
        # --- report: Markdown ---
        "md_title": "### evalgate 결과",
        "md_metric": "지표",
        "md_gate": "게이트",
        "md_noise": ", 잡음",
    },
}


def resolve_lang(cli_value: str | None = None, env: dict | None = None) -> str:
    """Pick the display language: cli_value > EVALGATE_LANG > LC_ALL > LC_MESSAGES > LANG. Not Korean means English."""
    env = os.environ if env is None else env
    for value in (cli_value, env.get("EVALGATE_LANG"), env.get("LC_ALL"), env.get("LC_MESSAGES"), env.get("LANG")):
        if value:  # an empty value counts as "not set"
            return "ko" if value.strip().lower().startswith("ko") else "en"
    return DEFAULT_LANG


def t(key: str, lang: str | None = None, /, **params) -> str:
    """Render message `key` in `lang` (None = resolve from the environment)."""
    lang = lang if lang in MESSAGES else resolve_lang(lang)
    return MESSAGES[lang][key].format(**params)


def placeholders(text: str) -> set[str]:
    """Names of the {placeholders} used in a message (for the key-parity test)."""
    return set(re.findall(r"\{(\w+)(?:![rsa])?(?::[^}]*)?\}", text))


class LocalizedError(Exception):
    """Error carrying a message key plus parameters, so the CLI can render it in the chosen language.

    str(error) renders English (for library users and tracebacks); error.render(lang) picks a language.
    """

    def __init__(self, code: str, **params):
        self.code = code
        self.params = params
        super().__init__(code)

    def render(self, lang: str | None = None) -> str:
        return t(self.code, lang, **self.params)

    def __str__(self) -> str:
        return self.render("en")
