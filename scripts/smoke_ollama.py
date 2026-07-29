#!/usr/bin/env python
from __future__ import annotations

import asyncio
import json
from tempfile import TemporaryDirectory
from pathlib import Path

from glaceon_companion.config import ConfigStore
from glaceon_companion.ollama_client import OllamaClient, clean_model_text, parse_tool_call


async def run() -> dict[str, object]:
    with TemporaryDirectory(prefix="glaceon-ollama-") as temp:
        config = ConfigStore(Path(temp)).load()
        client = OllamaClient(config)
        prompts = {
            "es": "Salúdame en español con una frase muy corta.",
            "en": "Greet me in English with one very short sentence.",
            "gl": "Saúdame en galego cunha frase moi curta.",
        }
        replies: dict[str, str] = {}
        for language, prompt in prompts.items():
            response = await client.chat(
                [{"role": "user", "content": prompt}],
                "tranquilo",
                tools=False,
            )
            replies[language] = clean_model_text(
                (response.get("message") or {}).get("content")
            )
        proposed = await client.chat(
            [{"role": "user", "content": "Abre Steam."}],
            "tranquilo",
            tools=True,
        )
        return {
            "replies": replies,
            "tool_call": parse_tool_call(proposed.get("message") or {}),
        }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
