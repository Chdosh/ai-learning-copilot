from __future__ import annotations

import json
import struct
import urllib.request
from typing import Optional

from app.services.settings import AppSettings


class EmbeddingService:
    def __init__(self, settings: AppSettings, model: str = "text-embedding-3-small") -> None:
        self.settings = settings
        self.model = model

    def get_embedding(self, text: str) -> Optional[bytes]:
        if not text.strip() or not self.settings.api_key:
            return None
        try:
            result = self._call_api(text)
            if result:
                return self._pack_embedding(result)
        except Exception:
            return None
        return None

    def _call_api(self, text: str) -> Optional[list[float]]:
        payload = json.dumps({
            "model": self.model,
            "input": text[:8000],
        }).encode("utf-8")

        base_url = self.settings.base_url.rstrip("/")
        if "/v1" not in base_url:
            base_url = f"{base_url}/v1"
        url = f"{base_url}/embeddings"

        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("data", [{}])[0].get("embedding")
        except Exception:
            return None

    def _pack_embedding(self, vector: list[float]) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    @staticmethod
    def unpack_embedding(data: bytes) -> list[float]:
        count = len(data) // 4
        return list(struct.unpack(f"{count}f", data))

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
