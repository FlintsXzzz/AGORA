"""
app/services/rag.py
--------------------
RAG (Retrieval-Augmented Generation) service for AGORA.

Pipeline:
  1. Embed  – turn text into a 768-dim vector via NVIDIA nv-embed-v2.
  2. Retrieve – cosine similarity search against the `documents` table.
  3. Enrich  – call a generation model to produce category inference,
                merchant suggestions, and a user-friendly summary.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.settings import settings

logger = logging.getLogger(__name__)


def _format_idr_amount(value: Any) -> str:
    amount = float(value or 0)
    return f"{amount:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

async def embed_text(text_input: str) -> list[float] | None:
    """
    Call the NVIDIA NV-Embed-v2 model to produce a 768-dim vector.
    Returns None on failure (embedding is optional for storage).
    """
    payload = {
        "model": settings.NVIDIA_EMBED_MODEL,
        "input": text_input,
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    embed_url = settings.NVIDIA_API_URL.replace(
        "/chat/completions", "/embeddings"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(embed_url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            return data["data"][0]["embedding"]
        logger.warning("Embedding call failed: HTTP %s", response.status_code)
    except Exception as exc:
        logger.warning("Embedding exception: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

async def retrieve_similar(
    db: AsyncSession,
    query_embedding: list[float],
    top_k: int = 5,
    source_filter: str | None = None,
) -> list[models.Document]:
    """
    Retrieve the top-k most similar documents using pgvector cosine distance.
    Optionally filter by `source` (e.g. "product_catalogue").
    """
    # Build the raw SQL for pgvector cosine similarity
    vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    if source_filter:
        sql = text(
            "SELECT * FROM documents "
            "WHERE source = :src "
            "ORDER BY embedding <=> CAST(:vec AS vector) "
            "LIMIT :k"
        )
        result = await db.execute(sql, {"src": source_filter, "vec": vec_str, "k": top_k})
    else:
        sql = text(
            "SELECT * FROM documents "
            "ORDER BY embedding <=> CAST(:vec AS vector) "
            "LIMIT :k"
        )
        result = await db.execute(sql, {"vec": vec_str, "k": top_k})

    rows = result.mappings().all()
    # Convert raw rows to Document-like objects for consistent access
    docs = []
    for row in rows:
        doc = models.Document()
        doc.id = row["id"]
        doc.source = row["source"]
        doc.content = row["content"]
        doc.metadata_ = row["metadata_"]
        doc.embedding = row["embedding"]
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
# Generation / Enrichment
# ---------------------------------------------------------------------------

_ENRICH_SYSTEM = (
    "You are a financial data assistant for AGORA, a small-business expense tracker. "
    "Given an OCR-extracted receipt JSON and relevant context documents, produce a "
    "structured JSON enrichment with these fields:\n"
    "  merchant_name: corrected merchant name (string)\n"
    "  category: best-fit expense category (string)\n"
    "  summary: short human-readable WhatsApp reply in Bahasa Indonesia (≤80 words)\n"
    "  confidence: float 0.0–1.0 reflecting enrichment confidence\n"
    "Return ONLY valid JSON. No explanation outside the JSON object."
)


async def enrich_receipt(
    ocr_payload: dict[str, Any],
    context_docs: list[models.Document],
) -> dict[str, Any]:
    """
    Use a generation model to enrich OCR output with merchant/category
    suggestions and a human-friendly summary, given retrieved context docs.

    Falls back gracefully to the raw OCR payload if generation fails.
    """
    context_text = "\n---\n".join(
        f"[{doc.source}] {doc.content}" for doc in context_docs
    )
    user_message = (
        f"Receipt OCR output:\n{json.dumps(ocr_payload, ensure_ascii=False)}\n\n"
        f"Context documents:\n{context_text}"
    )

    request_payload = {
        "model": settings.NVIDIA_GEN_MODEL,
        "messages": [
            {"role": "system", "content": _ENRICH_SYSTEM},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": 512,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                settings.NVIDIA_API_URL, headers=headers, json=request_payload
            )
        if response.status_code == 200:
            raw = response.json()["choices"][0]["message"]["content"]
            # Strip markdown code fences if present
            import re
            cleaned = re.sub(r"```(?:json)?\n?|```", "", raw).strip()
            enriched = json.loads(cleaned)
            return enriched
        logger.warning("Enrich call failed: HTTP %s", response.status_code)
    except Exception as exc:
        logger.warning("Enrich exception: %s", exc)

    # Graceful fallback
    return {
        "merchant_name": ocr_payload.get("merchant_name", ""),
        "category": ocr_payload.get("category", "Uncategorized"),
        "summary": _default_summary(ocr_payload),
        "confidence": 0.0,
    }


def _default_summary(ocr_payload: dict[str, Any]) -> str:
    items = ocr_payload.get("items", [])
    total = ocr_payload.get("total_amount", 0)
    merchant = ocr_payload.get("merchant_name", "")
    lines = [f"🧾 *Struk{' dari ' + merchant if merchant else ''}*"]
    for item in items[:5]:
        lines.append(
            f"• {item.get('item', '')} x{item.get('quantity', 1)} = Rp{_format_idr_amount(item.get('price', 0))}"
        )
    if len(items) > 5:
        lines.append(f"  ... dan {len(items) - 5} item lainnya")
    lines.append(f"*Total: Rp{_format_idr_amount(total)}*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

class RAGService:
    """
    Orchestrates the full Embed → Retrieve → Enrich pipeline.
    """

    async def process(
        self,
        db: AsyncSession,
        ocr_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Given validated OCR output, return an enriched payload that includes
        merchant_name, category, summary, and confidence.
        """
        # Build query text from receipt content
        query_text = " ".join(
            filter(
                None,
                [
                    ocr_payload.get("merchant_name"),
                    ocr_payload.get("category"),
                    " ".join(
                        str(i.get("item", "")) for i in ocr_payload.get("items", [])
                    ),
                ],
            )
        )

        embedding = await embed_text(query_text) if query_text.strip() else None

        context_docs: list[models.Document] = []
        if embedding:
            context_docs = await retrieve_similar(db, embedding, top_k=5)

        enriched = await enrich_receipt(ocr_payload, context_docs)

        # Merge enriched fields back into OCR payload (enrichment takes priority)
        merged = {
            **ocr_payload,
            "merchant_name": enriched.get("merchant_name") or ocr_payload.get("merchant_name"),
            "category": enriched.get("category") or ocr_payload.get("category") or "Uncategorized",
            "_rag_summary": enriched.get("summary", _default_summary(ocr_payload)),
            "_rag_confidence": enriched.get("confidence", 0.0),
        }
        return merged


# Module-level singleton
rag_service = RAGService()
