# 내 프로젝트에 옮기기

## 복사할 것

```
src/evalgate/                      # 도구 본체 (표준 라이브러리만 사용)
evalgate.toml                      # 채점기 정의 · 게이트 기준
evals/cases.jsonl                  # 내 평가 세트
evals/baseline.json                # 기준선 (3~4단계에서 내 것으로 교체)
prompts/baseline.txt               # 내 현재 프롬프트
cassettes/qwen3-4b.jsonl           # 녹화 파일 (내 것으로 다시 녹화)
docs/adopt/eval-gate.yml           # CI → .github/workflows/eval-gate.yml 로 복사
```

이 저장소의 `.github/workflows/eval-gate.yml`은 개발용(테스트·회귀 자가검사·lint 포함)이라 복사하지 않습니다. `docs/adopt/eval-gate.yml`은 모의 게이트 한 단계만 돌립니다. `pyproject.toml` 없이 `PYTHONPATH=src python -m evalgate.cli ...` 로 실행하며 Python 3.14 이상과 uv가 필요합니다. 아래 명령은 `PYTHONPATH=src`를 설정한 셸(`export PYTHONPATH=src`)에서 `uv run --no-project --python 3.14 python -m evalgate.cli ...` 형태로 실행합니다.

## 순서

1. `evals/cases.jsonl` 에 케이스를 씁니다. 한 줄이 한 케이스입니다.
   ```json
   {"id": "c01", "input": "문의", "expected": {"label": "배송", "facts": "정책 사실", "reference": "모범 답안"}, "scorers": ["format", "label", "judge"]}
   ```
   `expected` 안의 키는 마음대로 정하고, 채점기 설정이 그 키를 가리킵니다(`expected = "label"`).
2. `evalgate.toml` 의 `[scorers.*]` 를 내 업무에 맞게 고칩니다. `type` 은 `exact`·`regex`·`contains`·`similarity`·`judge`. 이름은 케이스의 `scorers` 목록과 `[gate].min_scores` 에서 그대로 씁니다.
3. 실모델로 녹화합니다(Ollama 또는 OpenAI 호환 엔드포인트).
   ```
   uv run --no-project --python 3.14 python -m evalgate.cli run --mode record --prompt prompts/baseline.txt
   ```
4. 결과가 마음에 들면 기준선으로 저장하고 녹화 파일과 함께 커밋합니다.
   ```
   uv run --no-project --python 3.14 python -m evalgate.cli baseline
   ```
5. `[gate]` 의 `min_scores`(절대 하한)와 `max_drop`(기준선 대비 허용 하락폭)을 정합니다. 처음엔 기준선 점수보다 조금 낮게 잡습니다.
6. 이후 프롬프트를 고치는 PR 에서는 **새 프롬프트로 `--mode record` 를 한 번 돌려 녹화 파일을 함께 커밋**합니다. 녹화에 없는 프롬프트면 CI 가 exit 2 로 실패하고 녹화 명령을 안내합니다. 의도된 동작입니다.

## 녹화 운영 규칙

- 요청 키 = 모델·메시지·온도·시드·반복 번호의 해시. 프롬프트·모델·설정을 한 글자라도 바꾸면 새로 녹화해야 합니다.
- `record` 는 이미 녹화된 요청은 건너뜁니다. 오래 걸리는 녹화를 끊었다가 같은 명령으로 이어 할 수 있습니다. 다시 녹화하려면 `--overwrite`.
- 녹화에는 최종 답·심판 판정·임베딩만 저장하고 생각 과정은 저장하지 않습니다.
- 녹화 파일 줄 수는 (프롬프트 수 × 케이스 수 × 반복 × (생성 + 심판 + 임베딩))에 비례해 커집니다. 안 쓰는 프롬프트의 줄은 파일에서 지워도 됩니다.

## mock 게이트의 한계와 다른 선택지

mock 게이트는 **"녹화된 응답에 대한 채점이 기준을 넘는가"** 만 검증합니다. 녹화를 조작하면 통과시킬 수 있고, 모델 자체가 지금도 같은 답을 내는지는 알 수 없습니다.

| 방식 | 장점 | 단점 |
|---|---|---|
| mock(녹화 재생, 이 저장소 기본) | 비밀값·모델 불필요, 결정적, 수 초 | 녹화를 사람이 갱신해야 함, 증거 검증일 뿐 |
| real + 호스팅 엔드포인트(CI 비밀값) | 실제 모델로 검증 | 비용·시간·비결정성, 키 관리 |

실모드 CI 는 `EVALGATE_BASE_URL`·`EVALGATE_API_KEY`·`EVALGATE_MODEL` 을 비밀값으로 넣고 `--mode real` 로 돌리면 됩니다. 이 방식은 이 저장소에서 검증하지 않았습니다.

## 다른 OpenAI 호환 엔드포인트

`.env.example` 의 변수 이름을 셸에서 `export` 하면 됩니다(값은 직접, `.env` 파일은 자동으로 읽지 않습니다). 모델 이름이 바뀌면 요청 키가 달라지므로 녹화도 다시 해야 합니다. 비생각 모델을 쓰면 호출이 훨씬 빠르지만 이 저장소에서 검증한 범위는 아닙니다.
