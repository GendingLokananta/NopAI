# NopAI

Aplikasi desktop untuk membantu menulis novel dengan Python, PySide6, SQLite, dan Ollama. NopAI mendukung pengelolaan novel, bab, karakter, lore/worldbuilding, bantuan AI lokal, serta ekspor naskah ke Word (`.docx`).

## Fitur

- Mengelola beberapa proyek novel.
- Menulis dan mengatur bab.
- Menyimpan data karakter dan lore/worldbuilding.
- Bantuan penulisan menggunakan AI lokal melalui Ollama.
- Mengekspor novel beserta bab, karakter, dan lore ke dokumen Word.
- Penyimpanan lokal menggunakan SQLite.

## Persyaratan

- Windows 10/11 (panduan ini menggunakan Windows Command Prompt/PowerShell).
- Python 3.10 atau lebih baru.
- Git untuk meng-clone repository.
- Ollama untuk menggunakan fitur AI.

## 1. Unduh project

Pastikan Git sudah terpasang, lalu jalankan:

```powershell
git clone https://github.com/GendingLokananta/NopAI.git
cd NopAI
```

Kalau tidak ingin menggunakan Git, buka repository GitHub lalu pilih **Code → Download ZIP**, ekstrak ZIP, kemudian buka terminal di folder project tersebut.

## 2. Buat virtual environment

Virtual environment (`venv`) memisahkan paket Python NopAI dari paket Python project lain di komputer. Jalankan dari folder NopAI:

```powershell
py -m venv .venv
```

Aktifkan virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Jika menggunakan Command Prompt (`cmd.exe`), gunakan:

```cmd
.venv\Scripts\activate.bat
```

Jika PowerShell menolak aktivasi karena kebijakan skrip, kamu tetap bisa memasang paket dan menjalankan aplikasi dengan interpreter virtual environment secara langsung, seperti pada langkah berikutnya. Tidak perlu mengubah kebijakan keamanan Windows hanya untuk menjalankan NopAI.

## 3. Pasang dependency

Dengan virtual environment aktif, jalankan:

```powershell
python -m pip install --upgrade pip
python -m pip install PySide6 requests python-docx
```

Paket yang digunakan:

- `PySide6` — antarmuka desktop.
- `requests` — komunikasi dengan Ollama.
- `python-docx` — ekspor dokumen Word.

Modul `sqlite3` sudah termasuk dalam instalasi standar Python, jadi tidak perlu dipasang terpisah.

## 4. Pasang dan siapkan Ollama (untuk fitur AI)

1. Unduh dan pasang Ollama dari situs resminya: https://ollama.com/download
2. Pastikan Ollama berjalan.
3. Buka terminal, lalu unduh model yang dipakai NopAI:

   ```powershell
   ollama pull llama3.2:3b
   ```

NopAI menghubungi Ollama di `http://localhost:11434`. Jika Ollama tidak berjalan atau model belum diunduh, aplikasi masih dapat digunakan untuk menulis dan mengelola data, tetapi fitur AI tidak akan merespons.

## 5. Jalankan NopAI

Pastikan terminal berada di folder project. Jika virtual environment sudah aktif:

```powershell
python main.py
```

Atau tanpa mengaktifkan virtual environment:

```powershell
.\.venv\Scripts\python.exe main.py
```

## 6. Buka dengan klik dua kali (Windows)

Jika file `Buka_NopAI.bat` tersedia di repository, simpan file tersebut di folder yang sama dengan `main.py` dan `.venv`. Setelah setup selesai, klik dua kali `Buka_NopAI.bat` untuk membuka aplikasi.

## Data dan privasi

Database lokal dibuat otomatis di `data/nopai.db` saat aplikasi dijalankan. Database tersebut menyimpan proyek dan isi novel di komputer pengguna. **Jangan commit atau mengunggah database yang berisi tulisan pribadi ke repository publik.** Pastikan `data/nopai.db` sudah tercantum di `.gitignore` sebelum menjalankan `git add .`.

Virtual environment (`.venv`) juga tidak perlu diunggah ke GitHub. Setiap pengguna membuat `.venv` sendiri mengikuti panduan di atas.

## Troubleshooting

### `py` atau `python` tidak dikenali

Pasang Python dari https://www.python.org/downloads/ lalu pastikan Python Launcher/Python tersedia di PATH. Tutup dan buka kembali terminal setelah instalasi.

### Modul seperti `PySide6` atau `docx` tidak ditemukan

Pastikan dependency dipasang menggunakan Python dari virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install PySide6 requests python-docx
```

### AI tidak bisa terhubung

- Pastikan Ollama sudah terpasang dan berjalan.
- Jalankan `ollama pull llama3.2:3b`.
- Coba `ollama list` untuk memastikan model tersedia.

### Ekspor Word gagal

Pasang ulang dependency ekspor:

```powershell
.\.venv\Scripts\python.exe -m pip install python-docx
```

## Teknologi

- Python
- PySide6 / Qt
- SQLite
- Ollama (`llama3.2:3b`)
- python-docx
