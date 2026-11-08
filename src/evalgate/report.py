"""보고서 생성: 자립형 HTML(외부 요청 없음, 인라인 CSS·SVG), Markdown 요약.

results 는 cli.evaluate_prompt 가 만든 dict 의 목록(프롬프트 1개 이상)이다.
HTML 의 주요 구역 id: #summary(지표 카드) · #chart(막대 그래프) · #cases(케이스별 답변·채점)
"""

from html import escape as esc

SERIES = ["s1", "s2", "s3", "s4"]  # 프롬프트마다 CSS 변수 색 하나
DETERMINISTIC = {"exact", "regex", "contains"}


def _fmt_delta(c: dict | None) -> tuple[str, str]:
    """기준선 대비 변화 → (문구, css 클래스). 색에만 기대지 않도록 ▲▼ 기호와 말을 같이 쓴다."""
    if not c:
        return "기준선 없음", "flat"
    if c["same"]:
        return "= 기준선과 같음", "flat"
    arrow = "▲" if c["delta"] > 0 else "▼"
    text = f"{arrow} {c['delta']:+.2f} (기준선 {c['baseline']:.2f})"
    if c["noise"]:
        return text + " · 잡음 범위", "flat"
    return text, ("up" if c["delta"] > 0 else "down")


def _metric_cards(r: dict, gate_cfg: dict) -> str:
    floors = gate_cfg.get("min_scores", {})
    cards = []
    for m, s in r["summary"]["metrics"].items():
        delta_text, delta_cls = _fmt_delta(r["comparison"]["metrics"].get(m))
        floor = floors.get(m)
        floor_html = ""
        if floor is not None:
            ok = s["mean"] >= floor
            floor_html = f'<div class="floor {"ok" if ok else "ng"}">하한 {floor:.2f} {"충족" if ok else "미달"}</div>'
        else:
            floor_html = '<div class="floor">참고용 지표(게이트 제외)</div>'
        cards.append(
            f'<div class="metric"><div class="mname">{esc(m)}</div>'
            f'<div class="mval">{s["mean"]:.2f}<span class="se"> ± {s["se"]:.2f}</span></div>'
            f'<div class="delta {delta_cls}">{esc(delta_text)}</div>{floor_html}</div>')
    return "".join(cards)


def _chart(results: list[dict]) -> str:
    """지표별 묶음 막대 그래프(SVG). 막대 위에 값을 직접 적는다."""
    metrics = list(results[0]["summary"]["metrics"])
    W, H, L, B, T = 640, 260, 36, 34, 14
    plot_h = H - B - T
    group_w = (W - L - 8) / len(metrics)
    bar_w = min(34, (group_w - 16) / len(results))
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="지표별 평균 점수 막대 그래프" class="chartsvg">']
    for g in (0, 0.25, 0.5, 0.75, 1.0):
        y = T + plot_h * (1 - g)
        out.append(f'<line x1="{L}" x2="{W - 8}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{y + 4:.1f}" class="axis" text-anchor="end">{g:.2f}</text>')
    for i, m in enumerate(metrics):
        gx = L + i * group_w + (group_w - bar_w * len(results)) / 2
        for j, r in enumerate(results):
            v = r["summary"]["metrics"][m]["mean"]
            h = plot_h * v
            x, y = gx + j * bar_w, T + plot_h - h
            out.append(f'<rect x="{x + 2:.1f}" y="{y:.1f}" width="{bar_w - 4:.1f}" height="{max(h, 0.5):.1f}" rx="2" class="bar {SERIES[j % 4]}"><title>{esc(r["name"])} {esc(m)} {v:.2f}</title></rect>'
                       f'<text x="{x + bar_w / 2:.1f}" y="{y - 4:.1f}" class="val" text-anchor="middle">{v:.2f}</text>')
        out.append(f'<text x="{gx + bar_w * len(results) / 2:.1f}" y="{H - 12}" class="axis" text-anchor="middle">{esc(m)}</text>')
    out.append("</svg>")
    legend = "".join(f'<span class="lg"><i class="sw {SERIES[j % 4]}"></i>{esc(r["name"])}</span>' for j, r in enumerate(results))
    return f'<div class="legend">{legend}</div>{"".join(out)}'


def _case_rows(r: dict) -> str:
    types = r.get("scorer_types", {})
    samples: dict[str, list[dict]] = {}
    for s in r["samples"]:
        samples.setdefault(s["case"], []).append(s)
    rows = []
    for c in r["cases"]:
        flips = r["comparison"]["cases"].get(c["id"], {})
        badges = []
        if "new_fail" in flips.values():
            badges.append('<span class="badge new-fail">새로 실패</span>')
        if "new_pass" in flips.values():
            badges.append('<span class="badge new-pass">새로 통과</span>')
        blocks, disagree = [], False
        for s in samples.get(c["id"], []):
            chips, det_fail, judge_pass, det_pass, judge_fail = [], False, False, False, False
            for m, sc in s["scores"].items():
                ok = sc["score"] >= 0.5
                chips.append(f'<span class="chip {"ok" if ok else "ng"}" title="{esc(sc["detail"])}">{"✓" if ok else "✗"} {esc(m)}</span>')
                t = types.get(m)
                if t in DETERMINISTIC:
                    det_fail |= not ok
                    det_pass |= ok
                if t == "judge":
                    judge_pass |= ok
                    judge_fail |= not ok
            disagree |= (det_fail and judge_pass) or (det_pass and judge_fail)
            reason = next((sc["detail"] for m, sc in s["scores"].items() if types.get(m) == "judge"), "")
            blocks.append(
                f'<div class="rep"><div class="replabel">반복 {s["repeat"] + 1}</div>'
                f'<div class="ans">{esc(s["answer"]) or "(빈 답변)"}</div>'
                f'<div class="chips">{"".join(chips)}</div>'
                + (f'<div class="reason">심판: {esc(reason)}</div>' if reason else "") + "</div>")
        if disagree:
            badges.append('<span class="badge split" title="결정적 채점기와 심판의 판정이 갈렸습니다">채점기 불일치</span>')
        rows.append(
            f'<tr class="case-row" id="{esc(r["name"])}-{esc(c["id"])}">'
            f'<td data-label="케이스"><strong>{esc(c["id"])}</strong><div class="q">{esc(c["input"])}</div>{"".join(badges)}</td>'
            f'<td data-label="답변과 채점">{"".join(blocks)}</td></tr>')
    return "".join(rows)


CSS = """
:root{--bg:#f7f8fa;--card:#fff;--fg:#1b2330;--mut:#5b6677;--line:#dfe3ea;--ok:#13795b;--ng:#c0392b;--warn:#a15c00;
--s1:#2a6fdb;--s2:#13795b;--s3:#d9622b;--s4:#7b5cc4;--okbg:#e4f5ee;--ngbg:#fbe9e6;--warnbg:#fdf1dc}
@media (prefers-color-scheme:dark){:root{--bg:#10151c;--card:#182029;--fg:#e6ebf2;--mut:#9aa6b6;--line:#2b3644;--ok:#4cc79b;--ng:#ff8a7a;--warn:#f0b254;
--s1:#6aa3ff;--s2:#4cc79b;--s3:#ff9a66;--s4:#b79cff;--okbg:#14352b;--ngbg:#3d201c;--warnbg:#3b2f14}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
main{max-width:1000px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.4rem;margin:0 0 4px}h2{font-size:1.1rem;margin:28px 0 10px}
.meta{color:var(--mut);font-size:.85rem;overflow-wrap:anywhere}
.run-card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0}
.run-head{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.run-head .name{font-weight:700;font-size:1.05rem}
.gate{font-weight:700;padding:2px 10px;border-radius:99px;font-size:.85rem}
.gate.pass{background:var(--okbg);color:var(--ok)}.gate.fail{background:var(--ngbg);color:var(--ng)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.metric{border:1px solid var(--line);border-radius:8px;padding:10px}
.mname{color:var(--mut);font-size:.8rem}.mval{font-size:1.6rem;font-weight:700}.se{font-size:.8rem;color:var(--mut);font-weight:400}
.delta{font-size:.82rem}.delta.up{color:var(--ok)}.delta.down{color:var(--ng)}.delta.flat{color:var(--mut)}
.floor{font-size:.78rem;color:var(--mut)}.floor.ok{color:var(--ok)}.floor.ng{color:var(--ng)}
.fails{margin:10px 0 0;padding:8px 12px;background:var(--ngbg);color:var(--ng);border-radius:8px;font-size:.88rem}
.fails ul{margin:4px 0 0;padding-left:18px}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:6px;font-size:.85rem}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.chartwrap{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.chartsvg{width:100%;height:auto;display:block}
.grid{stroke:var(--line);stroke-width:1}.axis{fill:var(--mut);font-size:11px}.val{fill:var(--fg);font-size:11px}
.s1{fill:var(--s1);background:var(--s1)}.s2{fill:var(--s2);background:var(--s2)}.s3{fill:var(--s3);background:var(--s3)}.s4{fill:var(--s4);background:var(--s4)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:10px 0;padding:0 12px}
summary{cursor:pointer;padding:12px 0;font-weight:700}
table{width:100%;border-collapse:collapse;table-layout:fixed}
th,td{text-align:left;vertical-align:top;padding:10px 8px;border-top:1px solid var(--line);overflow-wrap:anywhere}
th:first-child,td:first-child{width:30%}
.q{color:var(--mut);font-size:.88rem;margin:2px 0 6px}
.rep{margin-bottom:10px}.replabel{font-size:.75rem;color:var(--mut)}
.ans{white-space:pre-wrap;background:var(--bg);border-radius:6px;padding:6px 8px;font-size:.9rem}
.chips{margin-top:4px;display:flex;flex-wrap:wrap;gap:4px}
.chip{font-size:.78rem;padding:1px 8px;border-radius:99px}.chip.ok{background:var(--okbg);color:var(--ok)}.chip.ng{background:var(--ngbg);color:var(--ng)}
.reason{font-size:.8rem;color:var(--mut);margin-top:3px}
.badge{display:inline-block;font-size:.75rem;font-weight:700;padding:1px 8px;border-radius:99px;margin:0 4px 4px 0}
.badge.new-fail{background:var(--ngbg);color:var(--ng)}.badge.new-pass{background:var(--okbg);color:var(--ok)}.badge.split{background:var(--warnbg);color:var(--warn)}
@media (max-width:700px){
 table,thead,tbody,tr,td{display:block;width:100%}thead{display:none}
 th:first-child,td:first-child{width:100%}
 td::before{content:attr(data-label);display:block;font-size:.72rem;color:var(--mut)}}
"""


def render_html(results: list[dict], gate_cfg: dict) -> str:
    head = results[0]
    cards = []
    for j, r in enumerate(results):
        gate = r["gate"]
        fails = ""
        if gate["failures"]:
            fails = '<div class="fails"><strong>게이트 실패 이유</strong><ul>' + "".join(f"<li>{esc(f)}</li>" for f in gate["failures"]) + "</ul></div>"
        cards.append(
            f'<div class="run-card" id="run-{esc(r["name"])}"><div class="run-head">'
            f'<span class="sw {SERIES[j % 4]}"></span><span class="name">{esc(r["prompt_file"])}</span>'
            f'<span class="gate {"pass" if gate["passed"] else "fail"}">게이트 {"PASS" if gate["passed"] else "FAIL"}</span></div>'
            f'<div class="metrics">{_metric_cards(r, gate_cfg)}</div>{fails}</div>')
    cases = "".join(
        f'<details {"open" if j == len(results) - 1 or len(results) == 1 else ""} id="cases-{esc(r["name"])}"><summary>{esc(r["prompt_file"])} — 케이스별 답변과 채점</summary>'
        f'<table><thead><tr><th>케이스</th><th>답변과 채점</th></tr></thead><tbody>{_case_rows(r)}</tbody></table></details>'
        for j, r in enumerate(results))
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>evalgate 보고서</title><style>{CSS}</style></head><body><main>
<h1>evalgate 평가 보고서</h1>
<div class="meta">모드 {esc(head["mode"])} · 모델 {esc(head["model"])} · 심판 {esc(head["judge_model"])} · 케이스 {len(head["cases"])}개 × 반복 {head["repeats"]}회 · 표기: 평균 ± 표준오차</div>
<section id="summary"><h2>지표 요약</h2>{"".join(cards)}</section>
<section id="chart"><h2>지표별 점수</h2><div class="chartwrap">{_chart(results)}</div></section>
<section id="cases"><h2>케이스별 결과</h2>{cases}</section>
</main></body></html>
"""


def render_markdown(results: list[dict], gate_cfg: dict) -> str:
    """GitHub step summary 용 Markdown: 지표 × 프롬프트 표 + 게이트 결과."""
    names = [r["name"] for r in results]
    lines = ["### evalgate 결과", "", "| 지표 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for m in results[0]["summary"]["metrics"]:
        cells = []
        for r in results:
            s, c = r["summary"]["metrics"][m], r["comparison"]["metrics"].get(m)
            cell = f"{s['mean']:.2f} ± {s['se']:.2f}"
            if c and not c["same"]:
                cell += f" ({'▲' if c['delta'] > 0 else '▼'}{abs(c['delta']):.2f}{', 잡음' if c['noise'] else ''})"
            cells.append(cell)
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    lines.append("| 게이트 | " + " | ".join("PASS" if r["gate"]["passed"] else "**FAIL**" for r in results) + " |")
    for r in results:
        for f in r["gate"]["failures"]:
            lines.append(f"- `{r['name']}`: {f}")
    return "\n".join(lines) + "\n"
