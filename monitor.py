#!/usr/bin/env python3
"""
SWAP Canada RO Nomination Page Monitor
Checks for changes and sends notifications via ntfy.sh
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
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "swap-monitor")
CHECK_TYPE = os.environ.get("CHECK_TYPE", "change")  # "change" or "heartbeat"

# Key phrases to monitor (if any of these change, it's important)
KEY_PHRASES = [
    "in December",
    "2026 RO waitlist",
    "Sold out",
    "2025 season is now closed",
    "Check this webpage for updates",
]

# Phrases that indicate the waitlist is OPEN (high priority alert)
OPEN_INDICATORS = [
    "waitlist is now open",
    "join the waitlist",
    "register now",
    "sign up",
    "apply now",
    "spots available",
]


def fetch_page() -> str:
    """Fetch the SWAP page content."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    response = requests.get(URL, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def extract_relevant_content(html: str) -> dict:
    """Extract the relevant sections we care about."""
    # Get the main product description area
    content = {
        "full_hash": hashlib.md5(html.encode()).hexdigest(),
        "key_phrases_found": {},
        "open_indicators_found": [],
        "raw_text": "",
    }
    
    # Extract text content (remove HTML tags)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)
    content["raw_text"] = text
    
    # Check for key phrases
    text_lower = text.lower()
    for phrase in KEY_PHRASES:
        if phrase.lower() in text_lower:
            # Find context around the phrase
            idx = text_lower.find(phrase.lower())
            start = max(0, idx - 50)
            end = min(len(text), idx + len(phrase) + 50)
            content["key_phrases_found"][phrase] = text[start:end].strip()
    
    # Check for open indicators (HIGH PRIORITY)
    for indicator in OPEN_INDICATORS:
        if indicator.lower() in text_lower:
            content["open_indicators_found"].append(indicator)
    
    return content


def send_notification(title: str, message: str, priority: str = "high", tags: str = "rotating_light"):
    """Send notification via ntfy.sh."""
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": tags,
            },
            data=message.encode("utf-8"),
            timeout=10,
        )
        print(f"✅ Notification sent: {title}")
    except Exception as e:
        print(f"❌ Failed to send notification: {e}")


def load_previous_state() -> dict | None:
    """Load previous state from file."""
    state_file = Path("previous_state.txt")
    if state_file.exists():
        return {"hash": state_file.read_text().strip()}
    return None


def save_state(content_hash: str):
    """Save current state to file."""
    Path("previous_state.txt").write_text(content_hash)


def check_for_changes():
    """Main check logic."""
    print(f"🔍 Checking SWAP page at {datetime.now().isoformat()}")
    
    try:
        html = fetch_page()
        content = extract_relevant_content(html)
        previous = load_previous_state()
        
        # HIGH PRIORITY: Check if waitlist appears to be open
        if content["open_indicators_found"]:
            send_notification(
                "🚨 SWAP WAITLIST PEUT-ÊTRE OUVERTE !",
                f"Indicateurs détectés: {', '.join(content['open_indicators_found'])}\n\n"
                f"👉 Vérifie MAINTENANT: {URL}",
                priority="urgent",
                tags="rotating_light,canada",
            )
            save_state(content["full_hash"])
            return
        
        # Check if this is first run
        if previous is None:
            print("📝 First run - saving initial state")
            save_state(content["full_hash"])
            
            # Send initial status
            phrases_status = "\n".join(
                f"• {phrase}: ✓ trouvé" 
                for phrase in content["key_phrases_found"]
            )
            send_notification(
                "✅ Monitoring SWAP activé",
                f"Je surveille la page RO Nomination.\n\n"
                f"Phrases clés actuelles:\n{phrases_status}\n\n"
                f"Tu recevras une alerte si quelque chose change.",
                priority="default",
                tags="white_check_mark,canada",
            )
            return
        
        # Compare with previous state
        if content["full_hash"] != previous["hash"]:
            # Something changed!
            send_notification(
                "⚠️ CHANGEMENT DÉTECTÉ SUR SWAP !",
                f"La page RO Nomination a été modifiée.\n\n"
                f"👉 Vérifie: {URL}",
                priority="urgent",
                tags="warning,canada",
            )
            save_state(content["full_hash"])
        else:
            print("✓ No changes detected")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        send_notification(
            "❌ Erreur monitoring SWAP",
            f"Le script a rencontré une erreur:\n{str(e)[:200]}",
            priority="high",
            tags="x,warning",
        )
        sys.exit(1)


def send_heartbeat():
    """Send daily heartbeat to confirm monitoring is working."""
    print(f"💓 Sending heartbeat at {datetime.now().isoformat()}")
    
    try:
        html = fetch_page()
        content = extract_relevant_content(html)
        
        # Check current status
        status_lines = []
        
        if "Sold out" in content["key_phrases_found"]:
            status_lines.append("• Statut: Sold out (inchangé)")
        
        if "in December" in content["key_phrases_found"]:
            status_lines.append("• Waitlist 2026: prévu en décembre")
        
        if content["open_indicators_found"]:
            status_lines.append(f"• ⚠️ INDICATEURS D'OUVERTURE: {content['open_indicators_found']}")
        
        status = "\n".join(status_lines) if status_lines else "• Page inchangée"
        
        send_notification(
            "💓 Monitoring SWAP OK",
            f"Le monitoring fonctionne.\n\n{status}\n\n"
            f"Prochaine vérification dans 5 min.",
            priority="low",
            tags="heart,canada",
        )
        
    except Exception as e:
        send_notification(
            "❌ Heartbeat échoué",
            f"Erreur lors du heartbeat:\n{str(e)[:200]}",
            priority="high",
            tags="x,warning",
        )


if __name__ == "__main__":
    if CHECK_TYPE == "heartbeat":
        send_heartbeat()
    else:
        check_for_changes()
