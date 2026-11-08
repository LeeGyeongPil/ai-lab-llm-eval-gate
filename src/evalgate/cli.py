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
from .dataset import DatasetError, load_cases
from .providers import ProviderError, make_provider
from .runner import read_prompt, run_all

EXIT_OK, EXIT_GATE_FAIL, EXIT_ERROR = 0, 1, 2


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else text


def load_baseline(path: str) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def evaluate_prompt(cfg: dict, provider, cases: list[dict], prompt_path: str, baseline: dict | None) -> dict:
    """프롬프트 하나를 끝까지 평가해 결과 dict(= results.json 내용)를 만든다."""
    prompt = read_prompt(prompt_path)
    repeats = int(cfg["run"]["repeats"])
    samples = run_all(cfg, provider, prompt, cases, repeats, progress=cfg["run"]["mode"] != "mock")
    summary = stats.summarize(samples)
    comparison = stats.compare(summary, baseline)
    failures = gate_mod.evaluate(summary, comparison, cfg["gate"])
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


def format_table(results: list[dict]) -> str:
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
    lines.append("(± 표준오차, ▲▼ 기준선 대비 변화, ~ 잡음 범위 이내)")
    return "\n".join(lines)


def print_gate(results: list[dict]) -> None:
    for r in results:
        if r["gate"]["passed"]:
            print(_color(f"게이트 통과: {r['name']}", "32"))
        else:
            print(_color(f"게이트 실패: {r['name']}", "31"))
            for f in r["gate"]["failures"]:
                print(f"  - {f}")
            for line in gate_mod.github_annotations(r["gate"]["failures"], r["name"]):
                print(line)


def write_outputs(cfg: dict, results: list[dict], stem: str) -> Path:
    """결과 JSON·Markdown 요약·HTML 보고서를 reports 폴더에 쓴다. HTML 경로를 돌려준다."""
    out = Path(cfg["run"]["reports_dir"])
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = report.render_markdown(results, cfg["gate"])
    (out / f"{stem}.md").write_text(md, encoding="utf-8")
    html_path = out / f"{stem}.html"
    html_path.write_text(report.render_html(results, cfg["gate"]), encoding="utf-8")
    # GitHub Actions 의 실행 요약 화면(step summary)에 같은 표를 덧붙인다
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if os.environ.get("GITHUB_ACTIONS") == "true" and summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    return html_path


def _prepare(args) -> tuple[dict, list[dict], object, dict | None]:
    cfg = load_config(args.config, {
        "run": {"mode": getattr(args, "mode", None), "repeats": getattr(args, "repeats", None),
                "workers": getattr(args, "workers", None), "overwrite": getattr(args, "overwrite", None) or None,
                "prompt": getattr(args, "prompt", None)},
    })
    cases = load_cases(cfg["run"]["cases"], set(cfg["scorers"]))
    provider = make_provider(cfg)
    return cfg, cases, provider, load_baseline(cfg["run"]["baseline"])


def cmd_run(args) -> int:
    cfg, cases, provider, baseline = _prepare(args)
    result = evaluate_prompt(cfg, provider, cases, cfg["run"]["prompt"], baseline)
    print(f"프롬프트 {result['name']} — {result['mode']} 모드, 케이스 {len(cases)}개 × 반복 {result['repeats']}회, 모델 {result['model']}")
    print(format_table([result]))
    html_path = write_outputs(cfg, [result], args.name)
    print(f"보고서: {os.path.relpath(html_path)}")
    if args.gate:
        print_gate([result])
        return EXIT_OK if result["gate"]["passed"] else EXIT_GATE_FAIL
    return EXIT_OK


def cmd_demo(args) -> int:
    args.mode = "mock"  # demo 는 항상 녹화 재생
    cfg, cases, provider, baseline = _prepare(args)
    results = [evaluate_prompt(cfg, provider, cases, p, baseline) for p in cfg["demo"]["prompts"]]
    print(f"evalgate demo — mock 모드(녹화 재생), 케이스 {len(cases)}개 × 반복 {results[0]['repeats']}회, 모델 {results[0]['model']}\n")
    print(format_table(results))
    print()
    print_gate(results)
    html_path = write_outputs(cfg, results, "demo")
    print(f"\n보고서: {os.path.relpath(html_path)}")
    # 자가검사: 기준선·개선안은 통과, 회귀안은 실패해야 시연이 의도대로 된 것
    expected = [r["name"] != "regressed" for r in results]
    ok = [r["gate"]["passed"] for r in results] == expected
    if not ok:
        print("예상과 다른 게이트 결과입니다(baseline·improved 통과, regressed 실패가 정상).", file=sys.stderr)
    return EXIT_OK if ok else EXIT_GATE_FAIL


def cmd_gate(args) -> int:
    """마지막 결과(reports/latest.json)를 현재 설정의 규칙으로 다시 판정한다."""
    cfg = load_config(args.config)
    path = Path(args.results) if args.results else Path(cfg["run"]["reports_dir"]) / "latest.json"
    if not path.is_file():
        raise ConfigError(f"결과 파일이 없습니다: {path} (먼저 evalgate run 을 실행하세요)")
    result = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(result, list):
        raise ConfigError("여러 프롬프트 결과 파일은 gate 에 쓸 수 없습니다(run 결과를 지정하세요)")
    baseline = load_baseline(cfg["run"]["baseline"])
    result["comparison"] = stats.compare(result["summary"], baseline)
    failures = gate_mod.evaluate(result["summary"], result["comparison"], cfg["gate"])
    result["gate"] = {"passed": not failures, "failures": failures}
    print(format_table([result]))
    print_gate([result])
    return EXIT_OK if not failures else EXIT_GATE_FAIL


def cmd_baseline(args) -> int:
    """결과를 새 기준선으로 저장한다. 기준선은 '합격한 결과'여야 하므로 게이트 실패 결과는 --force 가 있어야 한다."""
    cfg = load_config(args.config)
    path = Path(args.results) if args.results else Path(cfg["run"]["reports_dir"]) / "latest.json"
    if not path.is_file():
        raise ConfigError(f"결과 파일이 없습니다: {path}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not result["gate"]["passed"] and not args.force:
        raise ConfigError("게이트에 실패한 결과는 기준선으로 쓸 수 없습니다(그래도 쓰려면 --force)")
    baseline = {"prompt_file": result["prompt_file"], "model": result["model"], "repeats": result["repeats"],
                "metrics": result["summary"]["metrics"], "cases": result["summary"]["cases"]}
    target = Path(cfg["run"]["baseline"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(baseline, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"기준선 저장: {os.path.relpath(target)} (프롬프트 {result['prompt_file']})")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="evalgate", description="프롬프트 평가 게이트: 채점 → 기준선 비교 → 종료 코드")
    p.add_argument("--config", default="evalgate.toml", help="설정 파일 (기본 evalgate.toml)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="녹화 재생으로 프롬프트 3종을 비교하고 보고서를 만든다 (모델·네트워크 불필요)").set_defaults(fn=cmd_demo)

    r = sub.add_parser("run", help="프롬프트 하나를 평가한다")
    r.add_argument("--prompt", help="평가할 프롬프트 파일")
    r.add_argument("--mode", choices=["mock", "real", "record"], help="mock=녹화 재생(기본) / real=실호출 / record=실호출+녹화")
    r.add_argument("--repeats", type=int, help="케이스당 반복 횟수")
    r.add_argument("--workers", type=int, help="동시 요청 수")
    r.add_argument("--gate", action="store_true", help="게이트 규칙으로 판정하고 실패 시 exit 1")
    r.add_argument("--overwrite", action="store_true", help="record 모드에서 이미 녹화된 요청도 다시 녹화")
    r.add_argument("--name", default="latest", help="보고서 파일 이름(기본 latest)")
    r.set_defaults(fn=cmd_run)

    g = sub.add_parser("gate", help="저장된 결과를 현재 설정의 규칙으로 다시 판정한다")
    g.add_argument("--results", help="결과 JSON (기본 reports/latest.json)")
    g.set_defaults(fn=cmd_gate)

    b = sub.add_parser("baseline", help="결과를 새 기준선(evals/baseline.json)으로 저장한다")
    b.add_argument("--results", help="결과 JSON (기본 reports/latest.json)")
    b.add_argument("--force", action="store_true", help="게이트 실패 결과도 기준선으로 저장")
    b.set_defaults(fn=cmd_baseline)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ConfigError, DatasetError, ProviderError, KeyError, FileNotFoundError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
