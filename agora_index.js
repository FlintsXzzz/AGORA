const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const axios = require('axios');
const FormData = require('form-data');

// Path untuk menyimpan sesi autentikasi agar tidak perlu scan QR berulang kali
const SESSION_DIR = './.wwebjs_auth';

console.log('🔄 Menginisialisasi sistem AGORA WhatsApp Gateway...');

const client = new Client({
    // LocalAuth menyimpan sesi di folder lokal, sangat penting agar bot stabil saat direstart
    authStrategy: new LocalAuth({ dataPath: SESSION_DIR }),
    puppeteer: {
        // Flag wajib jika dijalankan di dalam Docker (mencegah error sandbox)
        args: [
            '--no-sandbox', 
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--single-process', // Berguna untuk menghemat memory
            '--disable-gpu'
        ],
        headless: true
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
    console.log('Menunggu pesan masuk...');
});

// Event: Mendengarkan pesan dari pengguna
client.on('message', async msg => {
    const sender = msg.from;
    
    // Fitur ping untuk mengecek responsivitas bot
    if (msg.body === '!ping') {
        console.log(`[${new Date().toLocaleTimeString()}] Menerima perintah !ping dari ${sender}`);
        msg.reply('pong! 🏓 Sistem AGORA berjalan dengan baik. Silakan kirimkan foto struk Anda.');
    }
    
    // Fitur: Menangani pesan berupa media (gambar struk)
    if (msg.hasMedia) {
        console.log(`\n[${new Date().toLocaleTimeString()}] Menerima pesan berisi media dari ${sender}`);
        
        try {
            // 1. Mengunduh media dari WhatsApp
            const media = await msg.downloadMedia();
            
            // Memastikan media yang dikirim adalah gambar
            if (media && media.mimetype.includes('image')) {
                msg.reply('⏳ Menerima gambar struk. Sedang mengekstrak data...');
                
                // 2. Mengubah base64 dari whatsapp-web.js menjadi buffer memori
                const buffer = Buffer.from(media.data, 'base64');
                
                // 3. Menyiapkan FormData untuk dikirim via HTTP POST (Multipart)
                const form = new FormData();
                form.append('file', buffer, {
                    filename: `receipt_${Date.now()}.jpg`,
                    contentType: media.mimetype
                });
                
                // 4. Meneruskan gambar ke AI Engine (FastAPI)
                // Catatan: Karena kita menggunakan docker-compose, kita panggil hostname 'ai-engine'
                console.log('➡️ Mengirim gambar ke AI Engine untuk diproses...');
                const aiResponse = await axios.post('http://ai-engine:8000/extract-receipt', form, {
                    headers: {
                        ...form.getHeaders()
                    }
                });
                
                // 5. Memberikan respons balik ke pengguna
                console.log('✅ AI Engine merespons:', aiResponse.data);
                msg.reply(`✅ Berhasil diproses AI Engine.\nFile terdeteksi: ${aiResponse.data.filename}\nStatus: ${aiResponse.data.status}`);
                
            } else {
                msg.reply('⚠️ Format tidak didukung. Harap kirimkan file berupa gambar/foto struk.');
            }
        } catch (error) {
            console.error('❌ Error saat memproses media:', error.message);
            msg.reply('❌ Terjadi kesalahan saat mengunduh atau meneruskan gambar.');
        }
    }
});

// Event: Disconnected (Penting untuk debugging jika bot tiba-tiba mati)
client.on('disconnected', (reason) => {
    console.log('❌ Bot terputus dari WhatsApp. Alasan:', reason);
});

// Memulai proses inisialisasi
client.initialize();
