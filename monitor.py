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
STATE_FILE = Path("state.txt")

OPEN_INDICATORS = [
    "waitlist is now open",
    "join the waitlist",
    "register now",
    "sign up", 
    "apply now",
    "spots available",
    "inscription",
    "ouvert",
]


def fetch_page() -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    response = requests.get(URL, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def extract_stable_content(html: str) -> str:
    """Extract only the stable parts of the page that matter."""
    # Get text content
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Look for the important section about RO Nomination
    # Extract key phrases that would change if registration opens
    important_phrases = []
    
    keywords = [
        "2026 RO waitlist",
        "2025 season is now closed",
        "in December",
        "Sold out",
        "waitlist",
        "registration",
        "inscription",
        "apply",
        "join",
    ]
    
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            # Find context around keyword
            idx = text_lower.find(kw.lower())
            start = max(0, idx - 30)
            end = min(len(text), idx + len(kw) + 30)
            important_phrases.append(text[start:end])
    
    # Also check for "Add to cart" vs "Sold out" button state
    if "sold out" in text_lower:
        important_phrases.append("STATUS:SOLD_OUT")
    if "add to cart" in text_lower:
        important_phrases.append("STATUS:AVAILABLE")
    
    return "|".join(sorted(important_phrases))


def get_content_hash(html: str) -> str:
    """Get hash of only the important content."""
    stable_content = extract_stable_content(html)
    return hashlib.md5(stable_content.encode()).hexdigest()


def check_open_indicators(html: str) -> list:
    """Check if any indicators suggest the waitlist is open."""
    text = re.sub(r'<[^>]+>', ' ', html).lower()
    found = []
    for indicator in OPEN_INDICATORS:
        if indicator.lower() in text:
            found.append(indicator)
    return found


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


def load_previous_hash() -> str | None:
    if STATE_FILE.exists():
        content = STATE_FILE.read_text().strip()
        print(f"📂 Loaded previous hash: {content[:20]}...")
        return content
    print("📂 No previous state found")
    return None


def save_hash(content_hash: str):
    STATE_FILE.write_text(content_hash)
    print(f"💾 Saved hash: {content_hash[:20]}...")


def check_for_changes():
    print(f"🔍 Checking SWAP page at {datetime.now().isoformat()}")
    
    try:
        html = fetch_page()
        current_hash = get_content_hash(html)
        previous_hash = load_previous_hash()
        
        print(f"Current hash: {current_hash}")
        print(f"Previous hash: {previous_hash}")
        
        # Check for open indicators (HIGH PRIORITY)
        open_indicators = check_open_indicators(html)
        if "add to cart" in [i.lower() for i in open_indicators] or "apply now" in [i.lower() for i in open_indicators]:
            send_notification(
                "🚨 SWAP PEUT-ÊTRE OUVERT !",
                "Le bouton semble actif !\n\nFONCE MAINTENANT !",
                priority=2,
                url=URL,
            )
            save_hash(current_hash)
            return
        
        # First run
        if previous_hash is None:
            print("📝 First run - saving initial state")
            save_hash(current_hash)
            send_notification(
                "✅ Monitoring SWAP activé",
                "Je surveille la page RO Nomination.\nTu recevras une alerte si quelque chose change.",
                priority=0,
            )
            return
        
        # Compare
        if current_hash != previous_hash:
            print("🔔 Change detected!")
            send_notification(
                "⚠️ CHANGEMENT SUR SWAP !",
                "La page RO Nomination a été modifiée.\nVérifie maintenant !",
                priority=1,
                url=URL,
            )
            save_hash(current_hash)
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
        
        if "add to cart" in html.lower():
            send_notification("🚨 WAITLIST OUVERTE !", "FONCE !", priority=2, url=URL)
            return
        
        status = "Sold out" if "sold out" in html.lower() else "Inconnu"
        send_notification(
            "💓 Monitoring SWAP OK", 
            f"Le monitoring fonctionne.\nStatut actuel: {status}",
            priority=-1,
        )
    except Exception as e:
        send_notification("❌ Heartbeat échoué", str(e)[:200], priority=1)


if __name__ == "__main__":
    if CHECK_TYPE == "heartbeat":
        send_heartbeat()
    else:
        check_for_changes()