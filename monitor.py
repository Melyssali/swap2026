#!/usr/bin/env python3
"""
SWAP Canada RO Nomination Page Monitor
Checks for changes and sends notifications via Pushover
"""

import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

# Configuration
URL = "https://swap.ca/products/canada-ro-nomination-whv"
PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN")
CHECK_TYPE = os.environ.get("CHECK_TYPE", "change")

KEY_PHRASES = [
    "in December",
    "2026 RO waitlist",
    "Sold out",
    "2025 season is now closed",
    "Check this webpage for updates",
]

OPEN_INDICATORS = [
    "waitlist is now open",
    "join the waitlist",
    "register now",
    "sign up",
    "apply now",
    "spots available",
]


def fetch_page() -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    response = requests.get(URL, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def extract_relevant_content(html: str) -> dict:
    content = {
        "full_hash": hashlib.md5(html.encode()).hexdigest(),
        "key_phrases_found": {},
        "open_indicators_found": [],
    }
    
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)
    text_lower = text.lower()
    
    for phrase in KEY_PHRASES:
        if phrase.lower() in text_lower:
            content["key_phrases_found"][phrase] = True
    
    for indicator in OPEN_INDICATORS:
        if indicator.lower() in text_lower:
            content["open_indicators_found"].append(indicator)
    
    return content


def send_notification(title: str, message: str, priority: int = 1, url: str = None):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        print("❌ Pushover credentials not configured")
        return
    
    try:
        data = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message,
            "priority": priority,
        }
        
        if url:
            data["url"] = url
            data["url_title"] = "Ouvrir SWAP"
        
        if priority == 2:
            data["retry"] = 60
            data["expire"] = 3600
        
        response = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=data,
            timeout=10,
        )
        response.raise_for_status()
        print(f"✅ Notification sent: {title}")
    except Exception as e:
        print(f"❌ Failed to send notification: {e}")


def load_previous_state() -> dict | None:
    state_file = Path("previous_state.txt")
    if state_file.exists():
        return {"hash": state_file.read_text().strip()}
    return None


def save_state(content_hash: str):
    Path("previous_state.txt").write_text(content_hash)


def check_for_changes():
    print(f"🔍 Checking SWAP page at {datetime.now().isoformat()}")
    
    try:
        html = fetch_page()
        content = extract_relevant_content(html)
        previous = load_previous_state()
        
        if content["open_indicators_found"]:
            send_notification(
                "🚨 SWAP WAITLIST OUVERTE !",
                f"Indicateurs: {', '.join(content['open_indicators_found'])}\n\nFONCE MAINTENANT !",
                priority=2,
                url=URL,
            )
            save_state(content["full_hash"])
            return
        
        if previous is None:
            print("📝 First run - saving initial state")
            save_state(content["full_hash"])
            send_notification(
                "✅ Monitoring SWAP activé",
                "Je surveille la page RO Nomination.\nTu recevras une alerte si quelque chose change.",
                priority=0,
            )
            return
        
        if content["full_hash"] != previous["hash"]:
            send_notification(
                "⚠️ CHANGEMENT SUR SWAP !",
                "La page RO Nomination a été modifiée.\nVérifie maintenant !",
                priority=1,
                url=URL,
            )
            save_state(content["full_hash"])
        else:
            print("✓ No changes detected")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        send_notification("❌ Erreur monitoring SWAP", str(e)[:200], priority=1)
        sys.exit(1)


def send_heartbeat():
    print(f"💓 Sending heartbeat at {datetime.now().isoformat()}")
    try:
        html = fetch_page()
        content = extract_relevant_content(html)
        
        if content["open_indicators_found"]:
            send_notification("🚨 WAITLIST OUVERTE !", "FONCE !", priority=2, url=URL)
            return
        
        send_notification("💓 Monitoring SWAP OK", "Le monitoring fonctionne.", priority=-1)
    except Exception as e:
        send_notification("❌ Heartbeat échoué", str(e)[:200], priority=1)


if __name__ == "__main__":
    if CHECK_TYPE == "heartbeat":
        send_heartbeat()
    else:
        check_for_changes()
