from fastapi import FastAPI, File, UploadFile, HTTPException
import os
import base64
import requests
from dotenv import load_dotenv

# Memuat variabel environment
load_dotenv()

app = FastAPI(title="AGORA AI Engine")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
# Endpoint standar NVIDIA NIM untuk model vision/multimodal
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

@app.get("/")
def read_root():
    return {"message": "AGORA AI Engine is running securely."}

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
                            "text": "Anda adalah agen ekstraksi data AGORA. Ekstrak seluruh teks dari gambar struk/nota ini. Format output secara terstruktur menjadi JSON murni yang berisi array of objects dengan key: 'item', 'quantity', dan 'price'. Jangan tambahkan penjelasan teks apa pun sebelum atau sesudah JSON."
                        },
                        {
                            "type": "image_url", 
                            "image_url": {"url": f"data:{file.content_type};base64,{base64_image}"}
                        }
                    ]
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.1 # Suhu ditekan mendekati 0 agar output sangat deterministik dan analitis
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
        
        # 6. Mengembalikan hasil ke Node.js Gateway
        return {
            "filename": file.filename, 
            "status": "success",
            "data": extracted_text
        }
        
    except Exception as e:
        print(f"Exception di AI Engine: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan internal server: {str(e)}")
