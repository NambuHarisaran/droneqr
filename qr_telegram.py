"""
QR Code Scanner & Telegram Notifier
------------------------------------
Opens the webcam, detects QR codes in real-time, and sends
the decoded text to a Telegram chat via the Bot API.

Usage:
    1. Create a Telegram bot via @BotFather and copy the token.
    2. Get your chat ID (message @userinfobot or @RawDataBot on Telegram).
    3. Pass credentials via command-line args, .env file, or environment variables:
       python qr_telegram.py --token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"
       OR
       Create a .env file based on .env.example and run:
       python qr_telegram.py

Press 'q' to quit the camera window.
"""

import os
import sys
import time
import signal
import argparse
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import cv2
import requests
from pyzbar.pyzbar import decode, ZBarSymbol


# ── Configuration (hardcoded defaults) ───────────────────────────────────────
DEFAULT_BOT_TOKEN = "8742112415:AAEFk59yO8BOsyCCGSHPatU0PfgzmNGeyTc"
DEFAULT_CHAT_ID = "5334966139"


# ── Load .env if present (without requiring external libraries) ─────────────
def load_dotenv_file(filepath: Path):
    if not filepath.is_file():
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val


# Load .env from current directory or script directory
load_dotenv_file(Path(".env"))
load_dotenv_file(Path(__file__).parent / ".env")


# ── Telegram helper ─────────────────────────────────────────────────────────
def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    """Send *text* to the configured Telegram chat. Returns True on success."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            print(f"[+] Telegram message sent: {text}")
            return True
        else:
            print(f"[-] Telegram API error {resp.status_code}: {resp.text}")
            return False
    except requests.RequestException as exc:
        print(f"[-] Network error: {exc}")
        return False


# ── QR drawing helper ───────────────────────────────────────────────────────
def draw_qr_overlay(frame, decoded_obj):
    """Draw a bounding box and label around a decoded QR code."""
    points = decoded_obj.polygon
    if len(points) == 4:
        pts = [(p.x, p.y) for p in points]
        for i in range(4):
            cv2.line(frame, pts[i], pts[(i + 1) % 4], (0, 255, 0), 3)
    else:
        rect = decoded_obj.rect
        cv2.rectangle(
            frame,
            (rect.left, rect.top),
            (rect.left + rect.width, rect.top + rect.height),
            (0, 255, 0),
            3,
        )

    # Label
    text = decoded_obj.data.decode("utf-8", errors="replace")
    origin = (decoded_obj.rect.left, max(15, decoded_obj.rect.top - 10))
    cv2.putText(frame, text[:40], origin, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)


# ── Main loop ───────────────────────────────────────────────────────────────
# Global shutdown flag for graceful termination
_shutdown_requested = False


def _sig_handler(signum, frame):
    global _shutdown_requested
    print(f"\n[*] Received termination signal ({signum}). Exiting cleanly...")
    _shutdown_requested = True


signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)


# ── Main loop ───────────────────────────────────────────────────────────────
def run_scanner(
    token: str,
    chat_id: str,
    camera_source=0,
    cooldown: float = 10.0,
    headless: bool = False,
    fps: float = 15.0,
):
    global _shutdown_requested

    # Convert numeric camera source string to int if possible
    if isinstance(camera_source, str) and camera_source.isdigit():
        camera_source = int(camera_source)

    cap = cv2.VideoCapture(camera_source)
    if not cap.isOpened():
        print(f"[-] Cannot open camera source: {camera_source}")
        print("    Tip: Check if the camera device is connected (/dev/video0 on Linux).")
        sys.exit(1)

    # Lower default capture resolution for Raspberry Pi efficiency (640x480)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print(f"[*] Camera ({camera_source}) opened successfully.")
    if headless:
        print("[*] Running in HEADLESS mode (no GUI window, optimized for Raspberry Pi / server).")
        print("[*] Listening for QR codes... (Press Ctrl+C or stop container to quit)\n")
    else:
        print("[*] Scanning for QR codes... Press 'q' in the video window to quit.\n")

    sent_cache: dict[str, float] = {}  # {qr_data: last_sent_timestamp}
    frame_interval = 1.0 / max(1.0, fps)

    try:
        while not _shutdown_requested:
            start_time = time.time()
            ret, frame = cap.read()
            if not ret:
                print("[-] Failed to grab frame from camera. Retrying in 1s...")
                time.sleep(1.0)
                continue

            # Decode QR codes
            qr_codes = decode(frame, symbols=[ZBarSymbol.QRCODE])

            for obj in qr_codes:
                qr_text = obj.data.decode("utf-8", errors="replace")
                if not headless:
                    draw_qr_overlay(frame, obj)

                # Cooldown check
                now = time.time()
                if qr_text in sent_cache and (now - sent_cache[qr_text]) < cooldown:
                    continue

                print(f"[*] Decoded QR: {qr_text}")
                message = f"📷 <b>QR Code Detected</b>\n\n<code>{qr_text}</code>"
                if send_telegram_message(token, chat_id, message):
                    sent_cache[qr_text] = now

            if not headless:
                cv2.imshow("QR Scanner (Press 'q' to quit)", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("\n[*] Stopping scanner...")
                    break
            else:
                # Keep CPU usage low on Raspberry Pi
                elapsed = time.time() - start_time
                sleep_duration = max(0.01, frame_interval - elapsed)
                time.sleep(sleep_duration)

    finally:
        cap.release()
        if not headless:
            cv2.destroyAllWindows()
        print("[*] Camera released. Scanner shut down.")


# ── Entry point ──────────────────────────────────────────────────────────────
def main():
    # Detect headless environment (e.g. Linux server without X11 or explicitly configured)
    is_headless_env = os.getenv("HEADLESS", "").lower() in ("1", "true", "yes")
    if not is_headless_env and sys.platform != "win32" and "DISPLAY" not in os.environ:
        is_headless_env = True

    parser = argparse.ArgumentParser(description="Scan QR codes from camera and send to Telegram")
    parser.add_argument(
        "-c", "--camera",
        type=str,
        default=os.getenv("CAMERA_DEVICE", "0"),
        help="Camera index (e.g. 0) or device path (e.g. /dev/video0). Default: 0",
    )
    parser.add_argument(
        "-t", "--token",
        type=str,
        default=os.getenv("TELEGRAM_BOT_TOKEN", DEFAULT_BOT_TOKEN),
        help="Telegram Bot Token",
    )
    parser.add_argument(
        "-i", "--chat-id",
        type=str,
        default=os.getenv("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID),
        help="Telegram Chat ID",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=float(os.getenv("SEND_COOLDOWN", "10.0")),
        help="Cooldown in seconds between sending the same QR code (default: 10.0)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=float(os.getenv("SCAN_FPS", "15.0")),
        help="Target processing frames per second (default: 15.0, saves CPU on Pi)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=is_headless_env,
        help="Run without displaying a graphical window (default for Linux server / Docker)",
    )
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test message to Telegram without opening the camera",
    )

    args = parser.parse_args()

    token = args.token.strip()
    chat_id = args.chat_id.strip()

    if not token or token == "YOUR_BOT_TOKEN_HERE":
        print("[-] Error: Missing Telegram Bot Token.")
        print("    Pass via --token, set TELEGRAM_BOT_TOKEN in .env, or set environment variable.")
        sys.exit(1)

    if not chat_id or chat_id == "YOUR_CHAT_ID_HERE":
        print("[-] Error: Missing Telegram Chat ID.")
        print("    Pass via --chat-id, set TELEGRAM_CHAT_ID in .env, or set environment variable.")
        sys.exit(1)

    if args.test_telegram:
        print("[*] Sending test message to Telegram...")
        success = send_telegram_message(token, chat_id, "🤖 <b>QR Scanner Test Message</b>\nTelegram integration is working properly!")
        sys.exit(0 if success else 1)

    run_scanner(
        token,
        chat_id,
        camera_source=args.camera,
        cooldown=args.cooldown,
        headless=args.headless,
        fps=args.fps,
    )


if __name__ == "__main__":
    main()
