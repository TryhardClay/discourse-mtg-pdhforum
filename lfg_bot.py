#!/usr/bin/env python3
"""
PDH Forum LFG Bot
Monitors for LFG requests via PM to @PDHMatchmaker,
creates Looking for Game topics, monitors polls,
and creates Convoke game rooms when matches are found.
"""

import requests
import time
import json
import logging
from datetime import datetime, timezone

# ============================================================
# Configuration
# ============================================================

DISCOURSE_URL = "https://pdhforum.com"
DISCOURSE_API_KEY = "6421b230423d9fcfc043e4f1537441baa05e079f0a7442494c7ecc929360f3c3"
DISCOURSE_BOT_USERNAME = "PDHMatchmaker"

CONVOKE_API_URL = "https://api.convoke.games/api/game/create-game"
CONVOKE_API_KEY = "convk_6536e0adb4c407d49bfa7d4ee4d44c489dc147a6"

LFG_CATEGORY_ID = 35
LFG_TAG = "lfg"
POLL_INTERVAL_SECONDS = 30

# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/var/log/lfg_bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================
# Discourse API Helpers
# ============================================================

HEADERS = {
    "Api-Key": DISCOURSE_API_KEY,
    "Api-Username": DISCOURSE_BOT_USERNAME,
    "Content-Type": "application/json"
}

def discourse_get(path, params=None):
    r = requests.get(f"{DISCOURSE_URL}{path}", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()

def discourse_post(path, data):
    r = requests.post(f"{DISCOURSE_URL}{path}", headers=HEADERS, json=data)
    r.raise_for_status()
    return r.json()

def discourse_delete(path):
    r = requests.delete(f"{DISCOURSE_URL}{path}", headers=HEADERS)
    r.raise_for_status()
    return r

def get_unread_pms():
    """Fetch unread private messages sent to the bot."""
    data = discourse_get("/topics/private-messages/PDHMatchmaker.json")
    topics = data.get("topic_list", {}).get("topics", [])
    return [t for t in topics if t.get("unread_posts", 0) > 0 or t.get("highest_post_number", 0) == 1]

def get_topic_posts(topic_id):
    """Fetch all posts in a topic."""
    data = discourse_get(f"/t/{topic_id}.json")
    return data

def send_pm(username, subject, message):
    """Send a private message to a user."""
    data = {
        "title": subject,
        "raw": message,
        "target_recipients": username,
        "archetype": "private_message"
    }
    return discourse_post("/posts.json", data)

def reply_to_pm(topic_id, message):
    """Reply to an existing PM thread."""
    data = {
        "topic_id": topic_id,
        "raw": message
    }
    return discourse_post("/posts.json", data)

def create_lfg_topic(requester_username):
    """Create a Looking for Game topic on behalf of the requesting user."""
    title = f"Looking for a 1v1 PDH Game — {requester_username}"
    body = f"""Looking for a 1v1 PDH game on Convoke! Vote below to join @{requester_username}.

> ⏱ This post expires in 1 hour. If a second player joins before then,
> a Convoke game room will be created automatically and both players
> will receive a join link via private message. If no one joins, this
> post will be removed automatically.

**Format:** 1v1 PDH
**Platform:** Convoke (webcam)

[poll type=regular results=always public=true close=1h]
* Join me
[/poll]"""

    data = {
        "title": title,
        "raw": body,
        "category": LFG_CATEGORY_ID,
        "tags": [LFG_TAG]
    }
    return discourse_post("/posts.json", data)

def get_lfg_topics():
    """Fetch all open topics in the LFG category."""
    data = discourse_get(f"/c/{LFG_CATEGORY_ID}.json")
    return data.get("topic_list", {}).get("topics", [])

def get_poll_data(topic_id):
    """Fetch poll data from a topic."""
    data = discourse_get(f"/t/{topic_id}.json")
    posts = data.get("post_stream", {}).get("posts", [])
    if not posts:
        return None, None, data

    first_post = posts[0]
    polls = first_post.get("polls", [])
    if not polls:
        return None, None, data

    poll = polls[0]
    voters = poll.get("voters", 0)
    is_closed = poll.get("status") == "closed"
    voter_data = poll.get("options", [])

    return voters, is_closed, data

def get_poll_voters(topic_id, post_id):
    """Get usernames of users who voted in the poll."""
    try:
        data = discourse_get(
            f"/polls/voters.json",
            params={
                "topic_id": topic_id,
                "post_id": post_id,
                "poll_name": "poll",
                "option_id": "0"  # First option
            }
        )
        voters = data.get("voters", {})
        # voters is a dict keyed by option_id
        all_voters = []
        for option_voters in voters.values():
            all_voters.extend([v.get("username") for v in option_voters if v.get("username")])
        return all_voters
    except Exception as e:
        log.error(f"Failed to get poll voters for topic {topic_id}: {e}")
        return []

def delete_topic(topic_id):
    """Delete a topic."""
    return discourse_delete(f"/t/{topic_id}.json")

def close_topic(topic_id):
    """Close a topic."""
    data = {"status": "closed", "enabled": "true"}
    r = requests.put(f"{DISCOURSE_URL}/t/{topic_id}/status.json", headers=HEADERS, json=data)
    r.raise_for_status()
    return r.json()

# ============================================================
# Convoke API
# ============================================================

def create_convoke_room(requester_username):
    """Create a Convoke game room and return the join URL."""
    payload = {
        "apiKey": CONVOKE_API_KEY,
        "name": f"PDH Forum 1v1 — {requester_username}",
        "isPublic": False,
        "seatLimit": 2,
        "format": "standard"
    }
    r = requests.post(CONVOKE_API_URL, json=payload)
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("url")

# ============================================================
# Bot State (in-memory)
# ============================================================

# Tracks PM topic IDs we've already processed to avoid double-acting
processed_pm_ids = set()

# Maps LFG topic_id -> requester_username
active_lfg_topics = {}

# ============================================================
# Core Logic
# ============================================================

def handle_lfg_request(pm_topic_id, requester_username):
    """Process an incoming LFG PM request."""
    log.info(f"LFG request from {requester_username} (PM topic {pm_topic_id})")

    try:
        result = create_lfg_topic(requester_username)
        lfg_topic_id = result.get("topic_id")

        if not lfg_topic_id:
            log.error(f"Failed to create LFG topic for {requester_username}")
            reply_to_pm(pm_topic_id, "Sorry, I couldn't create your LFG post right now. Please try again in a moment.")
            return

        active_lfg_topics[lfg_topic_id] = requester_username
        topic_url = f"{DISCOURSE_URL}/t/{lfg_topic_id}"

        reply_to_pm(
            pm_topic_id,
            f"Your LFG post is live! ➡️ {topic_url}\n\n"
            f"I'll notify you via PM as soon as an opponent joins. "
            f"If no one joins within 1 hour, the post will be removed automatically."
        )
        log.info(f"Created LFG topic {lfg_topic_id} for {requester_username}")

    except Exception as e:
        log.error(f"Error handling LFG request from {requester_username}: {e}")
        reply_to_pm(pm_topic_id, "Sorry, something went wrong creating your LFG post. Please try again.")

def check_pm_inbox():
    """Check for new LFG requests via PM."""
    try:
        pms = get_unread_pms()
        for pm in pms:
            pm_topic_id = pm.get("id")
            if pm_topic_id in processed_pm_ids:
                continue

            # Fetch the actual PM content
            topic_data = get_topic_posts(pm_topic_id)
            posts = topic_data.get("post_stream", {}).get("posts", [])

            if not posts:
                continue

            # Get the first post (the original message)
            first_post = posts[0]
            raw = first_post.get("raw", "").strip().lower()
            requester_username = first_post.get("username")

            # Ignore messages from the bot itself
            if requester_username == DISCOURSE_BOT_USERNAME:
                processed_pm_ids.add(pm_topic_id)
                continue

            if "lfg" in raw:
                processed_pm_ids.add(pm_topic_id)
                handle_lfg_request(pm_topic_id, requester_username)
            else:
                # Not an LFG trigger — send help message
                processed_pm_ids.add(pm_topic_id)
                reply_to_pm(
                    pm_topic_id,
                    "Hi! To find a 1v1 PDH game, send me a PM with just the word **lfg** and I'll create a match post for you automatically."
                )

    except Exception as e:
        log.error(f"Error checking PM inbox: {e}")

def check_active_lfg_topics():
    """Check all active LFG topics for fulfilled polls or expired polls."""
    stale_topics = []

    for topic_id, requester_username in list(active_lfg_topics.items()):
        try:
            voters, is_closed, topic_data = get_poll_data(topic_id)

            if voters is None:
                # Topic may have been deleted or poll removed
                stale_topics.append(topic_id)
                continue

            if voters >= 2:
                # Poll fulfilled — get voter usernames
                posts = topic_data.get("post_stream", {}).get("posts", [])
                post_id = posts[0].get("id") if posts else None
                voter_usernames = get_poll_voters(topic_id, post_id) if post_id else []

                # Find the joiner (not the requester)
                joiner = next((u for u in voter_usernames if u != requester_username), None)

                log.info(f"Match found! Topic {topic_id}: {requester_username} vs {joiner}")

                # Create Convoke room
                try:
                    room_url = create_convoke_room(requester_username)
                    if room_url:
                        msg = (
                            f"✅ **Match found!** Your 1v1 PDH game is ready.\n\n"
                            f"**Join your game here:** {room_url}\n\n"
                            f"Good luck and have fun!"
                        )
                        send_pm(requester_username, "Your 1v1 PDH game is ready!", msg)
                        if joiner:
                            send_pm(joiner, "Your 1v1 PDH game is ready!", msg)
                        log.info(f"Convoke room created and PMs sent: {room_url}")
                    else:
                        log.error("Convoke returned no URL")
                        send_pm(requester_username, "Match found but room creation failed", "A match was found but the Convoke room couldn't be created. Please coordinate directly.")
                except Exception as e:
                    log.error(f"Convoke API error: {e}")
                    send_pm(requester_username, "Match found but room creation failed", "A match was found but the Convoke room couldn't be created. Please coordinate directly.")

                # Delete the LFG topic
                try:
                    delete_topic(topic_id)
                    log.info(f"Deleted fulfilled LFG topic {topic_id}")
                except Exception as e:
                    log.error(f"Failed to delete topic {topic_id}: {e}")

                stale_topics.append(topic_id)

            elif is_closed and voters < 2:
                # Poll expired with no match
                log.info(f"LFG topic {topic_id} expired with no match for {requester_username}")
                send_pm(
                    requester_username,
                    "Your LFG post expired",
                    "Unfortunately no opponent joined your LFG post before it expired. Feel free to try again anytime!"
                )
                try:
                    delete_topic(topic_id)
                    log.info(f"Deleted expired LFG topic {topic_id}")
                except Exception as e:
                    log.error(f"Failed to delete expired topic {topic_id}: {e}")

                stale_topics.append(topic_id)

        except Exception as e:
            log.error(f"Error checking LFG topic {topic_id}: {e}")

    # Clean up stale entries
    for topic_id in stale_topics:
        active_lfg_topics.pop(topic_id, None)

def restore_active_topics():
    """On startup, reload any existing LFG topics into memory."""
    log.info("Restoring active LFG topics from forum...")
    try:
        topics = get_lfg_topics()
        for topic in topics:
            topic_id = topic.get("id")
            title = topic.get("title", "")
            # Parse requester username from title format "Looking for a 1v1 PDH Game — username"
            if "—" in title:
                requester_username = title.split("—")[-1].strip()
                active_lfg_topics[topic_id] = requester_username
                log.info(f"  Restored topic {topic_id} for {requester_username}")
    except Exception as e:
        log.error(f"Error restoring active topics: {e}")

# ============================================================
# Main Loop
# ============================================================

def main():
    log.info("PDH Forum LFG Bot starting...")
    restore_active_topics()
    log.info(f"Monitoring every {POLL_INTERVAL_SECONDS} seconds. Active topics: {len(active_lfg_topics)}")

    while True:
        check_pm_inbox()
        check_active_lfg_topics()
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
