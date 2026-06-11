"""NVIDIA NIM mid renderer adapter (Tier 1.5).

Model: meta/llama-3.1-70b-instruct (same model as archaeology/consolidation).
Target latency: 2-5s (70B is slower than 8B nano but much better quality).

Endpoint speaks OpenAI /v1/chat/completions format.
"""

from aegis.renderer.openai_compat import OpenAICompatRenderer

_renderer = OpenAICompatRenderer(
    model="meta/llama-3.1-70b-instruct",
    endpoint_url="https://integrate.api.nvidia.com/v1/chat/completions",
    api_key_env="NVIDIA_API_KEY",
    name="nim_mid",
    timeout=15.0,
)


async def render(intent: dict) -> str:
    return await _renderer.render(intent)
