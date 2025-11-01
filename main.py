import os
import json
import requests
import discord
from discord.ext import commands, tasks
from keep_alive import keep_alive  # 👈 keeps Render service alive

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1433997173258715166"))
CLIENT_UID = os.getenv("CLIENT_UID", "154T-BFD91-4B8S")
UPDATE_MINUTES = int(os.getenv("UPDATE_MINUTES", "5"))

# Leaderboard identifiers
LEADERBOARD_UID = "1565-GC91E-MKCX"
EXPECTED_LB_NAME = "3dhaxxCpu"  # what SBX shows as name
FALLBACK_TITLE = "CPU Leaderboard"  # what you display in Discord

TRPC_URL = "https://www.sbx.com/api/trpc/referral.getPublicLeaderBoard"
# ===================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

leaderboard_message_id = None


# ===== FETCHING =====
def fetch_sbx_leaderboard():
    """
    Call SBX exactly like the page does, but only for the leaderboard.
    """
    payload = {
        "json": {
            "leaderboardUid": LEADERBOARD_UID,
            "filters": {
                "clientUid": CLIENT_UID,
                "sortBy": "wagered",
            },
        }
    }

    params = {"input": json.dumps(payload)}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.sbx.com/",
    }

    r = requests.get(TRPC_URL, params=params, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()

    if "result" in data and "data" in data["result"]:
        return data["result"]["data"]

    if isinstance(data, list) and len(data) > 0 and "result" in data[0]:
        return data[0]["result"]["data"]

    raise ValueError(f"Unexpected SBX response: {data}")


# ===== VALIDATION =====
def is_expected_leaderboard(lb_data):
    """
    Returns True only if the SBX response looks like *our* leaderboard.
    """
    if not isinstance(lb_data, dict):
        return False

    # unwrap if needed
    if "json" in lb_data and isinstance(lb_data["json"], dict):
        lb_data = lb_data["json"]

    name = lb_data.get("name") or lb_data.get("title") or ""
    uid = lb_data.get("leaderboardUid") or lb_data.get("uid") or ""

    if name.lower() == EXPECTED_LB_NAME.lower():
        return True
    if uid == LEADERBOARD_UID:
        return True

    return False


def has_enough_users(lb_data, min_users=2):
    """
    Optional safeguard to avoid posting empty/partial data.
    """
    if "json" in lb_data:
        lb_data = lb_data["json"]
    users = lb_data.get("users") or []
    return len(users) >= min_users


# ===== FORMAT =====
def format_leaderboard(lb_data, limit=10):
    """
    Your SBX response looks like:
    {
      "json": {
        "name": "3dhaxxCpu",
        "config": {"prizeSimple": [250, 150, ...]},
        "users": [...]
      }
    }
    """
    if isinstance(lb_data, dict) and "json" in lb_data:
        lb_data = lb_data["json"]

    title = FALLBACK_TITLE
    users = lb_data.get("users") or lb_data.get("entries") or lb_data.get("rankings") or []
    prizes = lb_data.get("config", {}).get("prizeSimple", [])

    lines = [f"**{title}** 🔁 (auto-updates)"]

    if not users:
        lines.append("_No entries found_")
        return "\n".join(lines)

    for i, user in enumerate(users[:limit], start=1):
        rank = user.get("position") or i
        name = user.get("username") or user.get("nickname") or "Unknown"
        wagered = user.get("totalWagered") or user.get("wagered") or user.get("amount") or 0

        try:
            wagered_txt = f"USD ${float(wagered):,.2f}"
        except (TypeError, ValueError):
            wagered_txt = str(wagered)

        prize_txt = ""
        if prizes and rank <= len(prizes):
            prize_amount = prizes[rank - 1]
            prize_txt = f" — prize: USD ${prize_amount}"

        lines.append(f"**{rank}. {name}** — wagered: {wagered_txt}{prize_txt}")

    return "\n".join(lines)


# ===== DISCORD EVENTS =====
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    update_leaderboard.start()


@bot.command(name="setlb")
async def setlb(ctx):
    global leaderboard_message_id
    lb_data = fetch_sbx_leaderboard()
    print("SBX RAW DATA:", lb_data)

    # Validate correct leaderboard
    if not is_expected_leaderboard(lb_data):
        await ctx.send("⚠️ Received data from a different leaderboard — update skipped.")
        return

    if not has_enough_users(lb_data):
        await ctx.send("⚠️ Leaderboard data incomplete — skipped this update.")
        return

    txt = format_leaderboard(lb_data)
    msg = await ctx.send(txt)
    leaderboard_message_id = msg.id
    await ctx.message.add_reaction("✅")


@tasks.loop(minutes=UPDATE_MINUTES)
async def update_leaderboard():
    global leaderboard_message_id
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        return

    try:
        lb_data = fetch_sbx_leaderboard()
    except Exception as e:
        await channel.send(f"⚠️ SBX update failed: `{e}`")
        return

    # Validate correct leaderboard
    if not is_expected_leaderboard(lb_data):
        print("⚠️ Skipped SBX update — wrong leaderboard returned")
        return

    if not has_enough_users(lb_data):
        print("⚠️ Skipped SBX update — not enough rows")
        return

    new_text = format_leaderboard(lb_data)

    if leaderboard_message_id is None:
        msg = await channel.send(new_text)
        leaderboard_message_id = msg.id
        return

    try:
        msg = await channel.fetch_message(leaderboard_message_id)
        await msg.edit(content=new_text)
    except discord.NotFound:
        msg = await channel.send(new_text)
        leaderboard_message_id = msg.id


@update_leaderboard.before_loop
async def before_update():
    await bot.wait_until_ready()


# ===== START BOT =====
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
