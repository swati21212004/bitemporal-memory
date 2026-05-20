"""
Bitemporal AI Memory System — Embedding service.

Provides an async interface for generating text embeddings via OpenAI's API.
The module exposes a :class:`EmbeddingProvider` protocol so the rest of the
codebase can depend on an abstraction rather than a concrete client, making
testing and future provider-swaps straightforward.

Usage::

    from src.services.embedding import get_embedding_service

    service = get_embedding_service()
    vec = await service.embed("The user prefers dark-mode.")
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI

from src.config import settings

logger = logging.getLogger(__name__)

# ── Abstract interface ───────────────────────────────────────────────────────


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Async protocol for text-to-vector embedding providers.

    Any class that implements :meth:`embed` and :meth:`embed_batch` with
    matching signatures satisfies this protocol without explicit inheritance.
    """

    async def embed(self, text: str) -> list[float]:
        """Return a single embedding vector for *text*."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of texts."""
        ...


# ── OpenAI implementation ────────────────────────────────────────────────────


class OpenAIEmbeddingService:
    """
    Concrete :class:`EmbeddingProvider` backed by the OpenAI Embeddings API.

    Parameters
    ----------
    api_key : str
        OpenAI API key (sourced from :data:`settings`).
    model : str
        Embedding model name, e.g. ``"text-embedding-3-small"``.

    Notes
    -----
    * The OpenAI embeddings endpoint accepts up to **2 048** inputs per call,
      but we cap each batch slice at **100** to stay well within rate limits
      and avoid excessively large payloads.
    * The ``AsyncOpenAI`` client handles retries / back-off internally.
    """

    _MAX_BATCH_SIZE: int = 100

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Parameters
        ----------
        text : str
            The input text to embed.

        Returns
        -------
        list[float]
            A 1 536-dimensional (default) embedding vector.

        Raises
        ------
        openai.APIError
            Propagated from the underlying OpenAI client on transient or
            permanent API failures.
        """
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts, automatically chunking into batches.

        Parameters
        ----------
        texts : list[str]
            Up to several thousand input strings.

        Returns
        -------
        list[list[float]]
            Embedding vectors in the same order as *texts*.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        for start in range(0, len(texts), self._MAX_BATCH_SIZE):
            batch = texts[start : start + self._MAX_BATCH_SIZE]
            logger.debug(
                "Embedding batch [%d–%d] of %d texts",
                start,
                start + len(batch) - 1,
                len(texts),
            )
            response = await self._client.embeddings.create(
                model=self._model,
                input=batch,
            )
            # The API returns embeddings in input order; be defensive and
            # sort by the ``index`` field just in case.
            sorted_data = sorted(response.data, key=lambda d: d.index)
            all_embeddings.extend(d.embedding for d in sorted_data)

        return all_embeddings


# ── Module-level singleton accessor ──────────────────────────────────────────

_singleton: OpenAIEmbeddingService | None = None


def get_embedding_service() -> EmbeddingProvider:
    """
    Return the module-level :class:`OpenAIEmbeddingService` singleton.

    The instance is created lazily on first call using the current
    :data:`src.config.settings`.

    Returns
    -------
    EmbeddingProvider
        The shared embedding service instance.
    """
    global _singleton  # noqa: PLW0603
    if _singleton is None:
        _singleton = OpenAIEmbeddingService(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
        )
    return _singleton
