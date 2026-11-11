"""명령행 진입점: demo / run / gate / baseline.

종료 코드 규약 (CI 는 이 숫자만 본다):
  0  통과
  1  게이트 실패(점수가 기준 미달)
  2  설정·녹화·호출 오류(점수와 무관한 문제)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import gate as gate_mod
from . import report, stats
from .config import ConfigError, load_config
from .dataset import load_cases
from .i18n import LANGS, LocalizedError, resolve_lang, t
from .providers import make_provider
from .runner import read_prompt, run_all

EXIT_OK, EXIT_GATE_FAIL, EXIT_ERROR = 0, 1, 2


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else text


def load_baseline(path: str) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def evaluate_prompt(cfg: dict, provider, cases: list[dict], prompt_path: str, baseline: dict | None, lang: str | None = None) -> dict:
    """프롬프트 하나를 끝까지 평가해 결과 dict(= results.json 내용)를 만든다."""
    prompt = read_prompt(prompt_path)
    repeats = int(cfg["run"]["repeats"])
    samples = run_all(cfg, provider, prompt, cases, repeats, progress=cfg["run"]["mode"] != "mock", lang=lang)
    summary = stats.summarize(samples)
    comparison = stats.compare(summary, baseline)
    failures = gate_mod.evaluate(summary, comparison, cfg["gate"], lang)
    return {
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),  # 결정성 비교에서는 이 필드만 제외한다
        "name": Path(prompt_path).stem,
        "prompt_file": Path(prompt_path).name,
        "prompt_text": prompt,
        "mode": cfg["run"]["mode"], "model": cfg["model"]["name"], "judge_model": cfg["model"]["judge"],
        "repeats": repeats,
        "cases": [{"id": c["id"], "input": c["input"], "expected": c.get("expected", {})} for c in cases],
        "scorer_types": {n: c["type"] for n, c in cfg["scorers"].items()},
        "samples": samples, "summary": summary, "comparison": comparison,
        "gate": {"passed": not failures, "failures": failures},
    }


def format_table(results: list[dict], lang: str | None = None) -> str:
    """터미널 점수표: 지표 × 프롬프트. 셀 = 평균±표준오차 (기준선 대비 ▲▼)."""
    metrics = list(results[0]["summary"]["metrics"])
    names = [r["name"] for r in results]
    w = max(18, *(len(n) + 2 for n in names))
    lines = [f"{'metric':<11}" + "".join(f"{n:<{w}}" for n in names)]
    for m in metrics:
        row = f"{m:<11}"
        for r in results:
            s, c = r["summary"]["metrics"][m], r["comparison"]["metrics"].get(m)
            cell = f"{s['mean']:.2f}±{s['se']:.2f}"
            if c:
                if c["same"]:
                    cell += " ="
                else:
                    cell += f" {'▲' if c['delta'] > 0 else '▼'}{abs(c['delta']):.2f}" + ("~" if c["noise"] else "")
            row += f"{cell:<{w}}"
        lines.append(row)
    lines.append(f"{'gate':<11}" + "".join(f"{('PASS' if r['gate']['passed'] else 'FAIL'):<{w}}" for r in results))
    lines.append(t("table_legend", lang))
    return "\n".join(lines)


def print_gate(results: list[dict], lang: str | None = None) -> None:
    for r in results:
        if r["gate"]["passed"]:
            print(_color(t("gate_pass", lang, name=r["name"]), "32"))
        else:
            print(_color(t("gate_fail", lang, name=r["name"]), "31"))
            for f in r["gate"]["failures"]:
                print(f"  - {f}")
            for line in gate_mod.github_annotations(r["gate"]["failures"], r["name"], lang):
                print(line)


def write_outputs(cfg: dict, results: list[dict], stem: str, lang: str | None = None) -> Path:
    """결과 JSON·Markdown 요약·HTML 보고서를 reports 폴더에 쓴다. HTML 경로를 돌려준다."""
    out = Path(cfg["run"]["reports_dir"])
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = report.render_markdown(results, cfg["gate"], lang)
    (out / f"{stem}.md").write_text(md, encoding="utf-8")
    html_path = out / f"{stem}.html"
    html_path.write_text(report.render_html(results, cfg["gate"], lang), encoding="utf-8")
    # GitHub Actions 의 실행 요약 화면(step summary)에 같은 표를 덧붙인다
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if os.environ.get("GITHUB_ACTIONS") == "true" and summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    return html_path


def _lang(args) -> str:
    """이 실행의 표시 언어(main 이 정해 args.lang 에 넣어 둔다. 라이브러리로 직접 부르면 환경에서 결정)."""
    return resolve_lang(getattr(args, "lang", None))


def _prepare(args) -> tuple[dict, list[dict], object, dict | None]:
    cfg = load_config(args.config, {
        "run": {"mode": getattr(args, "mode", None), "repeats": getattr(args, "repeats", None),
                "workers": getattr(args, "workers", None), "overwrite": getattr(args, "overwrite", None) or None,
                "prompt": getattr(args, "prompt", None)},
    })
    cfg["_lang"] = _lang(args)
    cases = load_cases(cfg["run"]["cases"], set(cfg["scorers"]))
    provider = make_provider(cfg)
    return cfg, cases, provider, load_baseline(cfg["run"]["baseline"])


def cmd_run(args) -> int:
    cfg, cases, provider, baseline = _prepare(args)
    lang = cfg["_lang"]
    result = evaluate_prompt(cfg, provider, cases, cfg["run"]["prompt"], baseline, lang)
    print(t("run_summary", lang, name=result["name"], mode=result["mode"], cases=len(cases), repeats=result["repeats"], model=result["model"]))
    print(format_table([result], lang))
    html_path = write_outputs(cfg, [result], args.name, lang)
    print(t("report_line", lang, path=os.path.relpath(html_path)))
    if cfg["run"]["mode"] == "record" and getattr(provider, "reused", 0) and not getattr(provider, "recorded", 0):
        print(t("warn_no_model_call", lang, reused=provider.reused, cassette=cfg["run"]["cassette"]), file=sys.stderr)
    if args.gate:
        print_gate([result], lang)
        return EXIT_OK if result["gate"]["passed"] else EXIT_GATE_FAIL
    return EXIT_OK


def cmd_demo(args) -> int:
    args.mode = "mock"  # demo 는 항상 녹화 재생
    cfg, cases, provider, baseline = _prepare(args)
    lang = cfg["_lang"]
    results = [evaluate_prompt(cfg, provider, cases, p, baseline, lang) for p in cfg["demo"]["prompts"]]
    print(t("demo_summary", lang, cases=len(cases), repeats=results[0]["repeats"], model=results[0]["model"]) + "\n")
    print(format_table(results, lang))
    print()
    print_gate(results, lang)
    html_path = write_outputs(cfg, results, "demo", lang)
    print("\n" + t("report_line", lang, path=os.path.relpath(html_path)))
    # 자가검사: 기준선·개선안은 통과, 회귀안은 실패해야 시연이 의도대로 된 것
    expected = [r["name"] != "regressed" for r in results]
    ok = [r["gate"]["passed"] for r in results] == expected
    if not ok:
        print(t("demo_unexpected", lang), file=sys.stderr)
    return EXIT_OK if ok else EXIT_GATE_FAIL


def cmd_gate(args) -> int:
    """마지막 결과(reports/latest.json)를 현재 설정의 규칙으로 다시 판정한다."""
    cfg = load_config(args.config)
    lang = _lang(args)
    path = Path(args.results) if args.results else Path(cfg["run"]["reports_dir"]) / "latest.json"
    if not path.is_file():
        raise ConfigError("cfg_results_missing_hint", path=str(path))
    result = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(result, list):
        raise ConfigError("cfg_multi_results")
    baseline = load_baseline(cfg["run"]["baseline"])
    result["comparison"] = stats.compare(result["summary"], baseline)
    failures = gate_mod.evaluate(result["summary"], result["comparison"], cfg["gate"], lang)
    result["gate"] = {"passed": not failures, "failures": failures}
    print(format_table([result], lang))
    print_gate([result], lang)
    return EXIT_OK if not failures else EXIT_GATE_FAIL


def cmd_baseline(args) -> int:
    """결과를 새 기준선으로 저장한다. 기준선은 '합격한 결과'여야 하므로 게이트 실패 결과는 --force 가 있어야 한다."""
    cfg = load_config(args.config)
    lang = _lang(args)
    path = Path(args.results) if args.results else Path(cfg["run"]["reports_dir"]) / "latest.json"
    if not path.is_file():
        raise ConfigError("cfg_results_missing", path=str(path))
    result = json.loads(path.read_text(encoding="utf-8"))
    if not result["gate"]["passed"] and not args.force:
        raise ConfigError("cfg_baseline_failed")
    baseline = {"prompt_file": result["prompt_file"], "model": result["model"], "repeats": result["repeats"],
                "metrics": result["summary"]["metrics"], "cases": result["summary"]["cases"]}
    target = Path(cfg["run"]["baseline"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(baseline, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(t("baseline_saved", lang, path=os.path.relpath(target), prompt=result["prompt_file"]))
    return EXIT_OK


def build_parser(lang: str | None = None) -> argparse.ArgumentParser:
    """lang 은 도움말 문구의 언어. main 이 --lang 을 먼저 훑어 정한 값을 넘긴다."""
    lang = lang or resolve_lang()
    p = argparse.ArgumentParser(prog="evalgate", description=t("help_description", lang))
    p.add_argument("--lang", choices=list(LANGS), help=t("help_lang", lang))
    p.add_argument("--config", default="evalgate.toml", help=t("help_config", lang))
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help=t("help_demo", lang)).set_defaults(fn=cmd_demo)

    r = sub.add_parser("run", help=t("help_run", lang))
    r.add_argument("--prompt", help=t("help_prompt", lang))
    r.add_argument("--mode", choices=["mock", "real", "record"], help=t("help_mode", lang))
    r.add_argument("--repeats", type=int, help=t("help_repeats", lang))
    r.add_argument("--workers", type=int, help=t("help_workers", lang))
    r.add_argument("--gate", action="store_true", help=t("help_gate", lang))
    r.add_argument("--overwrite", action="store_true", help=t("help_overwrite", lang))
    r.add_argument("--name", default="latest", help=t("help_name", lang))
    r.set_defaults(fn=cmd_run)

    g = sub.add_parser("gate", help=t("help_gate_cmd", lang))
    g.add_argument("--results", help=t("help_results", lang))
    g.set_defaults(fn=cmd_gate)

    b = sub.add_parser("baseline", help=t("help_baseline_cmd", lang))
    b.add_argument("--results", help=t("help_results_b", lang))
    b.add_argument("--force", action="store_true", help=t("help_force", lang))
    b.set_defaults(fn=cmd_baseline)
    return p


def _scan_lang(argv: list[str]) -> tuple[str | None, str | None]:
    """argv 에서 --lang 값을 먼저 찾는다(도움말 언어를 정하려고). (값, 오류 키)를 돌려준다."""
    value = None
    for i, a in enumerate(argv):
        if a == "--lang":
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                return None, "err_lang_missing"
            value = argv[i + 1]
        elif a.startswith("--lang="):
            value = a.split("=", 1)[1]
    if value is not None and value not in LANGS:
        return value, "err_bad_lang"
    return value, None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    value, problem = _scan_lang(argv)
    if problem:  # 잘못된 --lang: 환경 언어로 분명히 알리고 exit 2
        env_lang = resolve_lang(None)
        print(t("error_line", env_lang, msg=t(problem, env_lang, value=value)), file=sys.stderr)
        return EXIT_ERROR
    lang = resolve_lang(value)
    args = build_parser(lang).parse_args(argv)
    args.lang = lang
    try:
        return args.fn(args)
    except LocalizedError as e:  # 설정·평가 세트·공급원·채점기 오류: 선택 언어로 렌더링
        print(t("error_line", lang, msg=e.render(lang)), file=sys.stderr)
        return EXIT_ERROR
    except (OSError, KeyError) as e:  # OS 원문은 그대로 두고 접두만 번역
        print(t("error_line", lang, msg=str(e)), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
