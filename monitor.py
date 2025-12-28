#!/usr/bin/env python3
"""
Multi-page Monitor for Canadian Visa
Checks for changes and sends notifications via Pushover
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

PAGES = {
    "IEC Programs": {
        "url": "https://internship-network.org/iec-programs/",
        "state_file": "state_iec.txt",
        "urgent_keyword": "register now",
        "filter_keywords": ["2025", "2026", "season", "closed", "open", "december", "january", "application", "update"],
    },
    "Internship Network": {
        "url": "https://internship-network.org",
        "state_file": "state_internship.txt",
        "urgent_keyword": "register now",
        "filter_keywords": ["2025", "2026", "season", "closed", "open", "december", "january", "application", "update"],
    },
    "Jenza": {
        "url": "https://jenza.com/experiences/working-holidays/work-canada-ro/",
        "state_file": "state_jenza.txt",
        "urgent_keyword": "apply now",
        "filter_keywords": None,
    },
}

PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN")
CHECK_TYPE = os.environ.get("CHECK_TYPE", "change")


def fetch_page(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def extract_stable_content(html, filter_keywords=None):
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    if filter_keywords:
        sentences = re.split(r'[.!?]', text)
        relevant = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            if any(kw.lower() in sentence_lower for kw in filter_keywords):
                relevant.append(sentence.strip())
        text = " | ".join(relevant)
    
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
        return "Changement de structure/ordre détecté"
    return "\n".join(diff_parts)


def send_notification(title, message, priority=1, url=None):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        print("❌ Pushover credentials not configured")
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
        print(f"✅ Notification sent: {title}")
    except Exception as e:
        print(f"❌ Failed to send notification: {e}")


def load_previous_state(state_file):
    path = Path(state_file)
    if path.exists():
        try:
            content = path.read_text().strip()
            if not content:
                return None
            data = json.loads(content)
            if isinstance(data, str):
                return {"hash": data, "text": ""}
            return data
        except Exception:
            return None
    return None


def save_state(state_file, content_hash, text):
    data = {"hash": content_hash, "text": text[:50000]}
    Path(state_file).write_text(json.dumps(data))
    print(f"💾 Saved state to {state_file}")


def check_page(name, config):
    url = config["url"]
    state_file = config["state_file"]
    urgent_keyword = config["urgent_keyword"]
    filter_keywords = config.get("filter_keywords")
    
    print(f"\n🔍 Checking {name}: {url}")
    
    try:
        html = fetch_page(url)
        text = extract_stable_content(html, filter_keywords)
        current_hash = get_content_hash(text)
        previous = load_previous_state(state_file)
        text_lower = html.lower()
        
        print(f"Current hash: {current_hash}")
        print(f"Previous hash: {previous['hash'] if previous else 'None'}")
        
        if urgent_keyword and urgent_keyword in text_lower:
            send_notification(
                f"🚨 {name} - PEUT-ÊTRE OUVERT !",
                f"'{urgent_keyword}' détecté !\n\nFONCE MAINTENANT !",
                priority=2,
                url=url,
            )
            save_state(state_file, current_hash, text)
            return
        
        if previous is None:
            print(f"📝 First run for {name} - saving initial state")
            save_state(state_file, current_hash, text)
            send_notification(
                f"✅ Monitoring {name} activé",
                f"Je surveille cette page.\nTu recevras une alerte si quelque chose change.",
                priority=0,
            )
            return
        
        if current_hash != previous["hash"]:
            print(f"🔔 Change detected on {name}!")
            diff = find_differences(previous.get("text", ""), text)
            send_notification(
                f"⚠️ CHANGEMENT sur {name} !",
                f"La page a été modifiée.\n\n{diff}",
                priority=1,
                url=url,
            )
            save_state(state_file, current_hash, text)
        else:
            print(f"✓ No changes on {name}")
    except Exception as e:
        print(f"❌ Error checking {name}: {e}")
        send_notification(f"❌ Erreur monitoring {name}", str(e)[:200], priority=1)


def check_for_changes():
    print(f"🔍 Starting checks at {datetime.now().isoformat()}")
    for name, config in PAGES.items():
        try:
            check_page(name, config)
        except Exception as e:
            print(f"❌ Error with {name}: {e}")
            continue


def send_heartbeat():
    print(f"💓 Sending heartbeat at {datetime.now().isoformat()}")
    statuses = []
    for name, config in PAGES.items():
        try:
            html = fetch_page(config["url"])
            if "register now" in html.lower() or "apply now" in html.lower():
                send_notification(f"🚨 {name} OUVERT !", "FONCE !", priority=2, url=config["url"])
                statuses.append(f"• {name}: ⚠️ OUVERT?")
            else:
                statuses.append(f"• {name}: OK")
        except Exception as e:
            statuses.append(f"• {name}: ❌ Erreur")
    send_notification("💓 Monitoring OK", f"Le monitoring fonctionne.\n\n" + "\n".join(statuses), priority=-1)


if __name__ == "__main__":
    if CHECK_TYPE == "heartbeat":
        send_heartbeat()
    else:
        check_for_changes()