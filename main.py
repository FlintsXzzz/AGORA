from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database import engine, get_db
import models
import os
import base64
import requests
import json
import uuid
import re
from datetime import datetime, timezone
from pathlib import Path
import threading
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# Memuat variabel environment
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="AGORA AI Engine", lifespan=lifespan)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
if not NVIDIA_API_KEY:
    raise RuntimeError("NVIDIA_API_KEY belum dikonfigurasi di environment atau .env")

# Endpoint standar NVIDIA NIM untuk model vision/multimodal
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

def normalize_ocr_payload(extracted_text: str) -> dict:
    cleaned_text = re.sub(r'```(?:json)?\n?|```', '', extracted_text).strip()
    try:
        parsed = json.loads(cleaned_text)
        if isinstance(parsed, dict):

            return parsed
    except Exception:
        pass

    return {
        "raw_text": extracted_text,
        "items": [],
        "total_amount": None,
        "currency": "IDR"
    }


def normalize_numeric_token(token: str) -> float | None:
    if token is None:
        return None

    normalized = str(token).strip()
    if not normalized:
        return None

    normalized = re.sub(r"[^0-9,\.\-]", "", normalized)
    if not re.search(r"\d", normalized):
        return None

    normalized = normalized.replace(" ", "")
    comma_count = normalized.count(",")
    dot_count = normalized.count(".")

    if comma_count > 0 and dot_count > 0:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "")
            normalized = normalized.replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif comma_count > 0:
        parts = normalized.split(",")
        if comma_count > 1 or len(parts[-1]) == 3:
            normalized = normalized.replace(",", "")
        else:
            normalized = normalized.replace(",", ".")
    elif dot_count > 1:
        normalized = normalized.replace(".", "")
    elif dot_count == 1:
        parts = normalized.split(".")
        if len(parts[-1]) == 3:
            normalized = normalized.replace(".", "")

    try:
        return float(normalized)
    except ValueError:
        return None


def normalize_integer_token(token: str) -> int | None:
    value = normalize_numeric_token(token)
    if value is None:
        return None

    if not value.is_integer():
        return None

    return int(value)


def fallback_parse_items(payload: dict) -> list[dict]:
    items = payload.get("items")
    if isinstance(items, list) and items:
        return items

    raw_text = str(payload.get("raw_text") or "")
    if not raw_text:
        return []

    fallback_items = []
    skip_prefixes = (
        "total",
        "bayar",
        "kasir",
        "tanggal",
        "transaksi",
        "terima kasih",
        "thank you",
        "subtotal",
        "diskon",
        "ppn",
        "kembalian",
        "cash",
        "alfamart",
        "indomaret",
        "receipt",
        "member",
        "promo",
        "alamat",
        "store",
        "no.",
        "nomor",
    )

    for line in raw_text.splitlines():
        cleaned = re.sub(r"\s+", " ", line.strip())
        if not cleaned:
            continue

        cleaned = re.sub(r"^\d+\.\s*", "", cleaned)
        lower_line = cleaned.lower()
        if lower_line.startswith(skip_prefixes):
            continue

        if not any(char.isdigit() for char in cleaned):
            continue

        patterns = [
            r"^(?P<name>.+?)\s+(?P<qty>\d+)\s*(?:x|X|@|\*)\s*(?P<price>\d+(?:[.,]\d{1,2})?)$",
            r"^(?P<name>.+?)\s+(?P<qty>\d+)\s+(?P<price>\d+(?:[.,]\d{1,2})?)$",
            r"^(?P<name>.+?)\s+(?P<price>\d+(?:[.,]\d{1,2})?)\s*(?:x|X|@|\*)\s*(?P<qty>\d+)$",
            r"^(?P<name>.+?)\s+(?P<price>\d+(?:[.,]\d{1,2})?)$",
        ]

        match = None
        for pattern in patterns:
            match = re.match(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                break

        if match:
            name = match.group("name").strip(" -:|")
            qty = match.groupdict().get("qty")
            price = match.groupdict().get("price")
            quantity = normalize_integer_token(qty) if qty else 1
            normalized_price = normalize_numeric_token(price or "0")

            if not quantity or quantity < 1:
                continue

            if name and normalized_price is not None and normalized_price >= 0:
                fallback_items.append({
                    "item": name,
                    "quantity": quantity,
                    "price": normalized_price,
                })
                continue

        parts = [part for part in re.split(r"\s+", cleaned) if part]
        numeric_tokens = []
        numeric_indexes = []
        for index, part in enumerate(parts):
            number = normalize_numeric_token(part)
            if number is not None:
                numeric_tokens.append(number)
                numeric_indexes.append(index)

        if len(parts) >= 2 and len(numeric_tokens) >= 2:
            first_num = numeric_tokens[0]
            second_num = numeric_tokens[-1]
            name_tokens = [part for index, part in enumerate(parts) if index not in numeric_indexes]
            name = " ".join(name_tokens).strip(" -:|")

            if first_num <= 10 and second_num > 10:
                quantity = int(first_num) if first_num >= 1 else 1
                price = second_num
            elif second_num <= 10 and first_num > 10:
                quantity = int(second_num) if second_num >= 1 else 1
                price = first_num
            else:
                quantity = 1
                price = second_num

            if name and price >= 0 and quantity >= 1:
                fallback_items.append({
                    "item": name,
                    "quantity": quantity,
                    "price": price,
                })

        elif len(parts) >= 2 and len(numeric_tokens) == 1:
            price = numeric_tokens[0]
            name_tokens = [part for index, part in enumerate(parts) if index not in numeric_indexes]
            name = " ".join(name_tokens).strip(" -:|")
            if name and price >= 0:
                fallback_items.append({
                    "item": name,
                    "quantity": 1,
                    "price": price,
                })

    deduped_items = []
    seen = set()
    for item in fallback_items:
        key = (item["item"].lower(), item["quantity"], item["price"])
        if key not in seen:
            seen.add(key)
            deduped_items.append(item)

    return deduped_items


def validate_ocr_output(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="OCR output harus berupa objek JSON.")

    items = payload.get("items")
    if not isinstance(items, list) or len(items) == 0:
        items = fallback_parse_items(payload)

    if not isinstance(items, list) or len(items) == 0:
        raise HTTPException(status_code=400, detail="Struk tidak terbaca jelas atau terpotong. Mohon kirimkan foto ulang yang lebih terang dan fokus.")

    normalized_items = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"Item ke-{index} tidak valid.")

        item_name = str(item.get("item") or item.get("name") or "").strip()
        quantity_value = item.get("quantity") if item.get("quantity") is not None else item.get("qty")
        price_value = item.get("price") if item.get("price") is not None else item.get("amount")

        if not item_name:
            item_name = f"item_{index}"
        if quantity_value is None:
            quantity_int = 1
        else:
            quantity_int = normalize_integer_token(quantity_value)
            if quantity_int is None:
                raise HTTPException(status_code=400, detail=f"Format quantity item '{item_name}' tidak valid.")
        if price_value is None:
            price_float = 0.0
        else:
            price_float = normalize_numeric_token(price_value)
            if price_float is None:
                raise HTTPException(status_code=400, detail=f"Format price item '{item_name}' tidak valid.")

        if quantity_int < 1:
            raise HTTPException(status_code=400, detail=f"Quantity item '{item_name}' harus lebih dari 0.")
        if price_float < 0:
            raise HTTPException(status_code=400, detail=f"Price item '{item_name}' tidak boleh negatif.")

        normalized_items.append({
            "item": item_name,
            "quantity": quantity_int,
            "price": price_float,
        })

    total_amount = payload.get("total_amount")
    if total_amount is None:
        total_amount = sum(item["price"] * item["quantity"] for item in normalized_items)
    else:
        total_amount = normalize_numeric_token(total_amount)
        if total_amount is None:
            raise HTTPException(status_code=400, detail="total_amount harus berupa angka.")

    if total_amount < 0:
        raise HTTPException(status_code=400, detail="total_amount tidak boleh negatif.")

    return {
        **payload,
        "items": normalized_items,
        "total_amount": total_amount,
        "currency": payload.get("currency") or "IDR"
    }


class TransactionItem(BaseModel):
    item: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1)
    price: float = Field(..., ge=0)


class SaveTransactionRequest(BaseModel):
    tenant_id: str
    user_id: str
    source: str = Field(default="whatsapp")
    receipt_filename: str | None = None
    items: list[TransactionItem] | None = None
    total_amount: float | None = Field(default=None, ge=0)
    notes: str | None = None
    merchant_name: str | None = None
    category: str | None = None
    transaction_date: str | None = None
    payment_method: str | None = None
    currency: str | None = "IDR"
    receipt_data: dict | None = None





def normalize_items_from_receipt_data(receipt_data: dict | None) -> list[TransactionItem]:
    if not isinstance(receipt_data, dict):
        return []

    raw_items = receipt_data.get("items") or []
    normalized_items = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        item_name = item.get("item") or item.get("name") or "Unknown Item"
        quantity_value = item.get("quantity") if item.get("quantity") is not None else item.get("qty")
        price_value = item.get("price") if item.get("price") is not None else item.get("amount")

        if quantity_value is None:
            quantity = 1
        else:
            quantity = normalize_integer_token(quantity_value)
            if quantity is None or quantity < 1:
                continue

        if price_value is None:
            price = 0.0
        else:
            price = normalize_numeric_token(price_value)
            if price is None or price < 0:
                continue

        normalized_items.append(
            TransactionItem(
                item=str(item_name),
                quantity=quantity,
                price=price,
            )
        )

    return normalized_items


@app.get("/")
def read_root():
    return {"message": "AGORA AI Engine is running securely."}


@app.get("/users/by-whatsapp/{number}")
def get_user_by_whatsapp(number: str, db: Session = Depends(get_db)):
    cleaned = re.sub(r"[^\d]", "", number)
    user = db.query(models.User).filter(models.User.whatsapp_number == cleaned).first()
    
    if not user:
        if cleaned.startswith("62"):
            alt_number = "0" + cleaned[2:]
            user = db.query(models.User).filter(models.User.whatsapp_number == alt_number).first()
        elif cleaned.startswith("0"):
            alt_number = "62" + cleaned[1:]
            user = db.query(models.User).filter(models.User.whatsapp_number == alt_number).first()

    if not user:
        raise HTTPException(status_code=404, detail="User tidak terdaftar dalam sistem.")
    
    return {
        "status": "success",
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role
    }


@app.post("/transactions")
def save_transaction(payload: SaveTransactionRequest, db: Session = Depends(get_db)):
    try:
        try:
            tenant_id = uuid.UUID(payload.tenant_id)
            user_id = uuid.UUID(payload.user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="tenant_id atau user_id tidak valid.")

        tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan.")
        
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User tidak ditemukan.")

        receipt_data = payload.receipt_data or {}
        normalized_items = payload.items or normalize_items_from_receipt_data(receipt_data)

        if not normalized_items:
            raise HTTPException(status_code=400, detail="Payload OCR harus berisi field items yang valid.")

        total_amount = payload.total_amount
        if total_amount is None:
            total_amount = float(sum(item.price * item.quantity for item in normalized_items))

        desc_parts = [f"{item.quantity}x {item.item} @ {item.price}" for item in normalized_items]
        description = "\n".join(desc_parts)
        if payload.notes:
            description += f"\nNotes: {payload.notes}"
        merchant_name = payload.merchant_name or receipt_data.get("merchant_name")
        if merchant_name:
            description = f"Merchant: {merchant_name}\n" + description

        new_transaction = models.Transaction(
            tenant_id=tenant.id,
            recorded_by=user.id,
            type=models.TransactionTypeEnum.EXPENSE,
            amount=total_amount,
            category=payload.category or receipt_data.get("category") or "Uncategorized",
            description=description,
            raw_image_url=payload.receipt_filename
        )

        db.add(new_transaction)
        db.commit()
        db.refresh(new_transaction)

        return {
            "status": "success",
            "message": "Transaction berhasil disimpan.",
            "transaction": {
                "transaction_id": str(new_transaction.id),
                "tenant_id": str(new_transaction.tenant_id),
                "recorded_by": str(new_transaction.recorded_by),
                "amount": float(new_transaction.amount),
                "created_at": new_transaction.created_at.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan transaksi: {str(exc)}")


@app.post("/extract-receipt")
def extract_receipt(file: UploadFile = File(...)):
    try:
        # 1. Membaca file gambar ke dalam buffer memori
        file_bytes = file.file.read()
        
        # 2. Mengubah format biner gambar menjadi string Base64 
        # (Wajib untuk transmisi payload JSON ke endpoint NVIDIA)
        base64_image = base64.b64encode(file_bytes).decode("utf-8")
        
        # 3. Menyiapkan header dan payload HTTP
        headers = {
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Prompt Engineering: Memaksa model untuk mengembalikan data terstruktur
        payload = {
            "model": "nvidia/nemotron-ocr-v2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Anda adalah agen OCR AGORA untuk struk Indonesia. Ekstrak data dari gambar struk/nota ini dan kembalikan JSON murni yang valid. Schema wajib: {\"merchant_name\": string, \"category\": string, \"transaction_date\": string|null, \"items\": [{\"item\": string, \"quantity\": integer, \"price\": number}], \"total_amount\": number, \"payment_method\": string|null, \"currency\": \"IDR\"}. Aturan: 1) gunakan bahasa yang umum dipakai di struk Indonesia, 2) item harus masuk ke array items, 3) quantity harus integer, 4) price harus angka numerik tanpa simbol mata uang, 5) total_amount harus angka numerik, 6) kalau quantity tidak tersedia, gunakan 1, 7) category HARUS disimpulkan dari nama item atau toko (misal: 'Food', 'Supplies', 'Transport', 'Utilities', 'Other'), 8) jangan tambahkan teks penjelasan apa pun sebelum atau sesudah JSON."
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{file.content_type};base64,{base64_image}"}
                        }
                    ]
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.1
        }
        
        # 4. Mengeksekusi request ke server NVIDIA
        print(f"Meneruskan task OCR ke NVIDIA untuk file: {file.filename}")
        try:
            response = requests.post(NVIDIA_API_URL, headers=headers, json=payload, timeout=30)
        except requests.exceptions.RequestException as req_err:
            print(f"Error Koneksi ke NVIDIA: {str(req_err)}")
            raise HTTPException(status_code=502, detail="Koneksi ke server OCR gagal atau timeout. Mohon coba lagi nanti.")
        
        # 5. Evaluasi dan Error Handling
        if response.status_code != 200:
            print(f"Error Response dari NVIDIA: {response.text}")
            if response.status_code in (401, 403):
                raise HTTPException(status_code=500, detail="Konfigurasi API Key OCR tidak valid.")
            elif response.status_code == 429:
                raise HTTPException(status_code=503, detail="Server OCR sedang sibuk, mohon coba beberapa saat lagi.")
            else:
                raise HTTPException(status_code=502, detail=f"Server OCR sedang mengalami gangguan (Error {response.status_code}).")
            
        response_data = response.json()
        
        # Mengekstrak teks dari struktur JSON balasan NVIDIA
        extracted_text = response_data['choices'][0]['message']['content']
        normalized_data = normalize_ocr_payload(extracted_text)
        validated_ocr = validate_ocr_output(normalized_data)
        
        # 6. Mengembalikan hasil ke Node.js Gateway
        return {
            "filename": file.filename,
            "status": "success",
            "data": validated_ocr
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Exception di AI Engine: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan internal server: {str(e)}")
