#!/usr/bin/env python3
"""
Multi-page Monitor for Canadian Visa
Simple version: notifie si le contenu change
"""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests

PAGES = {
    "Jenza": {
        "url": "https://jenza.com/experiences/working-holidays/work-canada-ro/",
        "state_file": "state_jenza.txt",
    },
}

PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN")
CHECK_TYPE = os.environ.get("CHECK_TYPE", "change")


def fetch_page(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


def is_maintenance_page(text_lower):
    """Détecte si c'est une page d'erreur/maintenance."""
    markers = ["bad gateway", "cloudflare", "maintenance", "502", "503", "504", "temporarily unavailable"]
    return any(m in text_lower for m in markers)


def extract_stable_content(html):
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.replace("\u00a0", " ")
    return text


def get_content_hash(text):
    return hashlib.md5(text.encode()).hexdigest()


def find_differences(old_text, new_text):
    old_words = set(old_text.lower().split())
    new_words = set(new_text.lower().split())
    added = new_words - old_words
    removed = old_words - new_words
    diff_parts = []
    if added:
        diff_parts.append(f"Nouveaux mots: {', '.join(list(added)[:10])}")
    if removed:
        diff_parts.append(f"Mots retirés: {', '.join(list(removed)[:10])}")
    if not diff_parts:
        return "Changement de structure détecté"
    return "\n".join(diff_parts)


def send_notification(title, message, priority=1, url=None):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        print("Pushover credentials not configured")
        return
    try:
        data = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message[:1000],
            "priority": priority,
        }
        if url:
            data["url"] = url
            data["url_title"] = "Ouvrir le site"
        if priority == 2:
            data["retry"] = 60
            data["expire"] = 3600
        response = requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
        response.raise_for_status()
        print(f"Notification sent: {title}")
    except Exception as e:
        print(f"Failed to send notification: {e}")


def load_previous_state(state_file):
    path = Path(state_file)
    if path.exists():
        try:
            content = path.read_text().strip()
            if not content:
                return None
            data = json.loads(content)
            if isinstance(data, str):
                return {"hash": data, "text": "", "error": False}
            return data
        except Exception:
            return None
    return None


def save_state(state_file, content_hash, text, error=False):
    data = {"hash": content_hash, "text": text[:50000], "error": error}
    Path(state_file).write_text(json.dumps(data))
    print(f"Saved state to {state_file}")


def check_page(name, config):
    url = config["url"]
    state_file = config["state_file"]

    print(f"\nChecking {name}: {url}")
    previous = load_previous_state(state_file)

    try:
        html = fetch_page(url)
        text = extract_stable_content(html)
        
        # Ignorer les pages de maintenance
        if is_maintenance_page(text.lower()):
            print(f"Maintenance page detected for {name}, skipping")
            return
        
        current_hash = get_content_hash(text)

        print(f"Current hash: {current_hash}")
        print(f"Previous hash: {previous['hash'] if previous else 'None'}")

        # Si on était en erreur et ça remarche
        if previous and previous.get("error"):
            send_notification(f"{name} - Retour OK", "Le site répond à nouveau.", priority=0, url=url)
            save_state(state_file, current_hash, text, error=False)
            return

        # Premier run
        if previous is None:
            save_state(state_file, current_hash, text, error=False)
            send_notification(f"Monitoring {name} activé", "Surveillance en place. Alerte si changement.", priority=0, url=url)
            return

        # Changement
        if current_hash != previous["hash"]:
            diff = find_differences(previous.get("text", ""), text)
            send_notification(f"CHANGEMENT sur {name}", diff, priority=1, url=url)
            save_state(state_file, current_hash, text, error=False)
        else:
            print("No changes")

    except Exception as e:
        print(f"Error checking {name}: {e}")
        was_error = previous.get("error", False) if previous else False
        if not was_error:
            send_notification(f"Erreur monitoring {name}", str(e)[:200], priority=1, url=url)

        prev_hash = previous.get("hash", "") if previous else ""
        prev_text = previous.get("text", "") if previous else ""
        save_state(state_file, prev_hash, prev_text, error=True)


def check_for_changes():
    print(f"Starting checks at {datetime.now().isoformat()}")
    for name, config in PAGES.items():
        try:
            check_page(name, config)
        except Exception as e:
            print(f"Error with {name}: {e}")
            continue


def send_heartbeat():
    print(f"Sending heartbeat at {datetime.now().isoformat()}")
    statuses = []
    for name, config in PAGES.items():
        try:
            fetch_page(config["url"])
            statuses.append(f"- {name}: OK")
        except Exception:
            statuses.append(f"- {name}: Erreur")
    send_notification("Monitoring OK", f"Le monitoring fonctionne.\n\n" + "\n".join(statuses), priority=-1)


if __name__ == "__main__":
    if CHECK_TYPE == "heartbeat":
        send_heartbeat()
    else:
        check_for_changes()
