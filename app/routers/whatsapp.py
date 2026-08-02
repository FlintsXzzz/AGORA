"""
app/routers/whatsapp.py
------------------------
Meta Cloud API webhook endpoints for the AGORA WhatsApp bot.

Endpoints:
  GET  /whatsapp/webhook  – Meta webhook verification challenge.
  POST /whatsapp/webhook  – Inbound messages (image → OCR+RAG; text → echo).

User auto-provisioning: any wa_id that sends a message is auto-created
under a default "walk-in" tenant, so no prior registration is required.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.services.ocr import call_nemotron_ocr
from app.services.rag import rag_service
from app.services.whatsapp_meta import meta_client
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# UUID for the default "walk-in" tenant used for auto-provisioned users.
# Change this to your real default tenant ID if needed.
_DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_uuid(value: Any, fallback_key: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, fallback_key)


def _format_idr_amount(value: Any) -> str:
    amount = float(value or 0)
    return f"{amount:,.0f}".replace(",", ".")

async def _get_or_create_tenant(db: AsyncSession) -> models.Tenant:
    result = await db.execute(
        select(models.Tenant).where(models.Tenant.id == _DEFAULT_TENANT_ID)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = models.Tenant(
            id=_DEFAULT_TENANT_ID,
            business_name="Walk-In Users",
            subscription_tier="FREE",
        )
        db.add(tenant)
        await db.flush()
    return tenant


async def _get_or_create_user(db: AsyncSession, wa_id: str) -> models.User:
    """Return existing user or auto-provision one from the wa_id."""
    result = await db.execute(
        select(models.User).where(models.User.whatsapp_number == wa_id)
    )
    user = result.scalar_one_or_none()
    if user:
        return user
    tenant = await _get_or_create_tenant(db)
    user = models.User(
        tenant_id=tenant.id,
        whatsapp_number=wa_id,
        role=models.RoleEnum.EMPLOYEE,
    )
    db.add(user)
    await db.flush()
    return user


def _extract_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Safely parse messages from a Meta Cloud API webhook body."""
    try:
        return (
            body["entry"][0]["changes"][0]["value"].get("messages") or []
        )
    except (KeyError, IndexError):
        return []


def _format_receipt_reply(enriched: dict[str, Any]) -> str:
    """Return the RAG-generated summary or build a fallback."""
    summary = enriched.get("_rag_summary")
    if summary:
        return str(summary)
    merchant = enriched.get("merchant_name", "")
    total = enriched.get("total_amount", 0)
    items = enriched.get("items", [])
    lines = [f"🧾 *Struk{' dari ' + merchant if merchant else ''} berhasil direkam!*"]
    for item in items[:5]:
        lines.append(
            f"• {item.get('item')} x{item.get('quantity', 1)} = Rp{_format_idr_amount(item.get('price', 0))}"
        )
    if len(items) > 5:
        lines.append(f"  ... dan {len(items) - 5} item lainnya")
    lines.append(f"*Total: Rp{_format_idr_amount(total)}*")
    lines.append(f"Kategori: {enriched.get('category', 'Uncategorized')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GET – Webhook verification
# ---------------------------------------------------------------------------

@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> Response:
    """
    Meta Cloud API verification handshake.
    Meta sends GET with hub.mode=subscribe and hub.verify_token.
    We must echo back hub.challenge if the token matches.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully.")
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning("Webhook verification failed – token mismatch.")
    raise HTTPException(status_code=403, detail="Verification token mismatch.")


# ---------------------------------------------------------------------------
# POST – Inbound messages
# ---------------------------------------------------------------------------

@router.post("/webhook")
@limiter.limit(f"{settings.OCR_RATE_LIMIT_PER_MINUTE}/minute")
async def receive_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Handle inbound WhatsApp messages from Meta Cloud API.
    - image messages → OCR + RAG + save transaction + reply.
    - text messages  → simple echo (extendable to RAG Q&A).
    """
    body: dict[str, Any] = await request.json()
    messages = _extract_messages(body)

    for message in messages:
        wa_id: str = message.get("from", "")
        msg_type: str = message.get("type", "")

        if not wa_id:
            continue

        async with db.begin():
            user = await _get_or_create_user(db, wa_id)

            if msg_type == "image":
                await _handle_image(db, user, message, wa_id)
            elif msg_type == "text":
                await _handle_text(db, user, message, wa_id)
            else:
                # Unsupported type – politely inform the user
                await meta_client.send_text(
                    wa_id,
                    "Halo! Saya AGORA Bot 🤖. Kirimkan foto struk untuk saya rekam secara otomatis.",
                )

    # Always return 200 to Meta to prevent retries
    return {"status": "ok"}


async def _handle_image(
    db: AsyncSession,
    user: models.User,
    message: dict[str, Any],
    wa_id: str,
) -> None:
    media_id: str = message.get("image", {}).get("id", "")
    if not media_id:
        await meta_client.send_text(wa_id, "Gagal membaca gambar. Mohon coba kirim ulang.")
        return

    try:
        image_bytes, content_type = await meta_client.download_media(media_id)
    except Exception as exc:
        logger.error("Media download failed: %s", exc)
        await meta_client.send_text(wa_id, "Gagal mengunduh gambar. Mohon coba lagi.")
        return

    # OCR
    try:
        ocr_payload = await call_nemotron_ocr(image_bytes, content_type)
    except HTTPException as exc:
        await meta_client.send_text(wa_id, f"OCR gagal: {exc.detail}")
        return

    # RAG enrichment
    try:
        enriched = await rag_service.process(db, ocr_payload)
    except Exception as exc:
        logger.warning("RAG enrichment failed, using raw OCR: %s", exc)
        enriched = ocr_payload

    # Persist transaction
    total = enriched.get("total_amount") or 0.0
    desc_parts = [
        f"{i.get('quantity', 1)}x {i.get('item', '')} @ {i.get('price', 0)}"
        for i in enriched.get("items", [])
    ]
    merchant = enriched.get("merchant_name", "")
    description = "\n".join(desc_parts)
    if merchant:
        description = f"Merchant: {merchant}\n" + description

    transaction = models.Transaction(
        tenant_id=_as_uuid(user.tenant_id, f"tenant:{wa_id}"),
        recorded_by=_as_uuid(user.id, f"user:{wa_id}"),
        type=models.TransactionTypeEnum.EXPENSE,
        amount=float(total),
        category=enriched.get("category") or "Uncategorized",
        description=description,
        raw_image_url=media_id,
    )
    db.add(transaction)

    # Reply to user
    reply = _format_receipt_reply(enriched)
    await meta_client.send_text(wa_id, reply)
    logger.info("Transaction saved for user %s, total=%s", wa_id, total)


async def _handle_text(
    db: AsyncSession,
    user: models.User,
    message: dict[str, Any],
    wa_id: str,
) -> None:
    text_body: str = message.get("text", {}).get("body", "").strip()
    logger.info("Text message from %s: %s", wa_id, text_body[:80])
    # Simple reply – can be extended to a RAG Q&A flow
    await meta_client.send_text(
        wa_id,
        "Halo! 👋 Kirimkan foto struk belanja Anda dan saya akan merekamnya secara otomatis ke AGORA.",
    )
