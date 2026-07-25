const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const FormData = require('form-data');

const SESSION_DIR = process.env.WWEBJS_SESSION_DIR || path.resolve(process.cwd(), '.wwebjs_auth');
const AI_ENGINE_BASE_URL = process.env.AI_ENGINE_BASE_URL || 'http://ai-engine:8000';
const AI_ENGINE_URL = `${AI_ENGINE_BASE_URL}/extract-receipt`;
const SAVE_TRANSACTION_URL = `${AI_ENGINE_BASE_URL}/transactions`;

fs.mkdirSync(SESSION_DIR, { recursive: true });

function normalizeReceiptItems(payload) {
    if (Array.isArray(payload)) {
        return payload.map((item, index) => ({
            item: item.item || item.name || `item_${index + 1}`,
            quantity: Number(item.quantity || item.qty || 1),
            price: Number(item.price || item.amount || 0)
        }));
    }

    if (payload && typeof payload === 'object' && Array.isArray(payload.items)) {
        return payload.items.map((item, index) => ({
            item: item.item || item.name || `item_${index + 1}`,
            quantity: Number(item.quantity || item.qty || 1),
            price: Number(item.price || item.amount || 0)
        }));
    }

    return [];
}

function parseReceiptPayload(rawPayload) {
    if (!rawPayload) {
        return { items: [], total_amount: 0 };
    }

    if (typeof rawPayload === 'string') {
        const cleaned = rawPayload.replace(/```json|```/g, '').trim();

        try {
            const parsed = JSON.parse(cleaned);
            const items = normalizeReceiptItems(parsed);
            const totalAmount = Number(parsed.total_amount || parsed.totalAmount || 0);

            return {
                items,
                total_amount: totalAmount || items.reduce((sum, item) => sum + (item.price || 0), 0)
            };
        } catch (error) {
            return { items: [], total_amount: 0 };
        }
    }

    if (Array.isArray(rawPayload) || (rawPayload && typeof rawPayload === 'object')) {
        const items = normalizeReceiptItems(rawPayload);
        const totalAmount = Number(rawPayload.total_amount || rawPayload.totalAmount || 0);

        return {
            items,
            total_amount: totalAmount || items.reduce((sum, item) => sum + (item.price || 0), 0)
        };
    }

    return { items: [], total_amount: 0 };
}

console.log('🔄 Menginisialisasi sistem AGORA WhatsApp Gateway...');
console.log(`📁 Menyimpan sesi WhatsApp di: ${SESSION_DIR}`);

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: SESSION_DIR }),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--single-process',
            '--disable-gpu',
            '--disable-software-rasterizer'
        ],
        timeout: 60000
    }
});

// Event: Emit QR Code ke terminal (hanya jika belum ada sesi tersimpan)
client.on('qr', (qr) => {
    console.log('\n======================================================');
    console.log('📱 ACTION REQUIRED: SCAN QR CODE DI BAWAH INI');
    console.log('======================================================\n');
    qrcode.generate(qr, { small: true });
    console.log('\nPetunjuk: Buka WhatsApp > Linked Devices > Link a Device > Arahkan kamera ke layar ini.\n');
});

// Event: Menginformasikan saat proses autentikasi berhasil
client.on('authenticated', () => {
    console.log('✅ Autentikasi berhasil! Sesi tersimpan dengan aman.');
});

// Event: Menginformasikan jika autentikasi gagal (biasanya karena sesi corrupt)
client.on('auth_failure', msg => {
    console.error('❌ Gagal mengautentikasi bot:', msg);
});

// Event: Bot sudah menyala penuh dan siap digunakan
client.on('ready', () => {
    console.log('\n======================================================');
    console.log('🤖 AGORA BOT ONLINE & SIAP DIGUNAKAN!');
    console.log('======================================================\n');
    console.log(`🟢 Session aktif tersimpan di: ${SESSION_DIR}`);
    console.log('Menunggu pesan masuk...');
});

client.on('disconnected', (reason) => {
    console.warn('⚠️ Bot terputus dari WhatsApp. Alasan:', reason);

    if (reason && !String(reason).toLowerCase().includes('auth')) {
        console.log('🔄 Mencoba menghubungkan ulang bot dalam 5 detik...');
        setTimeout(() => client.initialize(), 5000);
    }
});

// Event: Mendengarkan pesan dari pengguna
client.on('message', async msg => {
    const sender = msg.from;
    const body = (msg.body || '').trim();

    // Fitur ping untuk mengecek responsivitas bot
    if (body === '!ping') {
        console.log(`[${new Date().toLocaleTimeString()}] Menerima perintah !ping dari ${sender}`);
        msg.reply('pong! 🏓 Sistem AGORA berjalan dengan baik. Silakan kirimkan foto struk Anda.');
        return;
    }

    // Fitur: Menangani pesan berupa media (gambar struk)
    if (msg.hasMedia) {
        console.log(`\n[${new Date().toLocaleTimeString()}] Menerima pesan berisi media dari ${sender}`);

        // Helper: kirim buffer ke AI Engine sebagai multipart/form-data
        async function sendBufferToAI(buffer, mimetype, filename) {
            const form = new FormData();
            form.append('file', buffer, { filename, contentType: mimetype });

            const resp = await axios.post(AI_ENGINE_URL, form, {
                headers: { ...form.getHeaders() },
                timeout: 120000
            });

            return resp.data;
        }

        // Helper: simpan transaksi ke service penyimpanan
        async function saveTransactionToStore(payload) {
            const resp = await axios.post(SAVE_TRANSACTION_URL, payload, { timeout: 120000 });
            return resp.data;
        }

        try {
            const media = await msg.downloadMedia();

            if (!media || !media.mimetype || !media.mimetype.startsWith('image/')) {
                msg.reply('⚠️ Format tidak didukung. Harap kirimkan file berupa gambar/foto struk.');
                return;
            }

            msg.reply('⏳ Menerima gambar struk. Sedang mengekstrak data...');

            const buffer = Buffer.from(media.data, 'base64');
            const filename = `receipt_${Date.now()}.jpg`;

            console.log('➡️ Mengirim gambar ke AI Engine untuk diproses...');
            const aiData = await sendBufferToAI(buffer, media.mimetype, filename);

            console.log('✅ AI Engine merespons:', aiData);

            const parsedReceipt = parseReceiptPayload(aiData.data);
            const saveTransactionPayload = {
                source: 'whatsapp',
                receipt_filename: aiData.filename || filename,
                items: parsedReceipt.items,
                total_amount: parsedReceipt.total_amount,
                notes: `Receipt processed from WhatsApp at ${new Date().toISOString()}`
            };

            const saveResp = await saveTransactionToStore(saveTransactionPayload);

            console.log('✅ Transaksi berhasil disimpan:', saveResp);
            const transactionId = saveResp?.transaction?.transaction_id || saveResp?.transaction_id || 'unknown';

            msg.reply(`✅ Berhasil diproses AI Engine.\nFile terdeteksi: ${aiData.filename || filename}\nStatus: ${aiData.status || 'ok'}\nTransaksi tersimpan dengan ID: ${transactionId}`);
        } catch (error) {
            console.error('❌ Error saat memproses media:', error && error.stack ? error.stack : error);

            // Jika error berkaitan dengan autentikasi wwebjs, coba inisialisasi ulang sekali
            const errMsg = (error && error.message) ? error.message.toLowerCase() : '';
            if (errMsg.includes('auth') || errMsg.includes('session')) {
                msg.reply('⚠️ Terjadi masalah autentikasi sesi. Mencoba memulai ulang sesi...');
                try {
                    client.destroy();
                } catch (e) {
                    // ignore
                }
                setTimeout(() => client.initialize(), 2000);
            } else {
                msg.reply('❌ Terjadi kesalahan saat mengunduh, meneruskan gambar, atau menyimpan transaksi. Silakan coba lagi.');
            }
        }
    }
});

// Memulai proses inisialisasi
client.initialize();
