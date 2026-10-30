# Stomake

**Stomake** adalah aplikasi desktop untuk membantu penulis mengelola dan menulis novel dalam satu tempat. Aplikasi ini menyediakan fitur pengelolaan proyek, penulisan bab, database karakter, Story Bible, World Bible, serta integrasi AI lokal untuk mendukung proses kreatif.

## ✨ Fitur Utama

- **Project Management** — Mengelola proyek novel dan bab cerita.
- **Character Database** — Menyimpan informasi dan detail karakter.
- **Story Bible** — Mengelola informasi penting mengenai alur dan elemen cerita.
- **World Bible** — Menyimpan informasi tentang dunia, lokasi, dan elemen pendukung cerita.
- **Custom Categories** — Membuat kategori khusus untuk Story Bible dan World Bible.
- **Custom Traits** — Menyesuaikan atribut karakter sesuai kebutuhan.
- **Rich Text Editor** — Menulis dan memformat teks cerita.
- **Local AI Integration** — Menggunakan AI lokal melalui Ollama.
- **Word Export** — Mengekspor tulisan ke dokumen Word.
- **SQLite Database** — Menyimpan data aplikasi secara lokal.

## 🖥️ Persyaratan Sistem

- Windows 10 atau Windows 11
- Python 3.10 atau lebih baru
- Git
- Ollama untuk menggunakan fitur AI lokal

## 📥 Instalasi

### 1. Clone Repository

Unduh source code Stomake dari GitHub:

```bash
git clone https://github.com/GendingLokananta/Stomake.git
cd Stomake
```

### 2. Buat Virtual Environment

Buat lingkungan Python terpisah untuk mengelola dependencies aplikasi:

```bash
python -m venv .venv
```

### 3. Aktifkan Virtual Environment

**Windows CMD:**

```bat
.venv\Scripts\activate
```

**Windows PowerShell:**

```powershell
.\.venv\Scripts\Activate.ps1
```

### 4. Instal Dependencies

Pastikan file `requirements.txt` tersedia di direktori utama proyek.

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Jalankan Aplikasi

Jalankan aplikasi menggunakan file utama `main.py`:

```bash
python main.py
```

## 🤖 Integrasi AI Lokal

Stomake mendukung penggunaan AI lokal melalui Ollama.

### Cara Menggunakan

1. Unduh dan instal Ollama dari situs resminya: https://ollama.com/
2. Pastikan Ollama berjalan di komputer.
3. Unduh model AI yang ingin digunakan.
4. Jalankan Stomake dan gunakan fitur AI yang tersedia.

Contoh perintah untuk mengunduh model:

```bash
ollama pull llama3.2:3b
```

Model yang digunakan dapat disesuaikan dengan konfigurasi aplikasi dan kemampuan perangkat.

**Catatan:** Ketersediaan fitur AI bergantung pada konfigurasi dan model yang didukung oleh aplikasi.

## 🚀 Menjalankan dengan File BAT

Untuk mempermudah proses menjalankan aplikasi di Windows, kamu dapat membuat file `run_stomake.bat` di direktori utama proyek.

Isi file:

```bat
@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment tidak ditemukan.
    echo Silakan buat .venv dan instal requirements terlebih dahulu.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py

pause
```

Setelah disimpan, klik dua kali file `run_stomake.bat` untuk menjalankan aplikasi.

## 💾 Penyimpanan Data

Stomake menggunakan SQLite sebagai sistem penyimpanan data lokal.

Database utama aplikasi berada di:

```text
data/Stomake.db
```

**Penting:** Selalu buat cadangan database sebelum memperbarui aplikasi, mengubah struktur database, atau melakukan migrasi data.

## 📁 Struktur Proyek

Gambaran umum struktur proyek:

```text
Stomake/
├── main.py
├── requirements.txt
├── README.md
├── run_stomake.bat
└── data/
    └── Stomake.db
```

Struktur di atas merupakan gambaran umum. File dan folder aktual dapat berbeda sesuai implementasi aplikasi.

## 🛠️ Troubleshooting

### Aplikasi Tidak Bisa Dijalankan

Pastikan Python sudah terinstal dan virtual environment telah diaktifkan.

Jika dependencies belum terpasang, jalankan:

```bash
pip install -r requirements.txt
```

Kemudian jalankan kembali:

```bash
python main.py
```

### Fitur AI Tidak Berfungsi

- Pastikan Ollama sudah terinstal.
- Pastikan layanan Ollama berjalan.
- Pastikan model AI yang dibutuhkan sudah diunduh.
- Periksa konfigurasi integrasi AI pada aplikasi.

### Database Bermasalah

- Pastikan folder `data` tersedia.
- Pastikan database dapat diakses oleh aplikasi.
- Buat cadangan database sebelum mencoba memperbaiki atau mengganti file database.

## 🔧 Pengembangan

Stomake dikembangkan menggunakan Python dengan antarmuka desktop, penyimpanan SQLite, dan dukungan integrasi AI lokal.

Pengembangan lebih lanjut dapat dilakukan dengan menambahkan fitur, menyempurnakan antarmuka, atau meningkatkan pengelolaan data cerita.
