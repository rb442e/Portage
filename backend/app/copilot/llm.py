"""Ollama chat client with streaming and native tool calling."""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, Iterator, List

import requests


class LLMUnavailable(RuntimeError):
    pass


def model_installed(names: List[str], model: str) -> bool:
    return any(n == model or n.split(":")[0] == model for n in names)


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def health(self) -> Dict[str, Any]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=3)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
        except (requests.RequestException, ValueError) as e:
            return {"reachable": False, "models": [], "model_available": False, "detail": str(e)[:200]}
        return {"reachable": True, "models": names, "model_available": model_installed(names, self.model),
                "detail": ""}

    def describe_images(self, images: List[bytes], prompt: str) -> str:
        """One non-streaming call to a vision model. Returns its text."""
        body = {"model": self.model, "stream": False, "options": {"temperature": 0.1, "num_ctx": 4096},
                "messages": [{"role": "user", "content": prompt,
                              "images": [base64.b64encode(i).decode() for i in images]}]}
        try:
            r = requests.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise LLMUnavailable(f"Cannot reach Ollama at {self.base_url}. ({str(e)[:120]})") from e
        if r.status_code == 404:
            raise LLMUnavailable(f"Vision model '{self.model}' not found. Run: ollama pull {self.model}")
        if r.status_code >= 400:
            raise LLMUnavailable(f"Vision model '{self.model}' could not run ({r.status_code}: {r.text[:160]}). "
                                 "Choose another vision model in Settings, for example gemma3:4b.")
        text = ((r.json().get("message") or {}).get("content") or "").strip()
        if not text:
            raise LLMUnavailable(f"Vision model '{self.model}' returned no text")
        return text

    def chat_stream(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """Yield {"type": "token", "text"} and {"type": "tool_calls", "calls": [{name, arguments}]}."""
        body: Dict[str, Any] = {
            "model": self.model, "messages": messages, "stream": True,
            "options": {"temperature": 0.1, "num_ctx": 8192},
        }
        if tools:
            body["tools"] = tools
        try:
            with requests.post(f"{self.base_url}/api/chat", json=body, stream=True, timeout=self.timeout) as r:
                if r.status_code == 404:
                    raise LLMUnavailable(f"Model '{self.model}' not found. Run: ollama pull {self.model}")
                if r.status_code >= 400:
                    raise LLMUnavailable(f"Ollama error {r.status_code}: {r.text[:200]}")
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise LLMUnavailable(str(chunk["error"])[:200])
                    msg = chunk.get("message") or {}
                    if msg.get("content"):
                        yield {"type": "token", "text": msg["content"]}
                    calls = msg.get("tool_calls")
                    if calls:
                        yield {"type": "tool_calls", "calls": [
                            {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or {}}
                            for c in calls]}
        except requests.RequestException as e:
            raise LLMUnavailable(
                f"Cannot reach Ollama at {self.base_url}. Start it with `ollama serve`. ({str(e)[:120]})") from e
