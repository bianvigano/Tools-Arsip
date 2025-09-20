#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backup & Upload Tool (Python port)
---------------------------------
Port of the user's interactive backup Bash script to Python.

Goals:
- Parity with headless mode and most interactive features
- Works on Linux/macOS
- Uses external CLIs when needed (zip/7z/tar/gpg/rclone/aws/lftp/scp)

Notes:
- Encryption:
  * ZIP (ZipCrypto): uses `zip` CLI with -e or -P
  * ZIP (AES-256): uses `7z` CLI (-tzip -mem=AES256)
  * 7z format (AES-256): uses `7z` CLI
  * tar/tgz optional GPG symmetric encryption (AES256) via `gpg`
- Exclude patterns are passed through to the used CLI as in the Bash version
- Splitting can be done with built-in Python chunking (default) or external `split` if available
- Upload supports: rclone, aws s3, lftp, scp
- Notification plugins: built-in Telegram & Email, plus executable hooks
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List, Tuple, Optional

# ================== Konfigurasi Default ==================
PAGE_SIZE = 10
START_DIR = os.getcwd()
DEST_DIR = str(Path.home())
ARCHIVE_FORMAT = "zip"          # zip|tar|tgz|7z
ZIP_AES = 0                     # 1 = gunakan 7z untuk buat ZIP AES-256 (-tzip -mem=AES256)
USE_GPG = 0                     # 1 = enkripsi GPG untuk tar/tgz output
SPLIT_SIZE = ""                 # contoh: 100m, kosong = tidak split
OUT_NAME = ""                   # contoh: my-backup
ZIP_ENCRYPT = 0                 # 1 = aktifkan -e (prompt password) untuk zip
ZIP_PASSWORD = ""               # jika diisi, gunakan zip -P atau 7z -p
KEEP_AFTER_SPLIT = 1
RM_AFTER_SPLIT = 0
EXCLUDES: List[str] = []
EXCLUDE_FILE = ""

# Headless & Upload Defaults
NO_UI = 0
SOURCES: List[str] = []
UPLOAD_TARGET = ""              # gdrive:Backups | s3://bucket/path | sftp://user@host:/dir | ftp://user@host:/dir
UPLOAD_TOOL = "auto"            # auto|rclone|aws|lftp|scp
AFTER_UPLOAD_RM = 0
UPLOAD_RETRY = 3

# Dry-run, Config, Notifikasi
DRY_RUN = 0
CONFIG_FILE = ""
PLUGINS_DIR = "./plugins.d"
NOTIFY_TARGETS: List[str] = []   # telegram,email,/path/plugin.sh
NOTIFY_CONFIG = ""
LOG_FILE = ""

# Lokasi output opsional utk summary & checksum (kosong = OUT_DIR)
SUMMARY_DIR = ""
CHECKSUM_DIR = ""

# Nonaktifkan output opsional (0/1)
MAKE_CHECKSUM = 0
MAKE_SUMMARY = 0

# Globals
SELECTED_PATHS: List[str] = []
OUT_DIR = ""
BASE = ""
SUMMARY_JSON = ""
FINAL_STATUS = "success"

# ================== Utils ==================
def ts_name() -> str:
    return dt.datetime.now().strftime("backup-%Y%m%d-%H%M%S")

def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def _parse_bool(v: str) -> int:
    if v is None:
        return 0
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "y", "t"):
        return 1
    if s in ("0", "false", "no", "off", "n", "f", ""):
        return 0
    try:
        return 1 if int(s) != 0 else 0
    except Exception:
        return 0

def log(msg: str) -> None:
    global LOG_FILE
    line = msg if msg.endswith("\n") else msg + "\n"
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    sys.stdout.write(line)
    sys.stdout.flush()

def run_or_echo(cmd: str) -> int:
    if DRY_RUN:
        log(f"DRY-RUN: {cmd}")
        return 0
    try:
        return subprocess.call(cmd, shell=True)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        log(f"❌ Exec error: {e}")
        return 1

_size_re = re.compile(r"^(\d+)([kKmMgG])$")

def parse_split_size(s: str) -> Optional[int]:
    """Return bytes from strings like '100m', '1g', '500k'."""
    if not s:
        return None
    m = _size_re.match(s.strip())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == 'k':
        return n * 1024
    if unit == 'm':
        return n * 1024 * 1024
    if unit == 'g':
        return n * 1024 * 1024 * 1024
    return None

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

# ================== Config Loader ==================
CFG_BOOL_KEYS = {
    'ZIP_AES', 'USE_GPG', 'ZIP_ENCRYPT', 'KEEP_AFTER_SPLIT', 'RM_AFTER_SPLIT', 'NO_UI',
    'AFTER_UPLOAD_RM', 'DRY_RUN', 'MAKE_CHECKSUM', 'MAKE_SUMMARY'
}
CFG_STR_KEYS = {
    'START_DIR','DEST_DIR','ARCHIVE_FORMAT','SPLIT_SIZE','OUT_NAME','ZIP_PASSWORD','EXCLUDE_FILE',
    'UPLOAD_TARGET','UPLOAD_TOOL','UPLOAD_RETRY','PLUGINS_DIR','NOTIFY_CONFIG','EMAIL_TO','EMAIL_SUBJECT',
    'TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID', 'SUMMARY_DIR', 'CHECKSUM_DIR'
}

def add_excludes_from_arg(raw: str) -> None:
    if not raw:
        return
    for part in [p.strip() for p in raw.split(',')]:
        if part:
            EXCLUDES.append(part)

def load_config_file(file: str) -> None:
    if not file or not Path(file).is_file():
        log(f"⚠️  Config tidak ditemukan: {file}")
        return
    global START_DIR, DEST_DIR, ARCHIVE_FORMAT, SPLIT_SIZE, OUT_NAME, ZIP_PASSWORD
    global EXCLUDE_FILE, UPLOAD_TARGET, UPLOAD_TOOL, UPLOAD_RETRY, PLUGINS_DIR
    global NOTIFY_CONFIG, DRY_RUN, ZIP_AES, USE_GPG, ZIP_ENCRYPT, KEEP_AFTER_SPLIT, RM_AFTER_SPLIT
    global NO_UI, AFTER_UPLOAD_RM, MAKE_CHECKSUM, MAKE_SUMMARY
    global NOTIFY_TARGETS, SOURCES, SUMMARY_DIR, CHECKSUM_DIR

    with open(file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k in CFG_STR_KEYS:
                globals()[k] = v
            elif k in CFG_BOOL_KEYS:
                globals()[k] = _parse_bool(v)
            elif k == 'EXCLUDES':
                add_excludes_from_arg(v)
            elif k == 'SOURCES':
                SOURCES.extend([p.strip() for p in v.split(',') if p.strip()])
            elif k == 'NOTIFY':
                NOTIFY_TARGETS.extend([p.strip() for p in v.split(',') if p.strip()])
            else:
                pass

# ================== Exclude helpers ==================
def collect_exclude_patterns() -> List[str]:
    patterns = []
    patterns.extend(EXCLUDES)
    if EXCLUDE_FILE and Path(EXCLUDE_FILE).is_file():
        with open(EXCLUDE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                patterns.append(s)
    return patterns

# ================== Archiving ==================
def _build_zip_exclude_args(patterns: List[str]) -> List[str]:
    if not patterns:
        return []
    return ['-x', *patterns]

def _build_tar_exclude_args(patterns: List[str]) -> List[str]:
    return [f"--exclude={p}" for p in patterns]

def shlex_quote(s: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"

def do_python_split(path: str, prefix: str, chunk_bytes: int) -> List[str]:
    parts = []
    idx = 0
    with open(path, 'rb') as src:
        while True:
            chunk = src.read(chunk_bytes)
            if not chunk:
                break
            out = f"{prefix}{idx:03d}"
            with open(out, 'wb') as dst:
                dst.write(chunk)
            parts.append(out)
            idx += 1
    return parts

def human_total_size(files: List[str]) -> str:
    total = 0
    for f in files:
        try:
            total += Path(f).stat().st_size
        except Exception:
            pass
    for unit in ['B','KB','MB','GB','TB']:
        if total < 1024.0 or unit == 'TB':
            return f"{total:.1f} {unit}"
        total /= 1024.0

def make_archive(paths: List[str]) -> Tuple[str, List[str]]:
    """Return (primary_output_path, files_to_upload[])"""
    if not paths:
        raise SystemExit("❌ Tidak ada item terpilih.")

    global OUT_DIR, BASE, LOG_FILE, SUMMARY_JSON

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    LOG_FILE = str(Path(OUT_DIR) / f"{BASE}.log")
    log(f"🗒️  Log: {LOG_FILE}")

    patterns = collect_exclude_patterns()
    if DRY_RUN:
        log("🧪 DRY-RUN MODE — tidak ada perubahan nyata.")
        log(f"• Format: {ARCHIVE_FORMAT}  • ZIP_AES: {ZIP_AES}  • GPG: {USE_GPG}")
        log(f"• Output dir: {OUT_DIR}  • Base: {BASE}")
        log(f"• Split: {SPLIT_SIZE or '-'}  • Upload: {UPLOAD_TARGET or '-'} ({UPLOAD_TOOL})")
        log(f"• Excludes: {len(patterns)} pola")
        for p in paths:
            try:
                size = subprocess.check_output(["du", "-sh", p]).split()[0].decode('utf-8')
            except Exception:
                size = "?"
            log(f"   - {os.path.basename(p)}  [{size}]")

    tmpfile = ""
    encrypted_file = ""

    # ====== Create archive ======
    if ARCHIVE_FORMAT == 'zip':
        if ZIP_AES == 1:
            if not command_exists('7z'):
                raise SystemExit("❌ butuh '7z' untuk ZIP AES-256")
            tmpfile = str(Path(OUT_DIR) / f"{BASE}.zip")
            seven_args = ["7z", "a", "-tzip", "-mem=AES256", tmpfile]
            if ZIP_PASSWORD:
                seven_args.extend([f"-p{ZIP_PASSWORD}", "-mhe=on"])
            elif ZIP_ENCRYPT == 1:
                pw = input("🔑 Password ZIP AES: ")
                seven_args.extend([f"-p{pw}", "-mhe=on"])
            for p in patterns:
                seven_args.append(f"-x!{p}")
            seven_args.extend(paths)
            cmd = " ".join(map(shlex_quote, seven_args))
            rc = run_or_echo(cmd)
            if rc != 0:
                raise SystemExit("❌ Gagal membuat ZIP AES")
        else:
            if not command_exists('zip'):
                raise SystemExit("❌ butuh 'zip'")
            tmpfile = str(Path(OUT_DIR) / f"{BASE}.zip")
            pass_args: List[str] = []
            if ZIP_PASSWORD:
                pass_args = ["-P", ZIP_PASSWORD]
            elif ZIP_ENCRYPT == 1:
                pass_args = ["-e"]
            ex_args = _build_zip_exclude_args(patterns)
            cmd_parts = ["zip", "-r", *pass_args, tmpfile, *paths, *ex_args]
            cmd = " ".join(map(shlex_quote, cmd_parts))
            if DRY_RUN:
                run_or_echo(cmd)
            else:
                rc = subprocess.call(cmd, shell=True)
                if rc != 0:
                    raise SystemExit("❌ Gagal membuat ZIP")
                try:
                    subprocess.check_call(["zip", "-T", tmpfile], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    log("🧪 Verifikasi zip OK.")
                except Exception:
                    log("❗ ZIP corrupt!")
    elif ARCHIVE_FORMAT in ('tgz', 'tar.gz'):
        if not command_exists('tar'):
            raise SystemExit("❌ butuh 'tar'")
        tmpfile = str(Path(OUT_DIR) / f"{BASE}.tar.gz")
        ex_args = _build_tar_exclude_args(patterns)
        compressor = 'pigz' if command_exists('pigz') else 'gzip'
        tar_cmd = " ".join(["tar", *ex_args, "-cf", "-", "--", *map(shlex_quote, paths)])
        cmd = f"{tar_cmd} | {compressor} > {shlex_quote(tmpfile)}"
        rc = run_or_echo(cmd)
        if rc != 0:
            raise SystemExit("❌ Gagal membuat TGZ")
        if not DRY_RUN and command_exists('gzip'):
            rc = subprocess.call(["gzip", "-t", tmpfile])
            if rc != 0:
                log("❗ Gzip corrupt!")
    elif ARCHIVE_FORMAT == 'tar':
        if not command_exists('tar'):
            raise SystemExit("❌ butuh 'tar'")
        tmpfile = str(Path(OUT_DIR) / f"{BASE}.tar")
        ex_args = _build_tar_exclude_args(patterns)
        cmd_parts = ["tar", *ex_args, "-cf", tmpfile, "--", *paths]
        cmd = " ".join(map(shlex_quote, cmd_parts))
        rc = run_or_echo(cmd)
        if rc != 0:
            raise SystemExit("❌ Gagal membuat TAR")
    elif ARCHIVE_FORMAT == '7z':
        if not command_exists('7z'):
            raise SystemExit("❌ butuh '7z'")
        tmpfile = str(Path(OUT_DIR) / f"{BASE}.7z")
        seven_args = ["7z", "a", "-t7z", tmpfile]
        if ZIP_PASSWORD:
            seven_args.extend([f"-p{ZIP_PASSWORD}", "-mhe=on"])
        elif ZIP_ENCRYPT == 1:
            pw = input("🔑 Password 7z: ")
            seven_args.extend([f"-p{pw}", "-mhe=on"])
        for p in patterns:
            seven_args.append(f"-x!{p}")
        seven_args.extend(paths)
        cmd = " ".join(map(shlex_quote, seven_args))
        rc = run_or_echo(cmd)
        if rc != 0:
            raise SystemExit("❌ Gagal membuat 7z")
    else:
        raise SystemExit(f"❌ format tidak didukung: {ARCHIVE_FORMAT}")

    # ====== GPG Encrypt for tar/tgz ======
    if USE_GPG == 1 and ARCHIVE_FORMAT in ('tgz','tar.gz','tar'):
        if not command_exists('gpg'):
            raise SystemExit("❌ butuh 'gpg' untuk --gpg-encrypt")
        encrypted_file = f"{tmpfile}.gpg"
        rc = run_or_echo(f"gpg --symmetric --cipher-algo AES256 --output {shlex_quote(encrypted_file)} {shlex_quote(tmpfile)}")
        if rc != 0:
            raise SystemExit("❌ Gagal enkripsi GPG")

    # ====== Split (optional) ======
    files_to_upload: List[str] = []
    primary_out = (locals().get('encrypted_file') or "") or tmpfile

    if SPLIT_SIZE:
        b = parse_split_size(SPLIT_SIZE)
        if not b:
            log("⚠️  Nilai --split tidak valid, melewati split")
            files_to_upload.append(primary_out)
        else:
            log(f"✂️  Split per {SPLIT_SIZE}...")
            prefix = f"{primary_out}.part."
            if DRY_RUN:
                run_or_echo(f"(split {SPLIT_SIZE} {shlex_quote(primary_out)} {shlex_quote(prefix)}NNN)")
                files_to_upload.append(primary_out)
            else:
                parts = do_python_split(primary_out, prefix, b)
                if KEEP_AFTER_SPLIT:
                    files_to_upload.extend(parts); files_to_upload.append(primary_out)
                    log("✅ Split sukses. Arsip utuh tetap disimpan.")
                elif RM_AFTER_SPLIT:
                    files_to_upload.extend(parts)
                    try:
                        os.remove(primary_out); log("🧹 Arsip utuh dihapus setelah split.")
                    except Exception:
                        pass
                else:
                    files_to_upload.extend(parts); files_to_upload.append(primary_out)
                log(f"📦 Output parts: {prefix}000, {prefix}001, ...")
    else:
        log(f"✅ Arsip siap: 📦 {primary_out}")
        files_to_upload.append(primary_out)

    # ====== Checksum ======
    if MAKE_CHECKSUM:
        if not DRY_RUN:
            for f in files_to_upload:
                try:
                    digest = sha256_file(Path(f))
                    chk_dir = CHECKSUM_DIR or OUT_DIR
                    Path(chk_dir).mkdir(parents=True, exist_ok=True)
                    chk_path = str(Path(chk_dir) / f"{Path(f).name}.sha256")
                    with open(chk_path, 'w', encoding='utf-8') as out:
                        out.write(f"{digest}  {Path(f).name}\n")
                    log(f"🔎 Membuat SHA256: {chk_path}")
                except Exception as e:
                    log(f"ℹ️  Lewati checksum: {e}")
        else:
            for f in files_to_upload:
                chk_dir = CHECKSUM_DIR or OUT_DIR
                chk_path = str(Path(chk_dir) / f"{Path(f).name}.sha256")
                log(f"DRY-RUN: sha256('{f}') > '{chk_path}'")

    # ====== Summary JSON ======
    SUMMARY_JSON = ""
    if MAKE_SUMMARY:
        sum_dir = SUMMARY_DIR or OUT_DIR
        Path(sum_dir).mkdir(parents=True, exist_ok=True)
        SUMMARY_JSON = str(Path(sum_dir) / f"{BASE}.summary.json")
        # (fix curly brace if typo occurs)
        if SUMMARY_JSON.endswith("}.json}"):
            SUMMARY_JSON = SUMMARY_JSON[:-1]
        size_str = "(estimasi)" if DRY_RUN else human_total_size(files_to_upload)
        summary = {
            "timestamp": dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "output": OUT_DIR,
            "archive": primary_out,
            "size": size_str,
            "files": files_to_upload,
        }
        with open(SUMMARY_JSON, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False)
        log(f"📝 Ringkasan: {SUMMARY_JSON}")

    return primary_out, files_to_upload

# ================== Upload ==================
def do_upload_one(file: str) -> int:
    target = UPLOAD_TARGET
    tool = UPLOAD_TOOL or "auto"
    tries = int(UPLOAD_RETRY or 3)

    if not target:
        return 0

    if tool == 'auto':
        if command_exists('rclone'):
            tool = 'rclone'
        elif target.startswith('s3://') and command_exists('aws'):
            tool = 'aws'
        elif command_exists('lftp'):
            tool = 'lftp'
        elif target.startswith('sftp://'):
            tool = 'scp'
        else:
            tool = 'rclone'

    log(f"☁️  Upload menggunakan: {tool} → {target}")

    attempt = 1
    delay = 2
    while attempt <= tries:
        log(f"   • Attempt {attempt}/{tries} ...")
        if tool == 'rclone':
            rc = run_or_echo(f"rclone copy {shlex_quote(file)} {shlex_quote(target)} --progress")
            if rc == 0 and not DRY_RUN:
                try:
                    subprocess.call(["rclone", "check", file, target, "--size-only"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    log("✅ Verifikasi rclone (size-only) selesai.")
                except Exception:
                    pass
        elif tool == 'aws':
            rc = run_or_echo(f"aws s3 cp {shlex_quote(file)} {shlex_quote(target)}")
        elif tool == 'lftp':
            rc = run_or_echo(f"lftp -c \"open '{target}'; put -O . '{file}'; bye\"")
        elif tool == 'scp':
            url = target[len('sftp://'):]
            rc = run_or_echo(f"scp {shlex_quote(file)} {shlex_quote(url)}")
        else:
            log(f"❌ UPLOAD_TOOL tidak didukung: {tool}")
            return 1

        if rc == 0:
            log(f"✅ Upload sukses: {file} → {target}")
            if AFTER_UPLOAD_RM:
                run_or_echo(f"rm -f -- {shlex_quote(file)}")
                log(f"🧹 Hapus lokal: {file}")
            return 0
        else:
            log(f"❌ Upload gagal ({tool}).")
            attempt += 1
            try:
                import time
                time.sleep(delay)
            except KeyboardInterrupt:
                raise
            delay *= 2

    log(f"❌ Upload gagal setelah {tries} percobaan.")
    return 1

# ================== Notifications / Plugins ==================
def notify_telegram(status: str, base: str, archive_path: str) -> None:
    bot = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not bot or not chat_id:
        log("ℹ️  Telegram ENV tidak lengkap.")
        return
    text = f"*{base}*\nStatus: {status}\nArsip: {archive_path}"
    if not command_exists('curl'):
        log("ℹ️  curl tidak ada, skip telegram")
        return
    cmd = (
        f"curl -s -X POST https://api.telegram.org/bot{shlex_quote(bot)}/sendMessage "
        f"-d chat_id={shlex_quote(chat_id)} -d parse_mode=Markdown -d text={shlex_quote(text)} > /dev/null"
    )
    run_or_echo(cmd)

def notify_email(status: str, base: str, archive_path: str, target: str) -> None:
    email_to = os.environ.get('EMAIL_TO')
    subject = os.environ.get('EMAIL_SUBJECT', f"Backup {base}: {status}")
    if not email_to:
        log("ℹ️  EMAIL_TO tidak diset, skip email")
        return
    body = f"Status: {status}\nArsip: {archive_path}\nTarget: {target}"
    if command_exists('mail'):
        run_or_echo(f"printf %b {shlex_quote(body)} | mail -s {shlex_quote(subject)} {shlex_quote(email_to)}")
    elif command_exists('mailx'):
        run_or_echo(f"printf %b {shlex_quote(body)} | mailx -s {shlex_quote(subject)} {shlex_quote(email_to)}")
    else:
        log("ℹ️  mail/mailx tidak ditemukan, skip email")

def _resolve_plugin(tgt: str, plugins_dir: str):
    """
    Kembalikan tuple (cmd_list, resolved_path) untuk dieksekusi,
    atau (None, None) jika tidak ketemu.

    - Mencoba:
      - path absolut / relative langsung
      - <plugins_dir>/<tgt>
      - varian dengan ekstensi: '', '.py', '.sh'
    - Jika file .py ada tapi tidak executable, fallback: [sys.executable, path]
    """
    exts = ["", ".py", ".sh"]
    candidates = []
    if os.path.isabs(tgt) or "/" in tgt:
        for ext in exts:
            candidates.append(tgt if ext == "" else tgt + ext)
    else:
        for ext in exts:
            candidates.append(os.path.join(plugins_dir, tgt if ext == "" else tgt + ext))
    for p in candidates:
        if os.path.isfile(p):
            if os.access(p, os.X_OK):
                return ([p], p)
            if p.endswith(".py"):
                return ([sys.executable, p], p)
    return (None, None)

def run_plugins(event: str, final_status: str, primary_out: str, files_to_upload: List[str]) -> None:

    try:
        total_size_str = "(estimasi)" if DRY_RUN else human_total_size(files_to_upload)
    except Exception:
        total_size_str = ""

    env = os.environ.copy()
    env.update({
        'EVENT': event,
        'SUMMARY_FILE': SUMMARY_JSON,
        'ARCHIVE_PATH': primary_out,
        'FILES': "\n".join(files_to_upload),
        'OUTPUT_DIR': OUT_DIR,
        'BASE_NAME': BASE,
        'STATUS': final_status,
        'LOG_FILE': LOG_FILE,
        'NOTIFY_CONFIG': NOTIFY_CONFIG,
        'UPLOAD_TARGET': UPLOAD_TARGET,
        'DRY_RUN': str(int(DRY_RUN)),
        'TOTAL_SIZE': total_size_str,  # <—— tambah ini
    })

    for tgt in NOTIFY_TARGETS:
        tgt = tgt.strip()
        if tgt == 'telegram':
            notify_telegram(final_status, BASE, primary_out)
        elif tgt == 'email':
            notify_email(final_status, BASE, primary_out, UPLOAD_TARGET)
        else:
            cmd, resolved = _resolve_plugin(tgt, PLUGINS_DIR)
            if cmd:
                if DRY_RUN:
                    log(f"DRY-RUN: plugin {resolved} (EVENT={event}) CMD={cmd}")
                else:
                    try:
                        subprocess.call(cmd, env=env)
                    except Exception as e:
                        log(f"ℹ️  Plugin error: {e}")
            else:
                log(f"ℹ️  Plugin tidak executable atau tidak ditemukan: {tgt} (cari di {PLUGINS_DIR} .py/.sh)")

# ================== UI ==================
try:
    import termios, tty
    _HAS_TERMIOS = True
except Exception:
    _HAS_TERMIOS = False

def _read_key() -> str:
    """Read a single keypress, including arrow sequences."""
    if os.name == 'nt':
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ('\r', '\n'):
            return 'ENTER'
        if ch in ('\x08',):
            return 'BACKSPACE'
        if ch in ('\xe0', '\x00'):
            code = msvcrt.getwch()
            return {'H': 'UP', 'P': 'DOWN', 'M': 'RIGHT', 'K': 'LEFT'}.get(code, '')
        return ch
    else:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch in ('\r', '\n'):
                return 'ENTER'
            if ch == '\x7f':
                return 'BACKSPACE'
            if ch == '\x1b':
                seq = sys.stdin.read(2)
                return {'[A': 'UP', '[B': 'DOWN', '[C': 'RIGHT', '[D': 'LEFT'}.get(seq, '')
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

def preview_excludes() -> str:
    lines = ["🔎 Pratinjau pola exclude aktif:"]
    if EXCLUDES:
        lines.append("  • Dari --exclude (CLI):")
        for p in EXCLUDES:
            lines.append(f"     - {p}")
    if EXCLUDE_FILE:
        if Path(EXCLUDE_FILE).is_file():
            lines.append(f"  • Dari --exclude-from file: {EXCLUDE_FILE}")
            try:
                with open(EXCLUDE_FILE, 'r', encoding='utf-8') as f:
                    shown = 0
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith('#'):
                            continue
                        lines.append(f"     - {s}")
                        shown += 1
                        if shown >= 50:
                            lines.append("     ...")
                            break
            except Exception:
                lines.append("  • (gagal membaca file)")
        else:
            lines.append(f"  • File exclude disetel namun tidak ditemukan: {EXCLUDE_FILE}")
    if len(lines) == 1:
        lines.append("  (tidak ada pola exclude aktif)")
    return "".join(lines)

def choose_exclude_ui() -> None:
    while True:
        os.system('clear')
        print("🧹 Exclude Manager")
        print("----------------------------------")
        print(f"File exclude aktif : {EXCLUDE_FILE or '(none)'}")
        print()
        print(preview_excludes())
        print()
        print("Aksi:")
        print("  1) Masukkan path file exclude manual")
        print("  2) Buat file exclude baru (kosong) lalu edit")
        print("  3) Kosongkan file exclude (nonaktifkan --exclude-from)")
        print("  b) Kembali")
        act = input("Pilih: ").strip()
        if act == '1':
            p = input("Masukkan path file exclude: ").strip()
            if Path(p).is_file():
                globals()['EXCLUDE_FILE'] = p
                print(f"✅ Dipilih: {EXCLUDE_FILE}")
            else:
                print(f"❌ File tidak ditemukan: {p}")
            input("Kembali...")
        elif act == '2':
            newname = input("Nama file baru (default: exclude-list.txt): ").strip() or 'exclude-list.txt'
            target = str(Path.cwd() / newname)
            if Path(target).exists():
                print(f"⚠️  File sudah ada: {target}")
            else:
                with open(target, 'w', encoding='utf-8') as f:
                    f.write(textwrap.dedent('''
                    # Contoh pola exclude (hapus baris ini bila tidak perlu)
                    # */node_modules/*
                    # *.log
                    # .git/
                    '''))
                print(f"✅ Dibuat: {target}")
            globals()['EXCLUDE_FILE'] = target
            editor = os.environ.get('EDITOR') or ('nano' if command_exists('nano') else 'vi' if command_exists('vi') else '')
            if editor:
                os.system(f"{editor} {shlex_quote(target)}")
            else:
                print("❌ Tidak ada editor (set $EDITOR atau instal nano/vi)")
            input("Kembali...")
        elif act == '3':
            globals()['EXCLUDE_FILE'] = ''
            print("✅ File exclude dinonaktifkan.")
            input("Kembali...")
        elif act.lower() == 'b':
            return
        else:
            print("❌ Pilihan tidak dikenal.")
            input("Kembali...")

def stat_mtime(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
        return dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    except Exception:
        return "-"

def print_selected():
    if not SELECTED_PATHS:
        print("∅ Belum ada pilihan.")
    else:
        print("✅ Terpilih:")
        for s in SELECTED_PATHS:
            print(f" - {s}")

def toggle_selected(p: str) -> None:
    if p in SELECTED_PATHS:
        SELECTED_PATHS[:] = [x for x in SELECTED_PATHS if x != p]
    else:
        SELECTED_PATHS.append(p)

def clear_selected():
    SELECTED_PATHS.clear()

def apply_sources_if_any():
    if not SELECTED_PATHS and SOURCES:
        for s in SOURCES:
            if Path(s).exists():
                SELECTED_PATHS.append(s)
            else:
                log(f"⚠️  --source tidak ditemukan: {s}")

def pilih_file_ui(target_dir: str):
    page = 1
    cursor_index = 0
    filter_regex = None
    expanded_dirs = set()

    def list_visual():
        entries = []
        try:
            base_items = sorted([str(Path(target_dir) / name) for name in os.listdir(target_dir)])
        except Exception:
            base_items = []
        def add_items(paths):
            for p in paths:
                name = os.path.basename(p)
                if filter_regex and not re.search(filter_regex, name):
                    continue
                entries.append(p)
        add_items(base_items)
        for d in list(expanded_dirs):
            if Path(d).is_dir():
                try:
                    subs = sorted([str(Path(d) / name) for name in os.listdir(d)])
                except Exception:
                    subs = []
                add_items(subs)
        return entries

    while True:
        os.system('clear')
        try:
            du = subprocess.check_output(["du", "-sh", target_dir]).split()[0].decode('utf-8')
        except Exception:
            du = "?"
        print(f"📂 Direktori: {target_dir} ({du})")
        if filter_regex:
            print(f"🔍 Filter: '{filter_regex}'")

        visual_list = list_visual()
        total = len(visual_list)
        if total == 0:
            print("❌ Kosong")
            input("Kembali...")
            return

        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(1, min(page, total_pages))
        start = (page - 1) * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        cursor_index = max(0, min(cursor_index, max(0, end - start - 1)))

        print(f"=== Isi: {target_dir} (page {page}/{total_pages}) ===")
        for i in range(start, end):
            idx = i - start
            p = visual_list[i]
            name = os.path.basename(p)
            try:
                size = subprocess.check_output(["du", "-sh", p]).split()[0].decode('utf-8')
            except Exception:
                size = "0"
            mdate = stat_mtime(Path(p))
            icon = "📁" if Path(p).is_dir() else ("📦" if re.search(r"\.(zip|tar|gz|tgz|tar\.gz|7z)$", p) else "📄")
            if p in SELECTED_PATHS:
                prefix = "\033[1;32m+\033[0m"; style = "\033[30;42m"
            else:
                prefix = "\033[1;31m-\033[0m"; style = "\033[0m"
            arrow = " ⬅️" if idx == cursor_index else ""
            print(f"{i+1:2d}. {prefix} {style}{icon} {name} [{size} | {mdate}]{arrow} \033[0m")

        def color_key(k):
            return f"\033[1;36m{k}\033[0m"

        print("\n📜 Navigasi:\n"
              f" ↑↓ Navigasi ←→ Halaman [{color_key('Enter')}] Pilih [{color_key('C')}] Expand [{color_key('/')}] Cari\n"
              f" [{color_key('p')}] Pilihan [{color_key('z')}] Arsip [{color_key('E')}] Exclude [{color_key('U')}] Clear "
              f" [{color_key('q')}] Keluar")
        key = _read_key()
        if key == 'UP':
            if cursor_index > 0:
                cursor_index -= 1
            else:
                if page > 1:
                    page -= 1
                    start = (page - 1) * PAGE_SIZE
                    end = min(start + PAGE_SIZE, total)
                    cursor_index = max(0, end - start - 1)
        elif key == 'DOWN':
            if cursor_index < (end - start - 1):
                cursor_index += 1
            else:
                if page < total_pages:
                    page += 1; cursor_index = 0
        elif key == 'LEFT':
            if page > 1:
                page -= 1; cursor_index = 0
        elif key == 'RIGHT':
            if page < total_pages:
                page += 1; cursor_index = 0
        elif key == 'ENTER':
            index = start + cursor_index
            if 0 <= index < total:
                toggle_selected(visual_list[index])
        elif key.lower() == 'c':
            index = start + cursor_index
            if 0 <= index < total:
                d = visual_list[index]
                if Path(d).is_dir():
                    if d in expanded_dirs:
                        expanded_dirs.remove(d)
                    else:
                        expanded_dirs.add(d)
        elif key == '/':
            filter_regex = input("🔍 Filter (regex; kosong=reset): ").strip() or None
            page = 1; cursor_index = 0
        elif key.lower() == 'p':
            print(); print_selected(); print(); input("Kembali...")
        elif key.lower() == 'z':
            headless_make_archive()
        elif key.lower() == 'e':
            choose_exclude_ui()
        elif key.lower() == 'u':
            clear_selected()
        elif key.lower() == 'q':
            sys.exit(0)
        else:
            if key.isdigit():
                n = int(key)
                target = start + (n - 1)
                if start <= target < end:
                    cursor_index = n - 1

# ================== Headless Runner ==================
def headless_make_archive():
    global OUT_DIR, BASE, FINAL_STATUS

    apply_sources_if_any()
    if not SELECTED_PATHS:
        if NO_UI:
            raise SystemExit("❌ Tidak ada item terpilih.")
        else:
            print("❌ Tidak ada item terpilih."); input("Kembali..."); return

    if NO_UI:
        OUT_DIR = DEST_DIR or str(Path.home())
        BASE = OUT_NAME or ts_name()
    else:
        print("📁 Simpan arsip di mana?")
        print(f"   1. Gunakan direktori sekarang ({os.getcwd()})")
        print(f"   2. Gunakan direktori default ({DEST_DIR or str(Path.home())})")
        print("   3. Masukkan path kustom")
        dchoice = (input("🔢 Pilih opsi [1/2/3] (default: 2): ").strip() or '2')
        if dchoice == '1':
            OUT_DIR = os.getcwd()
        elif dchoice == '3':
            custom = input("📂 Masukkan path tujuan: ").strip()
            OUT_DIR = custom or (DEST_DIR or str(Path.home()))
        else:
            OUT_DIR = DEST_DIR or str(Path.home())
        Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
        iname = input("📦 Masukkan nama arsip (tanpa ekstensi). Kosong = auto: ").strip()
        BASE = iname or (OUT_NAME or ts_name())

    primary, files_to_upload = make_archive(SELECTED_PATHS)

    FINAL_STATUS = "success"

    if UPLOAD_TARGET:
        for f in files_to_upload:
            if Path(f).exists() or DRY_RUN:
                rc = do_upload_one(f)
                if rc != 0:
                    FINAL_STATUS = "failure"

    if FINAL_STATUS == 'success':
        run_plugins('on_success', FINAL_STATUS, primary, files_to_upload)
    else:
        run_plugins('on_failure', FINAL_STATUS, primary, files_to_upload)
    # run_plugins('on_finish', FINAL_STATUS, primary, files_to_upload)

    if not NO_UI:
        input("Selesai. Kembali...")

# ================== Argparse ==================
def build_parser() -> argparse.ArgumentParser:
    class _Formatter(argparse.ArgumentDefaultsHelpFormatter,
                     argparse.RawDescriptionHelpFormatter):
        pass

    EPILOG = r"""
ENV bawaan untuk plugin (di-set saat plugin dipanggil):
  EVENT, STATUS, SUMMARY_FILE, ARCHIVE_PATH, FILES (daftar dipisah baris),
  UPLOAD_TARGET, LOG_FILE, NOTIFY_CONFIG, OUTPUT_DIR, BASE_NAME, TOTAL_SIZE

Contoh:
  # UI interaktif, mulai dari /data/projects
  %(prog)s --start /data/projects

  # Headless (tanpa UI), arsip TGZ, split 200 MB, nama custom
  %(prog)s --no-ui --source /srv/data --dest /backups --format tgz --split 200m --name proj-archive

  # ZIP AES-256 via 7z (lebih aman dari ZipCrypto)
  %(prog)s --no-ui --source /srv/app --dest /backups --format zip --zip-aes --password "Rahasia123"

  # TGZ + GPG symmetric (AES256)
  %(prog)s --no-ui --source /srv/data --dest /backups --format tgz --gpg-encrypt

  # Exclude pola (ulang argumen atau daftar koma)
  %(prog)s --exclude "*/node_modules/*" --exclude "*.log,.git/*"

  # Exclude dari file (satu pola per baris; dukung wildcard * ?)
  # contoh exclude-list.txt:
  #   *.log
  #   .tmp/
  #   */node_modules/*
  #   .git/
  #   .cache/
  %(prog)s --exclude-from ./exclude-list.txt

  # Upload ke rclone remote dan hapus lokal setelah sukses
  %(prog)s --no-ui --source /srv/data --dest /backups --format tgz \
           --upload gdrive:Backups --upload-tool rclone --after-upload-rm \
           --notify telegram,email

Catatan keamanan:
  • --password menaruh password di argumen proses (bisa terlihat di 'ps' atau history).
    Gunakan --zip-encrypt/interactive prompt bila memungkinkan.
"""

    p = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]),
        description="Interactive/Headless Backup & Upload Tool (Python)",
        formatter_class=_Formatter,
        epilog=EPILOG
    )

    # === Grup: Arsip & Enkripsi ===
    g1 = p.add_argument_group("Arsip & Enkripsi")
    g1.add_argument('--format', dest='ARCHIVE_FORMAT',
                    choices=['zip','tar','tgz','7z','tar.gz'],
                    help='Format arsip output')
    g1.add_argument('--name', dest='OUT_NAME', help='Nama file (tanpa ekstensi)')
    g1.add_argument('--zip-aes', dest='ZIP_AES', action='store_true',
                    help='Buat ZIP AES-256 via 7z (lebih aman dari ZipCrypto)')
    g1.add_argument('--zip-encrypt', dest='ZIP_ENCRYPT', action='store_true',
                    help='ZIP interaktif (prompt password) memakai ZipCrypto')
    g1.add_argument('--password', dest='ZIP_PASSWORD',
                    help='Password non-interaktif untuk ZIP/7z (hati-hati ekspos)')  # noqa
    g1.add_argument('--gpg-encrypt', dest='USE_GPG', action='store_true',
                    help='Enkripsi GPG (AES256) untuk tar/tgz → output .gpg')

    # === Grup: Split & Exclude ===
    g2 = p.add_argument_group("Split & Exclude")
    g2.add_argument('--split', dest='SPLIT_SIZE',
                    help="Pecah file hasil per ukuran, contoh: 200m, 1g")
    g2.add_argument('--keep-after-split', dest='KEEP_AFTER_SPLIT', action='store_true',
                    help='Setelah split, simpan juga file utuh')
    g2.add_argument('--rm-after-split', dest='RM_AFTER_SPLIT', action='store_true',
                    help='Setelah split, hapus file utuh')
    g2.add_argument('--exclude', dest='EXCLUDES', action='append',
                    help='Pola pengecualian; bisa diulang atau pakai koma')
    g2.add_argument('--exclude-from', dest='EXCLUDE_FILE',
                    help='File daftar pola exclude (satu pola per baris)')

    # === Grup: Upload ===
    g3 = p.add_argument_group("Upload")
    g3.add_argument('--upload', dest='UPLOAD_TARGET',
                    help='Target upload: gdrive:Backups | s3://bucket/path | sftp://user@host:/dir | ftp://user@host:/dir')
    g3.add_argument('--upload-tool', dest='UPLOAD_TOOL',
                    choices=['auto','rclone','aws','lftp','scp'],
                    help='Pilih tool upload (auto mendeteksi terbaik)')
    g3.add_argument('--after-upload-rm', dest='AFTER_UPLOAD_RM', action='store_true',
                    help='Hapus file lokal setelah upload sukses')
    g3.add_argument('--upload-retry', dest='UPLOAD_RETRY',
                    help='Jumlah retry upload')

    # === Grup: Mode & Konfigurasi ===
    g4 = p.add_argument_group("Mode & Konfigurasi")
    g4.add_argument('-s','--start', dest='START_DIR',
                    help='Direktori awal UI pemilihan (untuk mode interaktif)')
    g4.add_argument('--dest', dest='DEST_DIR',
                    help='Direktori output arsip')
    g4.add_argument('--no-ui', dest='NO_UI', action='store_true',
                    help='Mode headless (tanpa UI) — gunakan bersama --source')
    g4.add_argument('--source', dest='SOURCES', action='append',
                    help='Path sumber backup; dapat diulang')
    g4.add_argument('--config', dest='CONFIG_FILE',
                    help='File konfigurasi key=value (override CLI)')
    g4.add_argument('--dry-run', dest='DRY_RUN', action='store_true',
                    help='Simulasi: echo perintah tanpa membuat/mengupload')

    # === Grup: Notifikasi & Plugin ===
    g5 = p.add_argument_group("Notifikasi & Plugin")
    g5.add_argument('--notify', dest='NOTIFY_TARGETS', action='append',
                    help='telegram,email atau nama plugin; bisa koma/ulang argumen')
    g5.add_argument('--notify-config', dest='NOTIFY_CONFIG',
                    help='String konfigurasi diteruskan ke plugin via ENV NOTIFY_CONFIG')
    g5.add_argument('--plugins-dir', dest='PLUGINS_DIR',
                    help='Direktori plugin eksternal (default: ./plugins.d)')

    # === Grup: Output Tambahan ===
    g6 = p.add_argument_group("Output Tambahan (ringkasan & checksum)")
    g6.add_argument('--summary-dir', dest='SUMMARY_DIR',
                    help='Direktori untuk file ringkasan .summary.json')
    g6.add_argument('--checksum-dir', dest='CHECKSUM_DIR',
                    help='Direktori untuk file checksum .sha256')
    # aktif/nonaktif (biar konsisten: ada ON dan OFF)
    g6.add_argument('--summary', dest='MAKE_SUMMARY', action='store_true',
                    help='Aktifkan pembuatan ringkasan .summary.json')
    g6.add_argument('--no-summary', dest='MAKE_SUMMARY', action='store_false',
                    help='Nonaktifkan ringkasan .summary.json')
    g6.add_argument('--checksum', dest='MAKE_CHECKSUM', action='store_true',
                    help='Aktifkan pembuatan file .sha256')
    g6.add_argument('--no-checksum', dest='MAKE_CHECKSUM', action='store_false',
                    help='Nonaktifkan file .sha256')
    # default MAKE_* agar terlihat di help:
    p.set_defaults(MAKE_SUMMARY=0, MAKE_CHECKSUM=0)

    return p

def apply_args(args: argparse.Namespace) -> None:
    global START_DIR, DEST_DIR, ARCHIVE_FORMAT, ZIP_AES, USE_GPG, SPLIT_SIZE, OUT_NAME
    global ZIP_ENCRYPT, ZIP_PASSWORD, KEEP_AFTER_SPLIT, RM_AFTER_SPLIT, EXCLUDE_FILE
    global NO_UI, SOURCES, UPLOAD_TARGET, UPLOAD_TOOL, AFTER_UPLOAD_RM, UPLOAD_RETRY
    global DRY_RUN, CONFIG_FILE, PLUGINS_DIR, NOTIFY_TARGETS, NOTIFY_CONFIG
    global SUMMARY_DIR, CHECKSUM_DIR, MAKE_CHECKSUM, MAKE_SUMMARY

    if args.CONFIG_FILE:
        globals()['CONFIG_FILE'] = args.CONFIG_FILE
        load_config_file(args.CONFIG_FILE)

    if args.START_DIR: START_DIR = args.START_DIR
    if args.DEST_DIR: DEST_DIR = args.DEST_DIR
    if args.ARCHIVE_FORMAT: ARCHIVE_FORMAT = 'tgz' if args.ARCHIVE_FORMAT == 'tar.gz' else args.ARCHIVE_FORMAT
    if args.ZIP_AES: ZIP_AES = 1
    if args.USE_GPG: USE_GPG = 1
    if args.SPLIT_SIZE: SPLIT_SIZE = args.SPLIT_SIZE
    if args.OUT_NAME: OUT_NAME = args.OUT_NAME
    if args.ZIP_ENCRYPT: ZIP_ENCRYPT = 1
    if args.ZIP_PASSWORD: ZIP_PASSWORD = args.ZIP_PASSWORD
    if args.KEEP_AFTER_SPLIT: KEEP_AFTER_SPLIT = 1
    if args.RM_AFTER_SPLIT: RM_AFTER_SPLIT = 1
    if args.EXCLUDE_FILE: globals()['EXCLUDE_FILE'] = args.EXCLUDE_FILE

    if args.NO_UI: globals()['NO_UI'] = 1
    if args.SOURCES:
        for s in args.SOURCES:
            if s:
                SOURCES.append(s)
    if args.UPLOAD_TARGET: globals()['UPLOAD_TARGET'] = args.UPLOAD_TARGET
    if args.UPLOAD_TOOL: globals()['UPLOAD_TOOL'] = args.UPLOAD_TOOL
    if args.AFTER_UPLOAD_RM: globals()['AFTER_UPLOAD_RM'] = 1
    if args.UPLOAD_RETRY: globals()['UPLOAD_RETRY'] = args.UPLOAD_RETRY

    if args.DRY_RUN: globals()['DRY_RUN'] = 1
    if args.PLUGINS_DIR: globals()['PLUGINS_DIR'] = args.PLUGINS_DIR
    if args.NOTIFY_CONFIG: globals()['NOTIFY_CONFIG'] = args.NOTIFY_CONFIG
    if args.NOTIFY_TARGETS:
        for n in args.NOTIFY_TARGETS:
            if n:
                NOTIFY_TARGETS.extend([p.strip() for p in n.split(',') if p.strip()])

    if args.EXCLUDES:
        for raw in args.EXCLUDES:
            add_excludes_from_arg(raw)

    if getattr(args, 'SUMMARY_DIR', None): SUMMARY_DIR = args.SUMMARY_DIR
    if getattr(args, 'CHECKSUM_DIR', None): CHECKSUM_DIR = args.CHECKSUM_DIR
    if args.MAKE_CHECKSUM is False: MAKE_CHECKSUM = 0
    if args.MAKE_SUMMARY  is False: MAKE_SUMMARY  = 0

    if KEEP_AFTER_SPLIT and RM_AFTER_SPLIT:
        globals()['RM_AFTER_SPLIT'] = 0

# ================== Main ==================
def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.CONFIG_FILE:
        load_config_file(args.CONFIG_FILE)

    apply_args(args)

    if not Path(START_DIR).is_dir():
        print(f"❌ START_DIR tidak valid: {START_DIR}")
        sys.exit(1)

    if NO_UI:
        globals()['KEEP_AFTER_SPLIT'] = KEEP_AFTER_SPLIT or 1
        headless_make_archive()
        return

    pilih_file_ui(START_DIR)

if __name__ == '__main__':
    main()
