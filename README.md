# AGORA (Automated Goods & Operations Recording Agent) 🛒🤖

AGORA adalah inovasi sistem manajemen operasional cerdas yang memanfaatkan antarmuka WhatsApp dan Agentic AI untuk menyederhanakan tata kelola keuangan dan barang bagi UMKM di Indonesia. Proyek ini dikembangkan untuk **COMPFEST 18 - AI Innovation Challenge (AIC)**.

## 🏗️ Arsitektur Sistem (MVP)
Sistem ini menggunakan arsitektur *microservices* lokal yang diorkestrasi melalui `docker-compose`:
1. **WhatsApp Gateway (Node.js):** Bertugas menerima *input* foto struk dari pengguna dan memberikan respon interaktif tanpa perlu instalasi aplikasi tambahan.
2. **AI Engine (Python/FastAPI):** Bertindak sebagai otak pemrosesan (Core Inference), memanfaatkan model **NVIDIA Nemotron-OCR-v2** untuk ekstraksi data terstruktur.

## 🚀 Panduan Setup & Instalasi Lokal

### Prasyarat
Pastikan Anda telah menginstal:
- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- Aplikasi WhatsApp aktif di *smartphone* Anda untuk *scanning* QR Code.

### Langkah-Langkah Menjalankan Aplikasi
1. **Clone repositori ini:**
   ```bash
   git clone [https://github.com/](https://github.com/)[FlintsXzzz]/AGORA.git
   cd agora
