from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bool_from_text(value: Any, default: bool) -> bool:
    if value is None:
        return default
    lowered = _text(value).lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _int_from_text(value: Any, default: int, minimum: int = 1) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        number = default
    return max(minimum, number)


@dataclass(frozen=True)
class OllamaConfig:
    enabled: bool
    base_url: str
    model: str
    timeout_seconds: int
    max_output_tokens: int
    max_prompt_chars: int

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None = None, environ: dict[str, str] | None = None) -> "OllamaConfig":
        environ = environ or os.environ
        mapping = mapping or {}
        default_enabled = _bool_from_text(environ.get("OLLAMA_ENABLED", "false"), False)
        default_base_url = _text(environ.get("OLLAMA_BASE_URL")) or "http://127.0.0.1:11434"
        default_model = _text(environ.get("OLLAMA_MODEL")) or "qwen3:4b"
        default_timeout = _int_from_text(environ.get("OLLAMA_TIMEOUT_SECONDS", "120"), 120)
        default_max_tokens = _int_from_text(environ.get("OLLAMA_MAX_OUTPUT_TOKENS", "1200"), 1200)
        default_max_prompt_chars = _int_from_text(environ.get("OLLAMA_MAX_PROMPT_CHARS", "24000"), 24000)
        return cls(
            enabled=_bool_from_text(mapping.get("ollama_enabled"), default_enabled),
            base_url=_text(mapping.get("ollama_base_url")) or default_base_url,
            model=_text(mapping.get("ollama_model")) or default_model,
            timeout_seconds=_int_from_text(mapping.get("ollama_timeout_seconds"), default_timeout),
            max_output_tokens=_int_from_text(mapping.get("ollama_max_output_tokens"), default_max_tokens),
            max_prompt_chars=_int_from_text(mapping.get("ollama_max_prompt_chars"), default_max_prompt_chars),
        )

    def as_profile_fields(self) -> dict[str, str]:
        return {
            "ollama_enabled": "true" if self.enabled else "false",
            "ollama_base_url": self.base_url,
            "ollama_model": self.model,
            "ollama_timeout_seconds": str(self.timeout_seconds),
            "ollama_max_output_tokens": str(self.max_output_tokens),
            "ollama_max_prompt_chars": str(self.max_prompt_chars),
        }


def ollama_profile_defaults(environ: dict[str, str] | None = None) -> dict[str, str]:
    return OllamaConfig.from_mapping(environ=environ).as_profile_fields()


def build_ollama_health_report(config: OllamaConfig) -> dict[str, Any]:
    report: dict[str, Any] = {
        "enabled": config.enabled,
        "base_url": config.base_url,
        "model_name": config.model,
        "timeout_seconds": config.timeout_seconds,
        "max_output_tokens": config.max_output_tokens,
        "max_prompt_chars": config.max_prompt_chars,
        "reachable": False,
        "model_available": False,
        "status": "disabled" if not config.enabled else "unavailable",
        "summary": "Ollama is disabled." if not config.enabled else f"Checking {config.model} at {config.base_url}",
        "failure_reason": "",
        "pull_command": f"ollama pull {config.model}",
        "available_models": [],
    }
    if not config.enabled:
        return report

    url = urljoin(config.base_url.rstrip("/") + "/", "api/tags")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        report["status"] = "error"
        report["failure_reason"] = f"HTTP {exc.code} from Ollama."
        report["summary"] = report["failure_reason"]
        return report
    except urllib.error.URLError as exc:
        report["status"] = "error"
        report["failure_reason"] = f"Could not reach Ollama: {getattr(exc, 'reason', exc)}"
        report["summary"] = report["failure_reason"]
        return report
    except TimeoutError:
        report["status"] = "timeout"
        report["failure_reason"] = "Ollama health check timed out."
        report["summary"] = report["failure_reason"]
        return report
    except json.JSONDecodeError:
        report["status"] = "error"
        report["failure_reason"] = "Ollama returned invalid JSON."
        report["summary"] = report["failure_reason"]
        return report

    models = payload.get("models") if isinstance(payload, dict) else []
    available_models = []
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name")) or _text(item.get("model"))
            if name:
                available_models.append(name)
    report["reachable"] = True
    report["available_models"] = available_models
    if any(name == config.model or name.startswith(f"{config.model}:") for name in available_models):
        report["model_available"] = True
        report["status"] = "ok"
        report["summary"] = f"{config.model} is available and Ollama is reachable."
        return report

    report["status"] = "missing_model"
    report["failure_reason"] = f"Model {config.model} is not installed."
    report["summary"] = f"{report['failure_reason']} Run `{report['pull_command']}`."
    return report
