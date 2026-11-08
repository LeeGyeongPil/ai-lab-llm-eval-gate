"""설정 로드: evalgate.toml 을 읽고 EVALGATE_* 환경변수와 명령행 옵션으로 덮어쓴다.

우선순위: 명령행 옵션(overrides) > 환경변수 > evalgate.toml
dataclass 대신 평범한 dict 를 그대로 들고 다녀서, 설정 항목을 추가하려면 toml 에 한 줄만 쓰면 된다.
"""

import os
import tomllib
from pathlib import Path

# 환경변수 이름 → (섹션, 키, 형변환)
ENV_MAP = {
    "EVALGATE_MODE": ("run", "mode", str),
    "EVALGATE_WORKERS": ("run", "workers", int),
    "EVALGATE_BASE_URL": ("model", "base_url", str),
    "EVALGATE_API_KEY": ("model", "api_key", str),
    "EVALGATE_MODEL": ("model", "name", str),
    "EVALGATE_JUDGE_MODEL": ("model", "judge", str),
    "EVALGATE_EMBED_MODEL": ("model", "embed", str),
    "EVALGATE_TIMEOUT": ("model", "timeout", float),
}


class ConfigError(Exception):
    """설정 파일·값 오류 (CLI 에서 exit 2 로 바뀐다)."""


def load_config(path: str | Path = "evalgate.toml", overrides: dict | None = None) -> dict:
    """toml → 환경변수 → overrides 순으로 합친 설정 dict 를 돌려준다.

    overrides 는 {"run": {"mode": "real"}} 같은 중첩 dict 이고, 값이 None 이면 무시한다.
    상대 경로(cases·baseline·cassette·reports_dir)는 설정 파일이 있는 폴더 기준으로 풀어 둔다.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    for section in ("run", "model", "scorers", "gate"):
        cfg.setdefault(section, {})

    for env_name, (section, key, cast) in ENV_MAP.items():
        value = os.environ.get(env_name)
        if value:  # 빈 문자열은 "설정 안 함"으로 본다
            try:
                cfg[section][key] = cast(value)
            except ValueError as e:
                raise ConfigError(f"{env_name} 값이 올바르지 않습니다: {value!r}") from e

    for section, values in (overrides or {}).items():
        for key, value in values.items():
            if value is not None:
                cfg[section][key] = value

    if cfg["run"].get("mode") not in ("mock", "real", "record"):
        raise ConfigError(f"mode 는 mock / real / record 중 하나여야 합니다: {cfg['run'].get('mode')!r}")
    if not cfg["model"].get("judge"):
        cfg["model"]["judge"] = cfg["model"]["name"]  # 심판 모델 기본값 = 피평가 모델

    base = path.resolve().parent
    cfg["_root"] = base
    for key in ("cases", "baseline", "cassette", "reports_dir"):
        if key in cfg["run"]:
            cfg["run"][key] = str((base / cfg["run"][key]) if not os.path.isabs(cfg["run"][key]) else cfg["run"][key])
    return cfg
