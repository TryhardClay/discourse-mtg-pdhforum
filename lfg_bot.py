#!/usr/bin/env python3
"""
PDH Forum LFG Bot
Repository: https://github.com/TryhardClay/discourse-mtg-pdhforum
Author: TryhardClay

===============================================================
VERSION HISTORY
===============================================================
v2.2.0 (2026-02-24)
  - Replaced individual DM loop with single group DM channel
    containing all matched players plus the bot account
  - Match notification now runs unconditionally regardless of
    Convoke outcome — Convoke result affects message content only
  - Baseline match message uses Convoke lobby link as fallback:
    https://convoke.games/en/lobby
  - Convoke API room creation stubbed out and disabled — will be
    re-enabled in a future session once group DM flow is confirmed
  - Expiry notifications also use group DM when multiple players
    are involved, individual DM when only the requester is present
  - create_group_dm() helper added to replace get_or_create_dm_channel()
    in match and expiry notification flows

v2.1.0 (2026-02-24)
  - Redesigned check_dm_channels for scalability:
      * Channels with unread_count == 0 are skipped entirely
      * New channels use last_message.id from channel list
        response to set last_seen baseline (no extra API call)
      * New channels with unread_count > 0 on first sight are
        processed immediately rather than skipped until next cycle
  - Restored correct unread guard using tracking.channel_tracking
    (was previously removed, causing excessive API calls)
  - Fixed get_poll_voters: removed invalid option_id="0" parameter
    (Discourse uses hashed option IDs, not sequential integers)
  - Fixed get_poll_voters: voters dict guarded with `or {}` to
    handle null response from Discourse on empty polls
  - Added channel_id None guard in Convoke error fallback to
    prevent crash on restored topics with unknown channel

v2.0.0 (2026-02-24)
  - Replaced traditional PM polling with Discourse chat API
  - Three-format routing: casual / comp / 1v1
  - Fixed chat send endpoint to POST /chat/{channel_id}
  - Bot startup skips pre-existing messages to prevent stale
    trigger responses on restart
  - Poll syntax: results=always, chartType=bar, no close= timer
  - Bot owns topic lifecycle via created_at timestamp tracking
    (LFG_EXPIRY_SECONDS = 3600) instead of poll close timer
  - poll_threshold split from seat_count: requester implicitly
    fills one seat, so poll needs seat_count - 1 votes to trigger
  - Simultaneous request handling: second requester for same
    format is pointed to existing active topic instead of
    creating a duplicate
  - On bot restart, active topics are restored with a fresh
    1-hour expiry window
  - Cycle time reduced from 30s to 5s (max 3 active topics)
  - All voters plus requester receive notifications via DM

===============================================================
TRIGGERS (send via DM to @PDHMatchmaker)
===============================================================
  casual -> Casual PDH LFG (4 players, poll needs 3 votes)
  comp   -> Competitive PDH LFG (4 players, poll needs 3 votes)
  1v1    -> 1v1 PDH LFG (2 players, poll needs 1 vote)
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

# Convoke API — stubbed out pending group DM confirmation
# CONVOKE_API_URL = "https://api.convoke.games/api/game/create-game"
# CONVOKE_API_KEY = "convk_6536e0adb4c407d49bfa7d4ee4d44c489dc147a6"

CONVOKE_LOBBY_URL = "https://convoke.games/en/lobby"

POLL_INTERVAL_SECONDS = 5
LFG_EXPIRY_SECONDS = 3600  # 1 hour

# LFG category config:
# trigger -> (category_id, seat_count, poll_threshold, convoke_format, label)
#
# seat_count     = total players for the Convoke room
# poll_threshold = votes needed to trigger a match (seat_count - 1,
#                  because the requester fills one seat implicitly)
LFG_FORMATS = {
    "casual": (36, 4, 3, "commander", "Casual PDH"),
    "comp":   (37, 4, 3, "commander", "Competitive PDH"),
    "1v1":    (35, 2, 1, "standard",  "1v1 PDH"),
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

def get_dm_channel_data():
    """
    Fetch all DM channels and tracking data for the bot account.
    Returns (channels list, channel_tracking dict).
    channel_tracking is keyed by string channel ID and contains unread_count.
    This is a single API call that provides everything needed to decide
    whether any given channel requires further attention.
    """
    data = discourse_get("/chat/api/me/channels")
    channels = data.get("direct_message_channels", [])
    channel_tracking = data.get("tracking", {}).get("channel_tracking", {})
    return channels, channel_tracking

def get_channel_messages(channel_id):
    """Fetch messages from a chat DM channel."""
    data = discourse_get(f"/chat/api/channels/{channel_id}/messages")
    return data.get("messages", [])

def send_chat_message(channel_id, message):
    """Send a message to a chat channel."""
    data = {"message": message}
    return discourse_post(f"/chat/{channel_id}", data)

def get_or_create_dm_channel(username):
    """Get or create a 1:1 DM channel with a specific user."""
    data = {"target_usernames": [username]}
    result = discourse_post("/chat/api/direct-messages", data)
    return result.get("channel", {}).get("id")

def create_group_dm(usernames):
    """
    Create a group DM channel containing all provided usernames.
    The bot account is included automatically as the API actor.
    Returns the channel ID or None on failure.
    usernames should be a list of Discourse username strings.
    """
    try:
        data = {"target_usernames": usernames}
        result = discourse_post("/chat/api/direct-messages", data)
        channel_id = result.get("channel", {}).get("id")
        if channel_id:
            log.info(f"Created group DM channel {channel_id} for: {usernames}")
        else:
            log.error(f"Group DM creation returned no channel ID for: {usernames}")
        return channel_id
    except Exception as e:
        log.error(f"Failed to create group DM for {usernames}: {e}")
        return None

# ============================================================
# Topic Helpers
# ============================================================

def create_lfg_topic(requester_username, format_key):
    """Create a Looking for Game topic for the given format."""
    category_id, seat_count, poll_threshold, _, label = LFG_FORMATS[format_key]

    title = f"Looking for a {label} Game — {requester_username}"

    if poll_threshold == 1:
        poll_line = "Vote below — 1 spot available!"
        seat_text = "Once a second player joins the poll, both players will receive a Convoke link via DM."
    else:
        poll_line = f"Vote below — {poll_threshold} spots available!"
        seat_text = f"Once all {poll_threshold} spots are filled, everyone will receive a Convoke link via DM."

    body = f"""@{requester_username} is looking for a {label} game on Convoke! {poll_line}

> ⏱ This post expires in 1 hour. {seat_text} If the poll doesn't fill in time, it will be removed automatically and all participants will be notified via DM. No Discord required.

**Format:** {label}
**Platform:** Convoke (webcam)

[poll type=regular results=always public=true chartType=bar]
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
    """Fetch poll voter count and status from a topic."""
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
    """
    Get usernames of all poll voters.
    option_id is intentionally omitted — Discourse uses hashed option IDs,
    not sequential integers. Omitting it returns all voters across all options.
    voters is guarded with `or {}` since Discourse may return null for empty polls.
    """
    try:
        data = discourse_get(
            "/polls/voters.json",
            params={
                "topic_id": topic_id,
                "post_id": post_id,
                "poll_name": "poll",
            }
        )
        voters = data.get("voters") or {}
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
# Bot State
# ============================================================

# channel_id -> last processed message id
# Only populated for channels that have had unread activity.
# Channels with no unread messages are never fetched.
processed_message_ids = {}

# topic_id -> {requester, format_key, channel_id, created_at}
active_lfg_topics = {}

# ============================================================
# Core Logic
# ============================================================

def get_active_topic_for_format(format_key):
    """Return the topic_id of an existing active topic for this format, or None."""
    for topic_id, info in active_lfg_topics.items():
        if info["format_key"] == format_key:
            return topic_id
    return None

def notify_match(all_players, label):
    """
    Send a match notification to all players via a single group DM.
    Creates a group DM channel containing all players.
    Convoke API room creation is stubbed — lobby link used as baseline.
    """
    msg = (
        f"✅ **Game found!** Your {label} game is ready.\n\n"
        f"Head to the Convoke lobby to set up your game:\n"
        f"**{CONVOKE_LOBBY_URL}**\n\n"
        f"Your fellow players: {', '.join(f'@{u}' for u in all_players)}\n\n"
        f"Good luck and have fun! No Discord required."
    )

    group_channel = create_group_dm(all_players)
    if group_channel:
        send_chat_message(group_channel, msg)
        log.info(f"Match notification sent to group DM {group_channel}: {all_players}")
    else:
        log.error(f"Failed to create group DM for match — players were: {all_players}")

def notify_expiry(all_players, label, voters, poll_threshold):
    """
    Send an expiry notification to all involved players.
    Uses a group DM if multiple players are present,
    individual DM if only the requester remains.
    """
    msg = (
        f"Unfortunately your {label} LFG post expired before it could fill "
        f"({voters}/{poll_threshold} additional players joined). "
        f"Feel free to try again anytime!"
    )

    if len(all_players) > 1:
        group_channel = create_group_dm(all_players)
        if group_channel:
            send_chat_message(group_channel, msg)
            log.info(f"Expiry notification sent to group DM for: {all_players}")
        else:
            log.error(f"Failed to create group DM for expiry — players were: {all_players}")
    else:
        # Only the requester — use individual DM
        try:
            dm_channel = get_or_create_dm_channel(all_players[0])
            if dm_channel:
                send_chat_message(dm_channel, msg)
                log.info(f"Expiry notification sent to {all_players[0]}")
        except Exception as e:
            log.error(f"Failed to notify {all_players[0]} of expiry: {e}")

def handle_lfg_request(channel_id, requester_username, format_key):
    """Create an LFG topic and confirm via chat DM, or point to existing topic."""
    _, _, _, _, label = LFG_FORMATS[format_key]
    log.info(f"LFG request from {requester_username} for {label} (channel {channel_id})")

    # Check if there's already an active topic for this format
    existing_topic_id = get_active_topic_for_format(format_key)
    if existing_topic_id:
        topic_url = f"{DISCOURSE_URL}/t/{existing_topic_id}"
        log.info(f"Active {label} topic already exists ({existing_topic_id}), pointing {requester_username} to it")
        send_chat_message(
            channel_id,
            f"There's already a {label} game looking for players! Head over and join the poll:\n\n"
            f"➡️ {topic_url}"
        )
        return

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
            "channel_id": channel_id,
            "created_at": time.time()
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
    """
    Check DM channels for new LFG trigger messages.

    Scalability design:
    - One API call per cycle fetches all channel data including unread counts.
    - Channels with unread_count == 0 are skipped with no further API calls.
    - New channels (never seen before) use last_message.id from the channel
      list response to set their last_seen baseline — no extra fetch needed.
    - New channels that already have unread_count > 0 on first sight are
      processed immediately rather than skipped until next cycle.
    - Result: idle state costs one API call per cycle regardless of user count.
      Active state costs one additional API call per channel with unread messages.
    """
    try:
        channels, channel_tracking = get_dm_channel_data()

        for channel in channels:
            channel_id = channel.get("id")
            unread = channel_tracking.get(str(channel_id), {}).get("unread_count", 0)

            if channel_id not in processed_message_ids:
                # New channel — set last_seen from last_message.id in channel list.
                # No extra API call needed.
                last_msg_id = channel.get("last_message", {}).get("id", 0)

                if unread == 0:
                    # No unread messages — just record the baseline and move on.
                    processed_message_ids[channel_id] = last_msg_id
                    log.info(f"Initialized channel {channel_id}, last message id: {last_msg_id}")
                    continue
                else:
                    # Unread messages on first sight — set baseline to one before
                    # the last message so we process the unread messages now.
                    # We fetch the full message list to get all unread content.
                    processed_message_ids[channel_id] = last_msg_id - unread
                    log.info(f"Initialized channel {channel_id} with {unread} unread messages")

            elif unread == 0:
                # Known channel, nothing new — skip entirely.
                continue

            # Fetch and process new messages for this channel.
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

                log.info(f"New message in channel {channel_id} from {sender}: {text!r}")

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
    now = time.time()

    for topic_id, info in list(active_lfg_topics.items()):
        requester = info["requester"]
        format_key = info["format_key"]
        created_at = info["created_at"]
        _, seat_count, poll_threshold, _, label = LFG_FORMATS[format_key]

        try:
            voters, is_closed, post_id, topic_data = get_poll_data(topic_id)

            if voters is None:
                stale_topics.append(topic_id)
                continue

            if voters >= poll_threshold:
                # Poll fulfilled — notify all players via group DM
                voter_usernames = get_poll_voters(topic_id, post_id) if post_id else []
                all_players = list(set(voter_usernames + [requester]))
                log.info(f"Match found! Topic {topic_id} ({label}): {all_players}")

                notify_match(all_players, label)

                try:
                    delete_topic(topic_id)
                    log.info(f"Deleted fulfilled LFG topic {topic_id}")
                except Exception as e:
                    log.error(f"Failed to delete topic {topic_id}: {e}")

                stale_topics.append(topic_id)

            elif now - created_at >= LFG_EXPIRY_SECONDS:
                # Topic has been alive for 1 hour without filling — expire it
                log.info(f"LFG topic {topic_id} expired with {voters}/{poll_threshold} poll votes")

                voter_usernames = get_poll_voters(topic_id, post_id) if post_id else []
                all_players = list(set(voter_usernames + [requester]))

                notify_expiry(all_players, label, voters, poll_threshold)

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
    """
    On startup, reload existing LFG topics into memory.
    Each restored topic receives a fresh 1-hour expiry window from
    restart time since the original creation time is not persisted.
    channel_id is unknown after restart and set to None.
    """
    log.info("Restoring active LFG topics from forum...")
    for format_key, (category_id, _, _, _, label) in LFG_FORMATS.items():
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
                        "channel_id": None,
                        "created_at": time.time()
                    }
                    log.info(f"  Restored {label} topic {topic_id} for {requester}")
        except Exception as e:
            log.error(f"Error restoring {label} topics: {e}")

# ============================================================
# Main Loop
# ============================================================

def main():
    log.info("PDH Forum LFG Bot v2.2.0 starting...")
    restore_active_topics()
    log.info(f"Monitoring every {POLL_INTERVAL_SECONDS} seconds. Active topics: {len(active_lfg_topics)}")

    while True:
        check_dm_channels()
        check_active_lfg_topics()
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
