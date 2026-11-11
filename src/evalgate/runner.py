"""실행기: 케이스 × 반복마다 (프롬프트 → 모델 답변 → 채점기들) 을 돌려 샘플 목록을 만든다.

워커 스레드로 샘플을 병렬 처리하지만 결과는 항상 (케이스 순서, 반복 번호) 순서로 돌려줘서
mock 모드 결과가 실행마다 똑같다.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .i18n import t
from .scorers import run_scorer


def read_prompt(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def run_sample(cfg: dict, provider, prompt: str, case: dict, repeat: int, lang: str | None = None) -> dict:
    """샘플 하나: 답변 생성 → 케이스가 지정한 채점기 모두 실행."""
    m = cfg["model"]
    request = {
        "model": m["name"],
        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": case["input"]}],
        "temperature": m["temperature"], "top_p": m["top_p"],
        "seed": int(m["seed"]) + repeat,  # 반복마다 다른 고정 시드
        "max_tokens": m["max_tokens"],
    }
    answer = provider.chat(request, repeat=repeat, label=t("label_generate", lang, case=case["id"], n=repeat + 1))
    ctx = {"cfg": cfg, "provider": provider, "repeat": repeat, "lang": lang}
    scores = {name: run_scorer(name, case, answer, ctx) for name in case["scorers"]}
    return {"case": case["id"], "repeat": repeat, "answer": answer, "scores": scores}


def run_all(cfg: dict, provider, prompt: str, cases: list[dict], repeats: int, progress: bool = False, lang: str | None = None) -> list[dict]:
    jobs = [(c, r) for c in cases for r in range(repeats)]
    done = 0

    def work(job):
        nonlocal done
        sample = run_sample(cfg, provider, prompt, *job, lang=lang)
        if progress:  # 실모드는 느리므로 한 샘플 끝날 때마다 알린다
            done += 1
            print(t("progress", lang, done=done, total=len(jobs), case=job[0]["id"], n=job[1] + 1), file=sys.stderr, flush=True)
        return sample

    workers = max(1, int(cfg["run"]["workers"]))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(work, jobs))  # map 은 입력 순서대로 돌려준다
