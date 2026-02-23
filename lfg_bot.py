#!/usr/bin/env python3
"""
PDH Forum LFG Bot v2
Monitors chat DMs to @PDHMatchmaker for LFG triggers,
creates Looking for Game topics in the appropriate category,
monitors polls, and delivers Convoke game links via chat DM.

Triggers:
  casual -> Casual PDH LFG (4 players)
  comp   -> Competitive PDH LFG (4 players)
  1v1    -> 1v1 PDH LFG (2 players)
"""

import requests
import time
import logging

# ============================================================
# Configuration
# ============================================================

DISCOURSE_URL = "https://pdhforum.com"
DISCOURSE_API_KEY = "6421b230423d9fcfc043e4f1537441baa05e079f0a7442494c7ecc929360f3c3"
DISCOURSE_BOT_USERNAME = "PDHMatchmaker"

CONVOKE_API_URL = "https://api.convoke.games/api/game/create-game"
CONVOKE_API_KEY = "convk_6536e0adb4c407d49bfa7d4ee4d44c489dc147a6"

POLL_INTERVAL_SECONDS = 30

# LFG category config: trigger -> (category_id, seat_count, convoke_format, label)
LFG_FORMATS = {
    "casual": (36, 4, "commander", "Casual PDH"),
    "comp":   (37, 4, "commander", "Competitive PDH"),
    "1v1":    (35, 2, "standard",  "1v1 PDH"),
}

LFG_TAG = "lfg"

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

# ============================================================
# Chat API Helpers
# ============================================================

def get_dm_channels():
    """Fetch all DM channels for the bot account."""
    data = discourse_get("/chat/api/me/channels")
    return data.get("direct_message_channels", [])

def get_channel_messages(channel_id):
    """Fetch messages from a chat DM channel."""
    data = discourse_get(f"/chat/api/channels/{channel_id}/messages")
    return data.get("messages", [])

def send_chat_message(channel_id, message):
    """Send a message to a chat channel."""
    data = {"message": message}
    return discourse_post(f"/chat/{channel_id}", data)

def get_or_create_dm_channel(username):
    """Get or create a DM channel with a specific user."""
    data = {"target_usernames": [username]}
    result = discourse_post("/chat/api/direct-messages", data)
    return result.get("channel", {}).get("id")

# ============================================================
# Topic Helpers
# ============================================================

def create_lfg_topic(requester_username, format_key):
    """Create a Looking for Game topic for the given format."""
    category_id, seat_count, _, label = LFG_FORMATS[format_key]

    title = f"Looking for a {label} Game — {requester_username}"

    if seat_count == 2:
        poll_line = "Vote below — first player to join gets the spot!"
        seat_text = "Once a second player joins the poll, both players will receive a Convoke link via DM."
    else:
        poll_line = "Vote below — 3 spots available!"
        seat_text = f"Once all {seat_count} spots are filled, everyone will receive a Convoke link via DM."

    body = f"""@{requester_username} is looking for a {label} game on Convoke! {poll_line}

> ⏱ This post expires in 1 hour. {seat_text} If the poll doesn't fill in time, it will be removed automatically and all participants will be notified via DM. No Discord required.

**Format:** {label}
**Platform:** Convoke (webcam)

[poll type=regular results=on_vote public=true close=1h]
* Join me
[/poll]"""

    data = {
        "title": title,
        "raw": body,
        "category": category_id,
        "tags": [LFG_TAG]
    }
    return discourse_post("/posts.json", data)

def get_lfg_topics(category_id):
    """Fetch all open topics in an LFG category."""
    data = discourse_get(f"/c/{category_id}.json")
    return data.get("topic_list", {}).get("topics", [])

def get_poll_data(topic_id):
    """Fetch poll voters and status from a topic."""
    data = discourse_get(f"/t/{topic_id}.json")
    posts = data.get("post_stream", {}).get("posts", [])
    if not posts:
        return None, None, None, data
    first_post = posts[0]
    post_id = first_post.get("id")
    polls = first_post.get("polls", [])
    if not polls:
        return None, None, None, data
    poll = polls[0]
    voters = poll.get("voters", 0)
    is_closed = poll.get("status") == "closed"
    return voters, is_closed, post_id, data

def get_poll_voters(topic_id, post_id):
    """Get usernames of all poll voters."""
    try:
        data = discourse_get(
            "/polls/voters.json",
            params={
                "topic_id": topic_id,
                "post_id": post_id,
                "poll_name": "poll",
                "option_id": "0"
            }
        )
        voters = data.get("voters", {})
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

# ============================================================
# Convoke API
# ============================================================

def create_convoke_room(requester_username, format_key):
    """Create a Convoke game room and return the join URL."""
    _, seat_count, convoke_format, label = LFG_FORMATS[format_key]
    payload = {
        "apiKey": CONVOKE_API_KEY,
        "name": f"PDH Forum {label} — {requester_username}",
        "isPublic": False,
        "seatLimit": seat_count,
        "format": convoke_format
    }
    r = requests.post(CONVOKE_API_URL, json=payload)
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("url")

# ============================================================
# Bot State
# ============================================================

# channel_id -> last processed message id
processed_message_ids = {}

# topic_id -> {requester, format_key, channel_id}
active_lfg_topics = {}

# ============================================================
# Core Logic
# ============================================================

def handle_lfg_request(channel_id, requester_username, format_key):
    """Create an LFG topic and confirm via chat DM."""
    _, _, _, label = LFG_FORMATS[format_key]
    log.info(f"LFG request from {requester_username} for {label} (channel {channel_id})")

    try:
        result = create_lfg_topic(requester_username, format_key)
        topic_id = result.get("topic_id")

        if not topic_id:
            log.error(f"Failed to create LFG topic for {requester_username}")
            send_chat_message(channel_id, "Sorry, I couldn't create your LFG post right now. Please try again in a moment.")
            return

        active_lfg_topics[topic_id] = {
            "requester": requester_username,
            "format_key": format_key,
            "channel_id": channel_id
        }

        topic_url = f"{DISCOURSE_URL}/t/{topic_id}"
        send_chat_message(
            channel_id,
            f"Your LFG post is live! ➡️ {topic_url}\n\n"
            f"I'll DM you as soon as the game fills. "
            f"If no one joins within 1 hour the post will be removed and I'll let you know."
        )
        log.info(f"Created LFG topic {topic_id} for {requester_username} ({label})")

    except Exception as e:
        log.error(f"Error creating LFG topic for {requester_username}: {e}")
        send_chat_message(channel_id, "Sorry, something went wrong. Please try again.")

def check_dm_channels():
    """Check all DM channels for new LFG trigger messages."""
    try:
        channels = get_dm_channels()
        for channel in channels:
            channel_id = channel.get("id")
            tracking = channel.get("meta", {}).get("message_bus_last_ids", {})
            unread = tracking.get("new_messages", 0)

            if unread == 0:
                continue

            messages = get_channel_messages(channel_id)
            last_seen = processed_message_ids.get(channel_id, 0)

            for msg in messages:
                msg_id = msg.get("id", 0)
                if msg_id <= last_seen:
                    continue

                sender = msg.get("user", {}).get("username")
                if sender == DISCOURSE_BOT_USERNAME:
                    processed_message_ids[channel_id] = max(last_seen, msg_id)
                    continue

                text = msg.get("message", "").strip().lower()
                processed_message_ids[channel_id] = max(last_seen, msg_id)

                if text in LFG_FORMATS:
                    handle_lfg_request(channel_id, sender, text)
                else:
                    send_chat_message(
                        channel_id,
                        "Hi! I can help you find a PDH game on Convoke.\n\n"
                        "Send me one of these:\n"
                        "• **casual** — find a Casual PDH game (4 players)\n"
                        "• **comp** — find a Competitive PDH game (4 players)\n"
                        "• **1v1** — find a 1v1 PDH match (2 players)"
                    )

    except Exception as e:
        log.error(f"Error checking DM channels: {e}")

def check_active_lfg_topics():
    """Check all active LFG topics for fulfilled or expired polls."""
    stale_topics = []

    for topic_id, info in list(active_lfg_topics.items()):
        requester = info["requester"]
        format_key = info["format_key"]
        channel_id = info["channel_id"]
        _, seat_count, _, label = LFG_FORMATS[format_key]

        try:
            voters, is_closed, post_id, topic_data = get_poll_data(topic_id)

            if voters is None:
                stale_topics.append(topic_id)
                continue

            if voters >= seat_count:
                # Poll fulfilled
                voter_usernames = get_poll_voters(topic_id, post_id) if post_id else []
                log.info(f"Match found! Topic {topic_id} ({label}): {voter_usernames}")

                try:
                    room_url = create_convoke_room(requester, format_key)
                    if room_url:
                        msg = (
                            f"✅ **Game found!** Your {label} game is ready.\n\n"
                            f"**Join here:** {room_url}\n\n"
                            f"Good luck and have fun! No Discord required."
                        )
                        # DM all voters
                        for username in voter_usernames:
                            try:
                                dm_channel = get_or_create_dm_channel(username)
                                if dm_channel:
                                    send_chat_message(dm_channel, msg)
                            except Exception as e:
                                log.error(f"Failed to DM {username}: {e}")
                        log.info(f"Convoke room created and DMs sent: {room_url}")
                    else:
                        log.error("Convoke returned no URL")
                        send_chat_message(channel_id, "A match was found but the Convoke room couldn't be created. Please coordinate directly.")

                except Exception as e:
                    log.error(f"Convoke API error: {e}")
                    send_chat_message(channel_id, "A match was found but the Convoke room couldn't be created. Please coordinate directly.")

                try:
                    delete_topic(topic_id)
                    log.info(f"Deleted fulfilled LFG topic {topic_id}")
                except Exception as e:
                    log.error(f"Failed to delete topic {topic_id}: {e}")

                stale_topics.append(topic_id)

            elif is_closed and voters < seat_count:
                # Poll expired unfulfilled — notify all who did vote
                log.info(f"LFG topic {topic_id} expired with {voters}/{seat_count} players")

                voter_usernames = get_poll_voters(topic_id, post_id) if post_id else []
                notify_users = voter_usernames if voter_usernames else [requester]

                for username in notify_users:
                    try:
                        dm_channel = get_or_create_dm_channel(username)
                        if dm_channel:
                            send_chat_message(
                                dm_channel,
                                f"Unfortunately your {label} LFG post expired before it could fill "
                                f"({voters}/{seat_count} players joined). Feel free to try again anytime!"
                            )
                    except Exception as e:
                        log.error(f"Failed to notify {username}: {e}")

                try:
                    delete_topic(topic_id)
                    log.info(f"Deleted expired LFG topic {topic_id}")
                except Exception as e:
                    log.error(f"Failed to delete expired topic {topic_id}: {e}")

                stale_topics.append(topic_id)

        except Exception as e:
            log.error(f"Error checking LFG topic {topic_id}: {e}")

    for topic_id in stale_topics:
        active_lfg_topics.pop(topic_id, None)

def restore_active_topics():
    """On startup, reload existing LFG topics into memory."""
    log.info("Restoring active LFG topics from forum...")
    for format_key, (category_id, _, _, label) in LFG_FORMATS.items():
        try:
            topics = get_lfg_topics(category_id)
            for topic in topics:
                topic_id = topic.get("id")
                title = topic.get("title", "")
                if "—" in title:
                    requester = title.split("—")[-1].strip()
                    active_lfg_topics[topic_id] = {
                        "requester": requester,
                        "format_key": format_key,
                        "channel_id": None  # channel unknown after restart
                    }
                    log.info(f"  Restored {label} topic {topic_id} for {requester}")
        except Exception as e:
            log.error(f"Error restoring {label} topics: {e}")

# ============================================================
# Main Loop
# ============================================================

def main():
    log.info("PDH Forum LFG Bot v2 starting...")
    restore_active_topics()
    log.info(f"Monitoring every {POLL_INTERVAL_SECONDS} seconds. Active topics: {len(active_lfg_topics)}")

    while True:
        check_dm_channels()
        check_active_lfg_topics()
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
