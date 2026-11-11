"""모델 응답 공급원 3종. 러너와 채점기는 이 모듈의 chat()/embed() 두 함수만 안다.

  CassetteProvider  mock   녹화 파일에서 응답을 재생한다. 네트워크 코드를 전혀 타지 않는다(결정적).
  HttpProvider      real   OpenAI 호환 API(Ollama /v1 등)를 실제로 부른다.
  RecordingProvider record real 과 같되, 받은 응답을 녹화 파일에 한 줄씩 추가한다.

요청 키 = sha256(정규화한 요청 JSON, 녹화 파일에는 req_hash 로 저장). 프롬프트·모델·온도·시드 중 하나라도 바뀌면 키가 달라지므로,
"프롬프트를 바꿨는데 녹화를 안 했다"는 사실이 mock 모드에서 조용히 통과하지 않고 실패(exit 2)로 드러난다.
"""

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .i18n import LocalizedError


class ProviderError(LocalizedError):
    """호출 실패(연결·시간 초과·응답 형식 오류). CLI 에서 exit 2. 메시지는 코드+파라미터."""


class CassetteMiss(ProviderError):
    """mock 모드인데 녹화에 없는 요청."""


def request_key(kind: str, request: dict, repeat: int = 0) -> str:
    """요청을 키 순서·공백에 상관없이 같은 문자열로 만든 뒤 sha256 을 취한다."""
    canon = json.dumps({"kind": kind, "request": request, "repeat": repeat}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def strip_think(text: str) -> str:
    """생각 모델 방어: 답에 '</think>' 가 섞여 있으면 그 앞(생각 과정)을 버린다."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


def _summary(kind: str, request: dict) -> dict:
    """녹화 파일에 사람이 읽으라고 남기는 요청 요약(키 계산에는 쓰지 않는다)."""
    if kind == "chat":
        last_user = next((m["content"] for m in reversed(request["messages"]) if m["role"] == "user"), "")
        return {"model": request["model"], "seed": request.get("seed"), "temperature": request.get("temperature"), "user_preview": last_user[:60]}
    return {"model": request["model"], "input_preview": request["input"][:60]}


class CassetteProvider:
    """mock: JSONL 녹화 파일을 {키: 응답} 사전으로 읽어 재생한다. 같은 키가 여러 번이면 마지막 것이 이긴다."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: dict[str, dict] = {}
        if self.path.is_file():
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        e = json.loads(line)
                        self.entries[e["req_hash"]] = e

    def _lookup(self, kind: str, request: dict, repeat: int, label: str):
        key = request_key(kind, request, repeat)
        entry = self.entries.get(key)
        if entry is None:
            raise CassetteMiss("cassette_miss", label=label or kind, key=key[:12], file=self.path.name)
        return entry["response"]

    def chat(self, request: dict, repeat: int = 0, label: str = "") -> str:
        return self._lookup("chat", request, repeat, label)

    def embed(self, request: dict, label: str = "") -> list[float]:
        return self._lookup("embed", request, 0, label)


class HttpProvider:
    """real: OpenAI 호환 /chat/completions·/embeddings 를 표준 라이브러리 urllib 으로 부른다."""

    RETRIES = 2  # 연결 오류·시간 초과·5xx 일 때 추가로 시도할 횟수

    def __init__(self, base_url: str, api_key: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout  # 모든 요청에 반드시 붙는다

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        last: Exception | None = None
        for attempt in range(self.RETRIES + 1):
            req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # with 로 응답을 반드시 닫는다
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                e.close()
                if e.code < 500:  # 4xx 는 다시 해도 소용없다
                    raise ProviderError("http_error", code=e.code, url=f"{self.base_url}{path}") from e
                last = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            if attempt < self.RETRIES:
                time.sleep(2 * (attempt + 1))
        raise ProviderError("call_failed", url=f"{self.base_url}{path}", error=str(last)) from last

    def chat(self, request: dict, repeat: int = 0, label: str = "") -> str:
        data = self._post("/chat/completions", request)
        try:
            # content 에는 최종 답만 온다(생각은 message.reasoning 으로 분리). 혹시 섞여 오면 strip_think 가 처리한다.
            return strip_think(data["choices"][0]["message"].get("content") or "")
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError("bad_response", label=label or "chat", body=str(data)[:200]) from e

    def embed(self, request: dict, label: str = "") -> list[float]:
        data = self._post("/embeddings", request)
        try:
            return [round(x, 6) for x in data["data"][0]["embedding"]]  # 소수 6자리로 줄여 녹화 파일 크기를 줄인다
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError("bad_embed_response", label=label or "embed") from e


class RecordingProvider:
    """record: real 호출 + 녹화. 이미 녹화된 키는 다시 부르지 않는다(끊어진 녹화를 이어 하기).

    overwrite=True 면 기존 키도 다시 불러 새 줄을 덧붙인다(읽을 때 마지막 줄이 이긴다).
    """

    def __init__(self, http: HttpProvider, path: str | Path, overwrite: bool = False):
        self.http = http
        self.path = Path(path)
        self.overwrite = overwrite
        self.store = CassetteProvider(self.path)  # 기존 녹화(이어 하기용). 이 실행에서 부른 만큼만 늘어난다.
        self.reused = 0  # 이미 녹화돼 있어 모델을 부르지 않고 건너뛴 요청 수
        self.recorded = 0  # 이번 실행에서 실제로 모델을 불러 새로 녹화한 요청 수
        self.lock = threading.Lock()  # 워커 스레드가 한 줄씩 안전하게 쓰도록
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _record(self, kind: str, request: dict, repeat: int, response, call):
        key = request_key(kind, request, repeat)
        if not self.overwrite and key in self.store.entries:
            with self.lock:
                self.reused += 1
            return self.store.entries[key]["response"]
        response = call()
        entry = {"req_hash": key, "kind": kind, "model": request["model"], "request": _summary(kind, request), "response": response,
                 "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": f"evalgate {__version__}"}
        with self.lock:
            with self.path.open("a", encoding="utf-8") as f:  # 한 줄씩 바로 flush — 중간에 끊겨도 지금까지 분은 남는다
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.store.entries[key] = entry
            self.recorded += 1
        return response

    def chat(self, request: dict, repeat: int = 0, label: str = "") -> str:
        return self._record("chat", request, repeat, None, lambda: self.http.chat(request, repeat, label))

    def embed(self, request: dict, label: str = "") -> list[float]:
        return self._record("embed", request, 0, None, lambda: self.http.embed(request, label))


def make_provider(cfg: dict):
    """설정의 mode 에 맞는 공급원을 만든다."""
    mode, m = cfg["run"]["mode"], cfg["model"]
    if mode == "mock":
        return CassetteProvider(cfg["run"]["cassette"])
    http = HttpProvider(m["base_url"], m["api_key"], float(m["timeout"]))
    if mode == "real":
        return http
    return RecordingProvider(http, cfg["run"]["cassette"], overwrite=bool(cfg["run"].get("overwrite")))
