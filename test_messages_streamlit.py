import requests
import streamlit as st

API = "http://127.0.0.1:8006/api"

st.set_page_config(
    page_title="ConnectNow Message Test",
    layout="wide"
)

st.title("ConnectNow Messaging API Test")

# -----------------------------
# USER SELECT
# -----------------------------
user_map = {
    "Amit Desai": "USR_123",
    "Rahul Sharma": "USR_456"
}

selected_user = st.sidebar.selectbox(
    "Login as",
    list(user_map.keys())
)

current_user_id = user_map[selected_user]

if "token" not in st.session_state or st.session_state.get("current_user_id") != current_user_id:
    res = requests.get(
        f"{API}/auth/demo-token",
        params={"user": current_user_id}
    )

    if res.status_code != 200:
        st.error(res.text)
        st.stop()

    st.session_state.token = res.json()["token"]
    st.session_state.current_user_id = current_user_id

headers = {
    "Authorization": f"Bearer {st.session_state.token}",
    "Content-Type": "application/json"
}

st.sidebar.success(f"Logged in as {selected_user}")

# -----------------------------
# PRESENCE
# -----------------------------
if st.sidebar.button("Mark Online"):
    r = requests.post(f"{API}/presence/online", headers=headers)
    st.sidebar.write(r.json())

if st.sidebar.button("Mark Offline"):
    r = requests.post(f"{API}/presence/offline", headers=headers)
    st.sidebar.write(r.json())

# -----------------------------
# START CONVERSATION
# -----------------------------
st.sidebar.divider()

other_users = {
    name: uid
    for name, uid in user_map.items()
    if uid != current_user_id
}

selected_receiver = st.sidebar.selectbox(
    "Start chat with",
    list(other_users.keys())
)

receiver_id = other_users[selected_receiver]

if st.sidebar.button("Start / Open Conversation"):
    r = requests.post(
        f"{API}/conversations/start",
        headers=headers,
        json={"receiver_user_id": receiver_id}
    )

    if r.status_code != 200:
        st.sidebar.error(r.text)
    else:
        st.session_state.active_conversation = r.json()
        st.sidebar.success("Conversation opened")

# -----------------------------
# CONVERSATION LIST
# -----------------------------
st.subheader("My Conversations")

conv_res = requests.get(
    f"{API}/conversations/me",
    headers=headers
)

if conv_res.status_code != 200:
    st.error(conv_res.text)
    st.stop()

conversations = conv_res.json()

if not conversations:
    st.info("No conversations yet. Start one from sidebar.")
else:
    for conv in conversations:
        participant = conv["participant"]

        label = (
            f"{participant['name']} | "
            f"{'Online' if participant['is_online'] else 'Offline'} | "
            f"Unread: {conv['unread_count']}"
        )

        if st.button(label, key=conv["conversation_id"]):
            st.session_state.active_conversation = conv

# -----------------------------
# CHAT AREA
# -----------------------------
st.divider()

if "active_conversation" not in st.session_state:
    st.info("Select or start a conversation.")
    st.stop()

active = st.session_state.active_conversation
conv_id = active["conversation_id"]
participant = active["participant"]

st.subheader(f"Chat with {participant['name']}")

st.caption(
    f"Can help with: {participant.get('can_help_with') or 'Not added'} | "
    f"Status: {'Online' if participant.get('is_online') else 'Offline'}"
)

msg_res = requests.get(
    f"{API}/conversations/{conv_id}/messages",
    headers=headers
)

if msg_res.status_code != 200:
    st.error(msg_res.text)
    st.stop()

messages = msg_res.json()

for msg in messages:
    if msg["sender_user_id"] == current_user_id:
        st.chat_message("user").write(msg["message_text"])
    else:
        st.chat_message("assistant").write(msg["message_text"])

# Mark read
requests.put(
    f"{API}/conversations/{conv_id}/read",
    headers=headers
)

# -----------------------------
# SEND MESSAGE
# -----------------------------
message_text = st.chat_input("Type message...")

if message_text:
    send_res = requests.post(
        f"{API}/conversations/{conv_id}/messages",
        headers=headers,
        json={"message_text": message_text}
    )

    if send_res.status_code != 201:
        st.error(send_res.text)
    else:
        st.rerun()