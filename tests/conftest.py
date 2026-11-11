"""테스트 공용 도구: 프로젝트 복사본 만들기, 표준 라이브러리 HTTP 스텁 서버."""

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path, monkeypatch):
    """저장소의 설정·평가 세트·프롬프트·녹화·기준선을 임시 폴더에 복사하고 그 안으로 이동한다(보고서가 저장소를 어지럽히지 않도록)."""
    for name in ("evalgate.toml", "evals", "prompts", "cassettes"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, tmp_path / name)
        else:
            shutil.copy(src, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    for var in ("EVALGATE_MODE", "EVALGATE_BASE_URL", "EVALGATE_API_KEY", "EVALGATE_MODEL", "EVALGATE_JUDGE_MODEL",
                "EVALGATE_EMBED_MODEL", "EVALGATE_WORKERS", "EVALGATE_TIMEOUT", "GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(var, raising=False)
    # 기존 테스트의 기대 문구는 한국어다 — 언어 결정 입력을 모두 비우고 EVALGATE_LANG=ko 로 고정한다
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("EVALGATE_LANG", "ko")
    return tmp_path


class StubServer:
    """OpenAI 호환 흉내 서버. 받은 요청을 requests 에 쌓고, 정해진 응답을 돌려준다."""

    def __init__(self):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # 테스트 출력 조용히
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                if self.path.endswith("/embeddings"):
                    text = body["input"]
                    payload = {"data": [{"embedding": [1.0, float(len(text) % 5), 0.123456789]}]}
                else:
                    user = body["messages"][-1]["content"]
                    if "채점자" in user:
                        content = "판정: PASS\n이유: 스텁 심판"
                    elif "THINK" in user:
                        content = "생각 중...\n</think>\n분류: 배송\n최종 답"
                    else:
                        content = "분류: 배송\n결제 후 2영업일 이내 출고됩니다."
                    payload = {"choices": [{"message": {"content": content, "reasoning": "숨은 생각"}}]}
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def stub():
    s = StubServer()
    yield s
    s.close()
