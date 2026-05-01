from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi, Configuration, ApiClient,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
import os
import sqlite3
import random
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]

handler = WebhookHandler(CHANNEL_SECRET)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

TZ = timezone(timedelta(hours=8))


def init_db():
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS poops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            user_name TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_user_name(event):
    user_id = event.source.user_id

    try:
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)

            if hasattr(event.source, "group_id") and event.source.group_id:
                profile = api.get_group_member_profile(event.source.group_id, user_id)
            else:
                profile = api.get_profile(user_id)

            return profile.display_name
    except:
        return "神秘便士"


def add_poop(user_id, user_name):
    now = datetime.now(TZ).isoformat()
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO poops (user_id, user_name, created_at) VALUES (?, ?, ?)",
        (user_id, user_name, now)
    )
    conn.commit()
    conn.close()


def count_user_today(user_id):
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


def month_ranking():
    month = datetime.now(TZ).strftime("%Y-%m")
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute("""
        SELECT user_name, COUNT(*) as total
        FROM poops
        WHERE created_at LIKE ?
        GROUP BY user_id
        ORDER BY total DESC
    """, (month + "%",))
    rows = c.fetchall()
    conn.close()
    return rows


def week_champion():
    now = datetime.now(TZ)
    start = now - timedelta(days=now.weekday())
    start_text = start.date().isoformat()

    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute("""
        SELECT user_name, COUNT(*) as total
        FROM poops
        WHERE created_at >= ?
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT 1
    """, (start_text,))
    row = c.fetchone()
    conn.close()
    return row


def constipation_king():
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute("""
        SELECT user_name, MAX(created_at) as last_time
        FROM poops
        GROUP BY user_id
        ORDER BY last_time ASC
        LIMIT 1
    """)
    row = c.fetchone()
    conn.close()

    if not row:
        return None

    name, last_time = row
    last_date = datetime.fromisoformat(last_time).date()
    days = (datetime.now(TZ).date() - last_date).days
    return name, days


def daily_chart():
    month = datetime.now(TZ).strftime("%Y-%m")
    conn = sqlite3.connect("poop.db")
    c = conn.cursor()
    c.execute("""
        SELECT substr(created_at, 1, 10) as day, COUNT(*)
        FROM poops
        WHERE created_at LIKE ?
        GROUP BY day
        ORDER BY day
    """, (month + "%",))
    rows = c.fetchall()
    conn.close()
    return rows


def roast(today_count):
    roasts = [
        "腸胃很認真上班欸。",
        "這不是大便，這是每日任務。",
        "你是不是跟馬桶簽約了？",
        "尊重，今天又有產量。",
        "大便超人已為你記上一筆豐功偉業。",
        "這個頻率，馬桶應該認識你了。",
        "你今天的腸道 KPI 達標了。"
    ]

    if today_count >= 5:
        return "你今天第 5 坨以上了欸，人體印鈔機是吧？"
    elif today_count >= 3:
        return "今天有點高產，馬桶辛苦了。"
    else:
        return random.choice(roasts)


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
    init_db()

    text = event.message.text.strip()
    user_id = event.source.user_id
    user_name = get_user_name(event)

    reply = None

    if text == "💩":
        add_poop(user_id, user_name)
        today_count = count_user_today(user_id)

        reply = (
            f"已記錄 {user_name} 的 💩\n"
            f"今天第 {today_count} 坨\n\n"
            f"{roast(today_count)}"
        )

    elif text == "/排行":
        rows = month_ranking()

        if not rows:
            reply = "本月還沒有人大便。"
        else:
            month = datetime.now(TZ).month
            msg = f"🏆 {month}月大便排行榜\n\n"
            for i, (name, total) in enumerate(rows, start=1):
                msg += f"{i}. {name} - {total} 坨\n"
            reply = msg.strip()

    elif text == "/本週":
        row = week_champion()

        if not row:
            reply = "本週還沒有人大便。"
        else:
            name, total = row
            reply = f"👑 本週大便王：{name}\n本週已經 {total} 坨 💩"

    elif text == "/便秘":
        result = constipation_king()

        if not result:
            reply = "目前沒有紀錄，大家都還很神秘。"
        else:
            name, days = result
            if days == 0:
                reply = f"{name} 今天有大便，暫時安全。"
            else:
                reply = f"⚠️ {name} 已經 {days} 天沒大便了。"

    elif text == "/統計":
        rows = daily_chart()

        if not rows:
            reply = "本月還沒有統計資料。"
        else:
            msg = "📊 本月每日大便統計\n\n"
            for day, total in rows:
                bar = "💩" * min(total, 10)
                msg += f"{day[5:]}：{bar} {total}\n"
            reply = msg.strip()

    elif text == "/說明":
        reply = (
            "大便超人指令表 💩\n\n"
            "傳 💩：記錄一次\n"
            "/排行：本月排行榜\n"
            "/本週：本週冠軍\n"
            "/便秘：誰最久沒大\n"
            "/統計：每日統計圖"
        )

    else:
        return

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
