# NopAI

NopAI adalah aplikasi desktop untuk membantu proses penulisan novel menggunakan Python, PySide6, SQLite, dan Ollama. Aplikasi ini mendukung pengelolaan proyek novel, bab, karakter, lore/worldbuilding, bantuan penulisan berbasis AI lokal, serta ekspor naskah ke Microsoft Word.

## Fitur

- Mengelola beberapa proyek novel.
- Menulis dan mengatur bab.
- Menyimpan informasi karakter dan lore/worldbuilding.
- Mendapatkan bantuan penulisan menggunakan AI lokal.
- Mengekspor novel, bab, karakter, dan lore ke dokumen Word (`.docx`).
- Menyimpan data secara lokal menggunakan SQLite.

## Persyaratan

- Windows 10/11.
- Python 3.10 atau lebih baru.
- Git (opsional, jika ingin meng-clone repository).
- Ollama (untuk menggunakan fitur AI).

## 1. Unduh Project

Clone repository menggunakan Git:

```powershell
git clone https://github.com/GendingLokananta/NopAI.git
cd NopAI
```

Atau unduh ZIP melalui halaman repository GitHub, kemudian ekstrak ke folder yang diinginkan.

## 2. Buat Virtual Environment

Jalankan perintah berikut di folder project:

```powershell
py -m venv .venv
```

Virtual environment berfungsi untuk memisahkan dependency NopAI dari project Python lainnya.

## 3. Pasang Dependency

Aktifkan virtual environment menggunakan PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Jika menggunakan Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

Kemudian pasang dependency:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Jika aktivasi virtual environment gagal, kamu bisa langsung menggunakan interpreter di dalam `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 4. Siapkan Ollama

Ollama diperlukan untuk menggunakan fitur AI lokal.

1. Unduh Ollama dari [situs resminya](https://ollama.com/download).
2. Pastikan Ollama sudah terpasang dan berjalan.
3. Unduh model yang digunakan NopAI:

```powershell
ollama pull llama3.2:3b
```

NopAI menggunakan endpoint lokal `http://localhost:11434`. Tanpa Ollama atau model yang diperlukan, fitur AI tidak akan berfungsi, tetapi fitur penulisan dan pengelolaan data tetap dapat digunakan.

## 5. Jalankan NopAI

Dengan virtual environment aktif, jalankan:

```powershell
python main.py
```

Atau jalankan langsung menggunakan interpreter virtual environment:

```powershell
.\.venv\Scripts\python.exe main.py
```

## 6. Menjalankan dengan File BAT

Jika file `NopAI.bat` tersedia, kamu bisa menjalankannya dengan klik dua kali setelah dependency selesai dipasang.

Pastikan file BAT tersebut sesuai dengan struktur folder dan konfigurasi Python di komputer yang digunakan.

## Data dan Privasi

NopAI menyimpan data proyek novel secara lokal menggunakan SQLite. Database dibuat di `data/nopai.db` saat aplikasi dijalankan.

Database, naskah novel pribadi, log, dan file lokal yang bersifat pribadi sebaiknya tidak diunggah ke repository publik.

Virtual environment `.venv` juga tidak perlu diunggah ke GitHub. Setiap pengguna dapat membuatnya sendiri mengikuti panduan instalasi di atas.

## Troubleshooting

### Python tidak dikenali

Pasang Python dari [python.org](https://www.python.org/downloads/), lalu pastikan Python tersedia melalui PATH. Buka kembali terminal setelah instalasi.

### Dependency tidak ditemukan

Pasang ulang dependency menggunakan interpreter virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### AI tidak dapat terhubung

- Pastikan Ollama sudah terpasang dan berjalan.
- Jalankan `ollama pull llama3.2:3b`.
- Jalankan `ollama list` untuk memastikan model tersedia.

### Ekspor Word gagal

Pasang dependency `python-docx`:

```powershell
.\.venv\Scripts\python.exe -m pip install python-docx
```

## Teknologi

- Python
- PySide6 / Qt
- SQLite
- Ollama (`llama3.2:3b`)
- Requests
- python-docx
