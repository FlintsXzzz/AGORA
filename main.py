from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel, Field
import os
import base64
import requests
import json
import uuid
import re
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Memuat variabel environment
load_dotenv()

app = FastAPI(title="AGORA AI Engine")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Endpoint standar NVIDIA NIM untuk model vision/multimodal
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
STORAGE_DIR = Path(os.getenv("AGORA_STORAGE_DIR", Path.cwd()))
TRANSACTIONS_FILE = STORAGE_DIR / "transactions.json"


def normalize_ocr_payload(extracted_text: str) -> dict:
    try:
        parsed = json.loads(extracted_text)
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
    cleaned = token.strip().replace("Rp", "").replace("IDR", "")
    cleaned = cleaned.replace(".", "").replace(",", ".")

    if not re.search(r"\d", cleaned):
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


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
            quantity = int(qty) if qty else 1
            normalized_price = normalize_numeric_token(price or "0")

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
                quantity = int(first_num)
                price = second_num
            elif second_num <= 10 and first_num > 10:
                quantity = int(second_num)
                price = first_num
            else:
                quantity = 1
                price = second_num

            if name and price > 0:
                fallback_items.append({
                    "item": name,
                    "quantity": quantity,
                    "price": price,
                })

        elif len(parts) >= 2 and len(numeric_tokens) == 1:
            price = numeric_tokens[0]
            name_tokens = [part for index, part in enumerate(parts) if index not in numeric_indexes]
            name = " ".join(name_tokens).strip(" -:|")
            if name and price > 0:
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
        raise HTTPException(status_code=400, detail="OCR output harus berisi minimal 1 item transaksi.")

    normalized_items = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"Item ke-{index} tidak valid.")

        item_name = str(item.get("item") or item.get("name") or "").strip()
        quantity = item.get("quantity") if item.get("quantity") is not None else item.get("qty")
        price = item.get("price") if item.get("price") is not None else item.get("amount")

        if not item_name:
            item_name = f"item_{index}"
        if quantity is None:
            quantity = 1
        if price is None:
            price = 0

        try:
            quantity_int = int(quantity)
            price_float = float(price)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Format quantity atau price pada item '{item_name}' tidak valid.")

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
        try:
            total_amount = float(total_amount)
        except (TypeError, ValueError):
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
    source: str = Field(default="whatsapp")
    receipt_filename: str | None = None
    items: list[TransactionItem] | None = None
    total_amount: float | None = Field(default=None, ge=0)
    notes: str | None = None
    merchant_name: str | None = None
    transaction_date: str | None = None
    payment_method: str | None = None
    currency: str | None = "IDR"
    receipt_data: dict | None = None


class TransactionRecord(BaseModel):
    transaction_id: str
    source: str
    receipt_filename: str | None = None
    items: list[TransactionItem]
    total_amount: float | None = None
    notes: str | None = None
    merchant_name: str | None = None
    transaction_date: str | None = None
    payment_method: str | None = None
    currency: str | None = "IDR"
    saved_at: str


def ensure_storage_file() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if not TRANSACTIONS_FILE.exists():
        TRANSACTIONS_FILE.write_text("[]", encoding="utf-8")


def load_transactions() -> list[dict]:
    ensure_storage_file()
    try:
        with TRANSACTIONS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def save_transactions(transactions: list[dict]) -> None:
    ensure_storage_file()
    with TRANSACTIONS_FILE.open("w", encoding="utf-8") as file:
        json.dump(transactions, file, indent=2, ensure_ascii=False)


def normalize_items_from_receipt_data(receipt_data: dict | None) -> list[TransactionItem]:
    if not isinstance(receipt_data, dict):
        return []

    raw_items = receipt_data.get("items") or []
    normalized_items = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        normalized_items.append(
            TransactionItem(
                item=item.get("item") or item.get("name") or "Unknown Item",
                quantity=int(item.get("quantity") or item.get("qty") or 1),
                price=float(item.get("price") or item.get("amount") or 0),
            )
        )

    return normalized_items


@app.get("/")
def read_root():
    return {"message": "AGORA AI Engine is running securely."}


@app.get("/transactions")
def get_transactions():
    return {"status": "success", "transactions": load_transactions()}


@app.post("/transactions")
def save_transaction(payload: SaveTransactionRequest):
    try:
        receipt_data = payload.receipt_data or {}
        normalized_items = payload.items or normalize_items_from_receipt_data(receipt_data)

        if not normalized_items:
            raise HTTPException(status_code=400, detail="Payload OCR harus berisi field items yang valid.")

        total_amount = payload.total_amount
        if total_amount is None:
            total_amount = float(sum(item.price * item.quantity for item in normalized_items))

        transaction_id = str(uuid.uuid4())
        saved_at = datetime.now(timezone.utc).isoformat()

        transaction = TransactionRecord(
            transaction_id=transaction_id,
            source=payload.source,
            receipt_filename=payload.receipt_filename,
            items=normalized_items,
            total_amount=total_amount,
            notes=payload.notes,
            merchant_name=payload.merchant_name or receipt_data.get("merchant_name"),
            transaction_date=payload.transaction_date or receipt_data.get("transaction_date"),
            payment_method=payload.payment_method or receipt_data.get("payment_method"),
            currency=payload.currency or receipt_data.get("currency") or "IDR",
            saved_at=saved_at,
        )

        transactions = load_transactions()
        transactions.append(transaction.model_dump())
        save_transactions(transactions)

        return {
            "status": "success",
            "message": "Transaction berhasil disimpan.",
            "transaction": transaction.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan transaksi: {str(exc)}")


@app.post("/extract-receipt")
async def extract_receipt(file: UploadFile = File(...)):
    # Lapisan keamanan dasar: pastikan API key tersedia
    if not NVIDIA_API_KEY:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY belum dikonfigurasi di .env")

    try:
        # 1. Membaca file gambar ke dalam buffer memori
        file_bytes = await file.read()
        
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
                            "text": "Anda adalah agen OCR AGORA untuk struk Indonesia. Ekstrak data dari gambar struk/nota ini dan kembalikan JSON murni yang valid. Schema wajib: {\"merchant_name\": string, \"transaction_date\": string|null, \"items\": [{\"item\": string, \"quantity\": integer, \"price\": number}], \"total_amount\": number, \"payment_method\": string|null, \"currency\": \"IDR\"}. Aturan: 1) gunakan bahasa yang umum dipakai di struk Indonesia, 2) item harus masuk ke array items, 3) quantity harus integer, 4) price harus angka numerik tanpa simbol mata uang, 5) total_amount harus angka numerik, 6) kalau quantity tidak tersedia, gunakan 1, 7) jangan tambahkan teks penjelasan apa pun sebelum atau sesudah JSON."
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
        response = requests.post(NVIDIA_API_URL, headers=headers, json=payload)
        
        # 5. Evaluasi dan Error Handling
        if response.status_code != 200:
            print(f"Error Response dari NVIDIA: {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Gagal mendapatkan respons valid dari NVIDIA NIM.")
            
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
        
    except Exception as e:
        print(f"Exception di AI Engine: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan internal server: {str(e)}")

