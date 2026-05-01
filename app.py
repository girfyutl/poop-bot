from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
import os
import sqlite3
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]

handler = WebhookHandler(CHANNEL_SECRET)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

TZ = timezone(timedelta(hours=8))  # 台灣時間

def init_db():
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS poops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_poop(user_id):
    now = datetime.now(TZ).isoformat()
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute("INSERT INTO poops (user_id, created_at) VALUES (?, ?)", (user_id, now))
    conn.commit()
    conn.close()

def count_today(user_id):
    today = datetime.now(TZ).date().isoformat()
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM poops WHERE user_id = ? AND created_at LIKE ?",
        (user_id, today + "%")
    )
    count = c.fetchone()[0]
    conn.close()
    return count

def count_all():
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM poops")
    count = c.fetchone()[0]
    conn.close()
    return count

@app.route("/", methods=["GET"])
def home():
    return "Poop bot is running!"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    if text == "💩":
        init_db()
        add_poop(user_id)
        today_count = count_today(user_id)
        total_count = count_all()

        reply = f"已記錄 💩\n你今天第 {today_count} 坨\n群組總共 {total_count} 坨"

    elif text == "/總數":
        init_db()
        total_count = count_all()
        reply = f"目前總共 {total_count} 坨 💩"

    else:
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
