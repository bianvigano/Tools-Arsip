
Tool backup & Arsip dengan UI interaktif (TUI) & mode headless. 
Mendukung `zip/tar/tgz/7z`, 
enkripsi (ZIP AES‑256 / GPG), split otomatis, exclude, upload (`rclone`, `aws s3`, `lftp`, `scp`), 
serta sistem plugin notifikasi (Telegram/Email/custom).

Tujuan dari program ini untuk dipermudah dalam menggunakan `zip/tar/tgz/7z` dan lebih interaktif dan mudah digunakan

Catatan : ini masih menggunakan `zip/tar/tgz/7z` dari pihak lain jadi murni program ini supaya mudah saja :D

---

## 📌 Requirements

* Python 3.7+
* CLI tools: `zip`, `7z`, `tar`, `gzip`, `gpg`, `rclone`, `aws`, `lftp`, `scp` (sesuai opsi)

---

## 🚀 Fitur Utama
  
| ✅ Fitur                     | Deskripsi                                              |
|-----------------------------|--------------------------------------------------------|
| UI interaktif               | Navigasi file, exclude, preview                        |
| Mode headless               | Untuk cron atau otomatisasi script                     |
| Format arsip                | `zip`, `tar`, `tgz`, `7z`                              |
| Enkripsi                    | `ZIP AES-256`, `GPG symmetric (AES256)`                |
| Split file                  | Otomatis, misal per 200MB                              |
| Exclude file/pola           | Langsung (--exclude) atau via file                     |
| Upload                     | `rclone`, `AWS S3`, `FTP/SFTP`, `SCP`                 |
| Notifikasi plugin           | `Telegram`, `Email`, atau plugin eksternal            |
| Output opsional             | Checksum `.sha256`, summary `.json`                   |

---

## 🧪 Contoh Pemakaian

### Mode interaktif (UI TUI):

```bash
./backup_tool.py --start /data/projects
```

### Arsip + Split 200MB:

```bash
./backup_tool.py --no-ui --source /srv/data --dest /backups \
  --format tgz --split 200m --name my-backup
```

### Zip AES-256 via 7z (non-ZipCrypto):

```bash
./backup_tool.py --no-ui --source /srv/app --format zip \
  --zip-aes --password "MySecret123"
```

### TGZ + GPG encrypted:

```bash
./backup_tool.py --no-ui --source /srv/data --format tgz --gpg-encrypt
```

### Exclude file:

```bash
./backup_tool.py --exclude "*.log,*.tmp,.git/" --exclude-from exclude-list.txt
```

### Upload + hapus file lokal setelah upload:

```bash
./backup_tool.py --no-ui --source /srv/data --format tgz \
  --upload gdrive:Backups --upload-tool rclone --after-upload-rm
```

---

## ⚙️ Opsi CLI

| Opsi                           | Deskripsi                                                   |
| ------------------------------ | ----------------------------------------------------------- |
| `--start`                      | Direktori awal UI (mode interaktif)                         |
| `--source`                     | Path yang dibackup (bisa lebih dari satu)                   |
| `--dest`                       | Direktori output arsip                                      |
| `--format`                     | Format arsip: `zip`, `tar`, `tgz`, `7z`                     |
| `--name`                       | Nama file output (tanpa ekstensi)                           |
| `--zip-aes`                    | Buat ZIP AES-256 via `7z`                                   |
| `--zip-encrypt`                | ZIP dengan password (prompt interaktif; ZipCrypto)          |
| `--password`                   | Password non-interaktif (raw di argumen!)                   |
| `--gpg-encrypt`                | Enkripsi `.tar` / `.tgz` via GPG AES256                     |
| `--split`                      | Pecah arsip, contoh: `200m`, `1g`                           |
| `--keep-after-split`           | Simpan file utuh setelah split                              |
| `--rm-after-split`             | Hapus file utuh setelah split                               |
| `--exclude`                    | Pola pengecualian (bisa diulang)                            |
| `--exclude-from`               | File daftar pola exclude (1 pola per baris)                 |
| `--no-ui`                      | Mode headless (otomatisasi)                                 |
| `--upload`                     | Target upload, contoh: `gdrive:Backups`, `s3://bucket/path` |
| `--upload-tool`                | Pilih upload tool: `rclone`, `aws`, `lftp`, `scp`           |
| `--after-upload-rm`            | Hapus file lokal setelah upload sukses                      |
| `--upload-retry`               | Jumlah retry upload (default: 3)                            |
| `--notify`                     | Notifikasi: `telegram`, `email`, atau nama plugin           |
| `--notify-config`              | String ENV diteruskan ke plugin                             |
| `--plugins-dir`                | Direktori plugin tambahan (default: `./plugins.d`)          |
| `--summary` / `--no-summary`   | Aktif/nonaktif ringkasan `.summary.json`                    |
| `--checksum` / `--no-checksum` | Aktif/nonaktif SHA256 `.sha256`                             |
| `--summary-dir`                | Tempat simpan `.summary.json`                               |
| `--checksum-dir`               | Tempat simpan `.sha256`                                     |
| `--dry-run`                    | Simulasi saja (tidak ada perubahan nyata)                   |
| `--config`                     | File konfigurasi `key=value` untuk override argumen CLI     |

---

## 📬 ENV Plugin (Notifikasi)

Tool ini mendukung sistem notifikasi yang fleksibel menggunakan **plugin eksternal**, baik plugin built-in (`telegram`, `email`) maupun script custom (`.sh`, `.py`, atau executable lain).

Saat plugin dipanggil, tool akan mengirimkan informasi melalui **environment variables (ENV)**, sehingga plugin dapat membaca status backup secara langsung tanpa perlu menyentuh kode inti (`backup_tool.py`).

---

### 🎯 Tujuan

Fitur `--notify` dan `--notify-config` memungkinkan Anda menambahkan notifikasi atau aksi tambahan **tanpa mengubah logika utama backup**.

Plugin dapat digunakan untuk:

* Mengirim notifikasi status backup
* Upload ke sistem eksternal
* Logging ke sistem Anda sendiri
* Men-trigger webhook, dsb

---

### ⚙️ Cara Kerja

Saat Anda menjalankan:

```bash
./backup_tool.py --notify ./plugins.d/myhook.py --notify-config ./plugin-config.json
```

Maka:

1. File `plugin-config.json` akan dibaca dan dikonversi menjadi string.
2. Isi file tersebut akan dimasukkan ke **ENV** bernama `NOTIFY_CONFIG`.
3. Plugin akan dieksekusi dengan semua variabel ENV tersedia (status backup, path arsip, dsb).
4. Plugin cukup membaca ENV untuk menjalankan logika yang dibutuhkan.

---

### 📦 ENV yang Dikirim ke Plugin

Plugin akan menerima ENV berikut:

```bash
EVENT=on_success                # atau on_failure
STATUS=success                 # atau failure
SUMMARY_FILE=/path/to/*.summary.json
ARCHIVE_PATH=/path/to/output/archive.tgz
FILES=file1\nfile2\n...        # daftar file hasil backup (dipisah baris)
UPLOAD_TARGET=gdrive:Backups
LOG_FILE=/path/to/logfile.log
NOTIFY_CONFIG=...              # isi dari --notify-config (biasanya JSON)
OUTPUT_DIR=/backup/output/dir
BASE_NAME=backup-20250920-1730
TOTAL_SIZE=123.4 MB
```

---

### 📢 Contoh Penggunaan Notifikasi

#### 🔔 Kirim ke Telegram

```bash
./backup_tool.py --notify telegram
```

> Pastikan ENV `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` sudah tersedia.

#### 📧 Kirim via Email

```bash
./backup_tool.py --notify email
```

> ENV yang diperlukan: `EMAIL_TO`, `EMAIL_SUBJECT` (opsional)

#### 🔧 Jalankan Plugin Custom

```bash
./backup_tool.py --notify ./plugins.d/myscript.py
./backup_tool.py --notify myhook.sh --plugins-dir ./myplugins
```

> File dapat berupa `.py`, `.sh`, atau binary executable.
> Jika plugin adalah Python script yang tidak memiliki permission eksekusi, tool akan menjalankannya menggunakan Python interpreter secara otomatis.

#### 🔁 Beberapa Plugin Sekaligus

```bash
--notify telegram,email,./plugins.d/myhook.py
```

---

### 📂 Contoh `plugin-config.json`

```json
{
  "webhook_url": "https://example.com/webhook",
  "title": "Backup Harian",
  "send_if": "on_success",
  "extra_note": "Backup dari server utama"
}
```

File ini akan dimasukkan ke ENV `NOTIFY_CONFIG` sebagai satu string.

---

### 🐍 Contoh Plugin Python (`myhook.py`)

```python
#!/usr/bin/env python3
import os, json

conf_raw = os.environ.get("NOTIFY_CONFIG", "{}")
conf = json.loads(conf_raw)

print(f"📦 Backup: {os.environ.get('BASE_NAME')} - {os.environ.get('STATUS')}")
print(f"Webhook : {conf.get('webhook_url')}")
print(f"Note    : {conf.get('extra_note')}")
```

---

### 🐚 Contoh Plugin Bash (`myhook.sh`)

```bash
#!/bin/bash
echo "📢 Backup status: $STATUS"
echo "🔧 Config (raw JSON): $NOTIFY_CONFIG"

# Ekstrak webhook URL (jika jq tersedia)
if command -v jq > /dev/null; then
  webhook=$(echo "$NOTIFY_CONFIG" | jq -r '.webhook_url')
  echo "Webhook: $webhook"
fi
```

---

### 📝 Tips Penggunaan

* Plugin Anda tidak perlu tahu lokasi file config — cukup baca ENV `NOTIFY_CONFIG`.
* Isi `--notify-config` bisa berupa JSON, YAML (as string), atau format lain yang bisa diparse plugin Anda.
* Jika plugin perlu parsing YAML, Anda harus menangani sendiri di sisi plugin.

---

### 📁 Struktur Direktori Plugin yang Direkomendasikan

```
plugins.d/
├── telegram.py        # Telegram built-in plugin
├── email.sh           # Email plugin
├── myhook.py          # Plugin buatan sendiri
├── diskcheck.sh       # Plugin eksternal lain
```


---

## 🔒 Catatan Keamanan

* Hindari menggunakan `--password` di CLI (bisa bocor di `ps`, history shell, dsb).
* Gunakan opsi interaktif `--zip-encrypt` atau plugin GPG untuk keamanan lebih kuat.

---

## 📦 Output Tambahan

* File checksum SHA256: `<arsip>.sha256`
* Ringkasan backup: `*.summary.json`
  Berisi: waktu backup, ukuran, file output, dll.

---

## 🧩 Struktur Plugin

Contoh plugin Telegram/Email tersedia di `./plugins.d`
Bisa dalam bentuk `.sh`, `.py`, atau binary.
