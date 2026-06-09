"""NVIDIA NIM nano renderer adapter (Tier 1.5).

Model: nvidia/llama-3.1-nemotron-nano-8b-v1
Target latency: 0.47-1.36s.

Endpoint speaks OpenAI /v1/chat/completions format.
"""

from __future__ import annotations

from aegis.renderer.openai_compat import OpenAICompatRenderer

_renderer = OpenAICompatRenderer(
    model="nvidia/llama-3.1-nemotron-nano-8b-v1",
    endpoint_url="https://integrate.api.nvidia.com/v1/chat/completions",
    api_key_env="NVIDIA_API_KEY",
    name="nim_nano",
    timeout=10.0,
)


async def render(intent: dict) -> str:
    """Render an intent packet via NVIDIA NIM nano.

    Public signature matches gemini.render() and groq.render()
    so the dispatcher adapter can call it transparently.
    """
    return await _renderer.render(intent)
