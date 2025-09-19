#!/usr/bin/env python3
# plugins.d/post-webhook
# Kirim webhook selesai backup (Discord embed / Slack blocks / generic JSON) tanpa dependency eksternal.

import os, sys, json, time, urllib.request, urllib.error

# ===== ENV dari backup_tool.py =====
EVENT         = os.getenv("EVENT", "on_finish")
STATUS        = os.getenv("STATUS", "unknown")
SUMMARY_FILE  = os.getenv("SUMMARY_FILE", "")
ARCHIVE_PATH  = os.getenv("ARCHIVE_PATH", "")
OUTPUT_DIR    = os.getenv("OUTPUT_DIR", "")
BASE_NAME     = os.getenv("BASE_NAME", "")
UPLOAD_TARGET = os.getenv("UPLOAD_TARGET", "")
NOTIFY_CONFIG = os.getenv("NOTIFY_CONFIG", "")
DRY_RUN       = os.getenv("DRY_RUN", "0") == "1"
FILES_ENV     = os.getenv("FILES", "")
TOTAL_SIZE    = os.getenv("TOTAL_SIZE", "")  # dikirim dari backup_tool.py (human_total_size)

def log(msg: str) -> None:
    print(f"[post-webhook:{BASE_NAME}] {msg}", flush=True)

def load_cfg(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"config error: {e}")
        return {}

cfg = load_cfg(NOTIFY_CONFIG)

# ===== Konfigurasi utama =====
webhook_url   = (cfg.get("webhook_url") or "").strip()
webhook_type  = (cfg.get("webhook_type", "generic") or "generic").lower()  # generic | discord | slack
token         = (cfg.get("webhook_token") or "").strip()                    # JANGAN dipakai untuk Discord
headers_extra = cfg.get("webhook_headers") if isinstance(cfg.get("webhook_headers"), dict) else {}
timeout_s     = int(cfg.get("webhook_timeout", 10))
retries       = int(cfg.get("webhook_retries", 3))
username      = cfg.get("discord_username", "BackupBot")
thread_id     = (cfg.get("thread_id") or "").strip()                        # opsional (Discord threads)

# ===== Tentukan size (prioritas: TOTAL_SIZE -> summary.json -> hitung dari FILES) =====
size = (TOTAL_SIZE or "").strip()

if not size and SUMMARY_FILE and os.path.isfile(SUMMARY_FILE):
    try:
        with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
            size = (json.load(f).get("size") or "").strip()
    except Exception:
        pass

if not size and FILES_ENV:
    # fallback: hitung ukuran total dari daftar file jika ada
    def _human(n: float) -> str:
        for u in ["B","KB","MB","GB","TB"]:
            if n < 1024 or u == "TB":
                return f"{n:.1f} {u}"
            n /= 1024.0
    total = 0
    for line in FILES_ENV.splitlines():
        p = line.strip()
        if not p:
            continue
        try:
            total += os.path.getsize(p)
        except Exception:
            pass
    if total > 0:
        size = _human(float(total))

if not size:
    size = "-"

# ===== Builder payload =====
def build_payload() -> dict:
    if webhook_type == "discord":
        # Discord: gunakan embeds
        color = 3066993 if STATUS == "success" else 15158332
        return {
            "username": username,
            "embeds": [{
                "title": f"📦 Backup {BASE_NAME}",
                "color": color,
                "fields": [
                    {"name": "Status", "value": STATUS, "inline": True},
                    {"name": "Size", "value": size, "inline": True},
                    {"name": "Event", "value": EVENT, "inline": True},
                    {"name": "Upload Target", "value": UPLOAD_TARGET or "-", "inline": False},
                    {"name": "Archive", "value": ARCHIVE_PATH or "-", "inline": False},
                ]
            }]
        }

    if webhook_type == "slack":
        # Slack: gunakan blocks
        color = "#2ecc71" if STATUS == "success" else "#e74c3c"
        return {
            "text": f"Backup {BASE_NAME} {STATUS}",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"📦 Backup {BASE_NAME}" }},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Status:*\n{STATUS}"},
                    {"type": "mrkdwn", "text": f"*Size:*\n{size}"},
                    {"type": "mrkdwn", "text": f"*Event:*\n{EVENT}"},
                    {"type": "mrkdwn", "text": f"*Target:*\n{UPLOAD_TARGET or '-'}"},
                ]},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"`{ARCHIVE_PATH or '-'}`"}]}
            ],
            "attachments": [{"color": color}]
        }

    # Generic JSON
    return {
        "event":  EVENT,
        "status": STATUS,
        "archive": ARCHIVE_PATH,
        "size":    size,
        "target":  UPLOAD_TARGET or "-",
        "name":    BASE_NAME,
    }

# ===== HTTP POST JSON (stdlib) =====
def http_post_json(url: str, data_dict: dict, hdrs: dict, timeout: int) -> bytes:
    data = json.dumps(data_dict, ensure_ascii=False).encode("utf-8")
    # tambahkan User-Agent agar jelas
    headers = {"Content-Type": "application/json", "User-Agent": "backup-tool/1.0"}
    headers.update(hdrs or {})
    req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read() or b""

def send_webhook() -> bool:
    if not webhook_url:
        log("skip: webhook_url kosong"); return True
    if DRY_RUN:
        log("DRY-RUN: tidak mengirim webhook"); return True

    # Discord: tambahkan ?wait=true (agar dapat body response), dan thread_id bila di-set
    url = webhook_url
    if webhook_type == "discord":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}wait=true"
        if thread_id:
            url = f"{url}&thread_id={thread_id}"

    payload = build_payload()

    # Header dasar
    headers = {}
    # Bearer token hanya dipakai utk webhook_type generic
    if token and webhook_type == "generic":
        headers["Authorization"] = f"Bearer {token}"
    # Custom header opsional dari config
    for k, v in (headers_extra or {}).items():
        headers[str(k)] = str(v)

    for attempt in range(1, retries+1):
        try:
            body = http_post_json(url, payload, headers, timeout_s)
            # kalau sukses, Discord kembalikan JSON jika wait=true
            log(f"✅ webhook terkirim (attempt {attempt})")
            return True
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", "replace")
            except Exception:
                err_body = ""
            log(f"HTTP {e.code} on attempt {attempt}: {e.reason} | body={err_body}")
        except urllib.error.URLError as e:
            log(f"URL error on attempt {attempt}: {e.reason}")
        except Exception as e:
            log(f"error on attempt {attempt}: {e}")
        time.sleep(min(5, attempt*2))
    log("❌ Gagal kirim webhook setelah retry.")
    return False

if __name__ == "__main__":
    ok = send_webhook()
    sys.exit(0 if ok else 1)
