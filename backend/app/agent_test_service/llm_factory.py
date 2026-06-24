"""LLM Provider 工厂：根据名字构造 ChatOpenAI 客户端，并对外暴露可用 provider 列表。

支持两种 provider：
- ``online``：使用 ``AGENT_LLM_*`` 配置（标准 OpenAI / 任意 OpenAI 兼容服务）。
- ``local`` ：使用 ``AGENT_LOCAL_*`` 配置（默认指向宿主机 Ollama 的 ``/v1`` 端点）。

未配置 / 未知 provider 时返回 ``None``，调用方应回退到启发式逻辑。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Literal

import httpx
from langchain_openai import ChatOpenAI

from app.agent_test_service.agent_logger import get_agent_logger
from app.config import settings

logger = get_agent_logger()

PROBE_TIMEOUT_SECONDS = 2.5

ProviderId = Literal["online", "local"]
ALL_PROVIDERS: tuple[ProviderId, ...] = ("local", "online")


@dataclass(frozen=True)
class ProviderSpec:
    id: ProviderId
    label: str
    model: str
    base_url: str
    available: bool


def _online_spec() -> ProviderSpec:
    return ProviderSpec(
        id="online",
        label=f"在线 LLM · {settings.agent_llm_model}",
        model=settings.agent_llm_model,
        base_url=settings.agent_llm_base_url or "https://api.openai.com/v1",
        # 仅判断"配置完整"，真正的可达性由 probe_providers() 决定
        available=bool(settings.agent_llm_api_key),
    )


def _local_spec() -> ProviderSpec:
    return ProviderSpec(
        id="local",
        label=f"本地 Ollama · {settings.agent_local_model}",
        model=settings.agent_local_model,
        base_url=settings.agent_local_base_url,
        available=bool(settings.agent_local_base_url and settings.agent_local_model),
    )


def list_providers() -> list[ProviderSpec]:
    return [_local_spec(), _online_spec()]


async def _probe_one(spec: ProviderSpec) -> ProviderSpec:
    """对单个 provider 发起轻量请求探活。

    - 未配置完整 → 直接保持 available=False
    - 任意 HTTP 响应（包括 401/404）→ 视为可达
    - 连接异常 / 超时 → 不可达
    - online provider 还会顺便校验下当前 model 是否在 /models 列表里
    """
    if not spec.available:
        return spec

    url = f"{spec.base_url.rstrip('/')}/models"
    headers: dict[str, str] = {}
    if spec.id == "online" and settings.agent_llm_api_key:
        headers["Authorization"] = f"Bearer {settings.agent_llm_api_key}"
    elif spec.id == "local":
        headers["Authorization"] = f"Bearer {settings.agent_local_api_key or 'ollama'}"

    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
    except Exception as exc:
        logger.info("[llm_factory] probe %s 不可达 url=%s err=%s", spec.id, url, exc)
        return replace(spec, available=False)

    # 任何 2xx/4xx 都说明端点活着；5xx 也算可达但通常意味着服务端有问题，仍标记为可达
    if response.status_code >= 200:
        # 对 local provider 顺便确认模型在不在
        if spec.id == "local" and response.status_code == 200:
            try:
                payload = response.json()
                names = {item.get("id") for item in payload.get("data", [])}
                if names and spec.model not in names:
                    logger.warning(
                        "[llm_factory] probe local 可达但模型 %s 不在列表，已有=%s",
                        spec.model,
                        sorted(names),
                    )
                    return replace(
                        spec,
                        available=False,
                        label=f"{spec.label}（模型未拉取）",
                    )
            except Exception as exc:
                logger.debug("[llm_factory] 解析 local /models 失败: %s", exc)

        logger.debug("[llm_factory] probe %s OK status=%d", spec.id, response.status_code)
        return replace(spec, available=True)

    logger.info("[llm_factory] probe %s 异常响应 status=%d", spec.id, response.status_code)
    return replace(spec, available=False)


async def probe_providers() -> list[ProviderSpec]:
    """对所有 provider 并发探活，返回带最新 available 的 spec 列表。"""
    specs = list_providers()
    return list(await asyncio.gather(*(_probe_one(spec) for spec in specs)))


def default_provider() -> ProviderId | None:
    """根据 settings 选择默认 provider；找不到可用 provider 时返回 None。"""
    preferred = (settings.agent_default_provider or "").strip().lower()
    if preferred in ALL_PROVIDERS:
        spec = _spec_of(preferred)  # type: ignore[arg-type]
        if spec.available:
            return spec.id  # type: ignore[return-value]
    for spec in list_providers():
        if spec.available:
            return spec.id  # type: ignore[return-value]
    return None


def _spec_of(provider: ProviderId) -> ProviderSpec:
    if provider == "online":
        return _online_spec()
    return _local_spec()


class LLMFactory:
    """按 provider 缓存 ChatOpenAI 客户端，避免重复构造。"""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], ChatOpenAI] = {}

    def build(
        self, provider: str | None, *, model_override: str | None = None
    ) -> ChatOpenAI | None:
        resolved = self._resolve_provider(provider)
        if resolved is None:
            return None

        spec = _spec_of(resolved)
        model = model_override or spec.model
        cache_key = (resolved, model)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        if resolved == "online":
            if not settings.agent_llm_api_key:
                logger.warning("[llm_factory] online provider 无 api_key，跳过")
                return None
            client = ChatOpenAI(
                api_key=settings.agent_llm_api_key,
                base_url=settings.agent_llm_base_url or None,
                model=model,
                temperature=0,
            )
        else:  # local
            client = ChatOpenAI(
                api_key=settings.agent_local_api_key or "ollama",
                base_url=settings.agent_local_base_url,
                model=model,
                temperature=0,
            )

        self._cache[cache_key] = client
        logger.info(
            "[llm_factory] 构造 LLM provider=%s model=%s base_url=%s",
            resolved,
            model,
            spec.base_url,
        )
        return client

    def describe(self, provider: str | None) -> str:
        resolved = self._resolve_provider(provider)
        if resolved is None:
            return "未配置"
        spec = _spec_of(resolved)
        return f"{spec.label} / {spec.model}"

    def _resolve_provider(self, provider: str | None) -> ProviderId | None:
        if provider:
            normalized = provider.strip().lower()
            if normalized in ALL_PROVIDERS:
                return normalized  # type: ignore[return-value]
            logger.warning("[llm_factory] 未知 provider=%s，回退默认", provider)
        return default_provider()


llm_factory = LLMFactory()
