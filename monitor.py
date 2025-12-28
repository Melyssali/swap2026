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

# Configuration
PAGES = {
    "IEC Programs": {
        "url": "https://internship-network.org/iec-programs/",
        "state_file": "state_iec.txt",
        "urgent_keyword": "register now",
        "filter_keywords": ["2025", "2026", "season", "closed", "open", "december", "january", "application", "update", "iec", "working holiday", "check back"],
    },
    "Internship Network": {
        "url": "https://internship-network.org",
        "state_file": "state_internship.txt",
        "urgent_keyword": "register now",
        "filter_keywords": ["2025", "2026", "season", "closed", "open", "december", "january", "application", "update", "iec", "working holiday", "check back"],
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


def fetch_page(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def extract_stable_content(html: str, filter_keywords: list = None) -> str:
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # If filter_keywords provided, only keep sentences containing those keywords
    if filter_keywords:
        sentences = re.split(r'[.!?]', text)
        relevant = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            if any(kw.lower() in sentence_lower for kw in filter_keywords):
                relevant.append(sentence.strip())
        text = " | ".join(relevant)
    
    return text


def get_content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def find_differences(old_text: str, new_text: str) -> str:
    old_words = set(old_text.lower().split())
    new_words = set(new_text.lower().split())
    
    added = new_words - old_words
    removed = old_words - new_words
    
    diff_parts = []
    if added:
        added_sample = list(added)[:10]
        diff_parts.append(f"Nouveaux mots: {', '.join(added_sample)}")
    if removed:
        removed_sample = list(removed)[:10]
        diff_parts.append(f"Mots retirés: {', '.join(removed_sample)}")
    
    if not diff_parts:
        return "Changement de structure/ordre détecté"
    
    return "\n".join(diff_parts)


def send_notification(title: str, message: str, priority: int = 1, url: str = None):
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
        
        response = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=data,
            timeout=10,
        )
        response.raise_for_status()
        print(f"✅ Notification sent: {title}")
    except Exception as e:
        print(f"❌ Failed to send notification: {e}")


def load_previous_state(state_file: str) -> dict | None:
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


def save_state(state_file: str, content_hash: str, text: str):
    data = {
        "hash": content_hash,
        "text": text[:50000]
    }
    Path(state_file).write_text(json.dumps(data))
    print(f"💾 Saved state to {state_file}")


def check_page(name: str, config: dict):
    url = config["url"]
    state_file = config["state_file"]
    urgent_keyword = config["urgent_keyword"]
    filter_keywords = config.get("filter_keywords")
    
    print(f"\n🔍 Checking {name}: {url}")
    
    try:
        html = fetch_page(url)
        text = extract_stable_content(html, filter_keywords)