#!/usr/bin/env python3
# plugins.d/post_email
import os, sys, json, smtplib
from email.mime.text import MIMEText

EVENT         = os.getenv("EVENT", "on_finish")
STATUS        = os.getenv("STATUS", "unknown")
SUMMARY_FILE  = os.getenv("SUMMARY_FILE", "")
ARCHIVE_PATH  = os.getenv("ARCHIVE_PATH", "")
OUTPUT_DIR    = os.getenv("OUTPUT_DIR", "")
BASE_NAME     = os.getenv("BASE_NAME", "")
UPLOAD_TARGET = os.getenv("UPLOAD_TARGET", "")
NOTIFY_CONFIG = os.getenv("NOTIFY_CONFIG", "")
DRY_RUN       = os.getenv("DRY_RUN", "0") == "1"

def log(msg): print(f"[post_email:{BASE_NAME}] {msg}", flush=True)

def load_cfg(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"config error: {e}")
        return {}

cfg = load_cfg(NOTIFY_CONFIG)
only_on = (cfg.get("email_only_on", "failure") or "failure").lower()  # failure|success|both

if only_on == "failure" and STATUS == "success":
    log("skip: email_only_on=failure dan status sukses")
    sys.exit(0)
if only_on == "success" and STATUS != "success":
    log("skip: email_only_on=success dan status gagal")
    sys.exit(0)

email_to   = cfg.get("email_to")
email_from = cfg.get("email_from", email_to or "backup@example.com")
subject_ok = cfg.get("email_subject_success", f"Backup {BASE_NAME} ✅")
subject_ng = cfg.get("email_subject_failure", f"Backup {BASE_NAME} ❌")
subject    = subject_ok if STATUS == "success" else subject_ng

smtp_host  = cfg.get("smtp_host")
smtp_port  = int(cfg.get("smtp_port", 587))
smtp_user  = cfg.get("smtp_user")
smtp_pass  = cfg.get("smtp_pass")

# ambil size dari summary (opsional)
size = ""
if SUMMARY_FILE and os.path.isfile(SUMMARY_FILE):
    try:
        import json
        with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
            size = json.load(f).get("size", "")
    except Exception:
        pass

body = (
    f"Event   : {EVENT}\n"
    f"Status  : {STATUS}\n"
    f"Archive : {ARCHIVE_PATH}\n"
    f"Output  : {OUTPUT_DIR}\n"
    f"Size    : {size or '-'}\n"
    f"Upload  : {UPLOAD_TARGET or '-'}\n"
)

if DRY_RUN:
    log("DRY-RUN: tidak mengirim email")
    sys.exit(0)

if not (email_to and smtp_host):
    log("skip: email_to/smtp_host kosong")
    sys.exit(0)

msg = MIMEText(body)
msg["Subject"] = subject
msg["From"]    = email_from
msg["To"]      = email_to

try:
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
        if int(cfg.get("smtp_starttls", 1)) == 1:
            server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg)
    log(f"✅ email terkirim ke {email_to}")
    sys.exit(0)
except Exception as e:
    log(f"❌ email gagal: {e}")
    sys.exit(1)
