# 🛡️ Backup & Upload Tool (Python)

Port Python dari skrip backup interaktif berbasis Bash.
Mendukung **backup otomatis, enkripsi, split, exclude, upload, dan notifikasi**, baik via UI maupun headless (cron).

---

## 🚀 Fitur Utama

✅ UI interaktif (navigasi file, exclude, preview)
✅ Mode headless (otomatisasi/cron)
✅ Format arsip: `zip`, `tar`, `tgz`, `7z`
✅ Enkripsi: `ZIP AES-256`, `GPG symmetric (AES256)`
✅ Split file otomatis (misal: per 200MB)
✅ Exclude file/pola (langsung atau dari file)
✅ Upload ke: `rclone`, `AWS S3`, `FTP/SFTP`, `SCP`
✅ Notifikasi via plugin: `Telegram`, `Email`, atau kustom
✅ Output opsional: SHA256 checksum & summary `.json`

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

Plugin akan menerima variabel lingkungan (ENV) berikut:

```
EVENT, STATUS, SUMMARY_FILE, ARCHIVE_PATH, FILES
UPLOAD_TARGET, LOG_FILE, NOTIFY_CONFIG, OUTPUT_DIR, BASE_NAME, TOTAL_SIZE
```

Contoh notifikasi:

* Telegram: `--notify telegram`
* Email: `--notify email`
* Plugin kustom: `--notify ./plugins.d/myhook.py`

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

## 📌 Requirements

* Python 3.7+
* CLI tools: `zip`, `7z`, `tar`, `gzip`, `gpg`, `rclone`, `aws`, `lftp`, `scp` (sesuai opsi)

---

## 🧩 Struktur Plugin

Contoh plugin Telegram/Email tersedia di `./plugins.d`
Bisa dalam bentuk `.sh`, `.py`, atau binary.

---

Kalau kamu ingin file ini langsung dikirim sebagai `README.md`, cukup bilang saja! Mau saya generate file-nya sekarang?
