import os
import json
import requests
import discord
from discord.ext import commands, tasks
from keep_alive import keep_alive  # 👈 this will keep Render/Replit awake

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1433997173258715166"))

TRPC_URL = "https://www.sbx.com/api/trpc/referral.getPublicLeaderBoard"
LEADERBOARD_UID = "1565-GC91E-MKCX"

# 👇 from your browser request
CLIENT_UID = os.getenv("CLIENT_UID", "154T-BFD91-4B8S")

UPDATE_MINUTES = int(os.getenv("UPDATE_MINUTES", "5"))
# ===================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

leaderboard_message_id = None


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


def format_leaderboard(lb_data, limit=10):
    """
    Your SBX response was:
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

    # hard-code your title like you wanted
    title = "CPU Leaderboard"

    users = (
        lb_data.get("users")
        or lb_data.get("entries")
        or lb_data.get("rankings")
        or []
    )

    prizes = []
    cfg = lb_data.get("config")
    if isinstance(cfg, dict):
        prizes = cfg.get("prizeSimple") or []

    lines = [f"**{title}** 🔁 (auto-updates)"]

    if not users:
        lines.append("_No entries found_")
        return "\n".join(lines)

    for i, user in enumerate(users[:limit], start=1):
        rank = user.get("position") or i
        name = user.get("username") or user.get("nickname") or "Unknown"
        wagered = (
            user.get("totalWagered")
            or user.get("wagered")
            or user.get("amount")
            or 0
        )

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


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    update_leaderboard.start()


@bot.command(name="setlb")
async def setlb(ctx):
    global leaderboard_message_id
    lb_data = fetch_sbx_leaderboard()
    print("SBX RAW DATA:", lb_data)
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
        new_text = format_leaderboard(lb_data)
    except Exception as e:
        await channel.send(f"⚠️ SBX update failed: `{e}`")
        return

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


if __name__ == "__main__":
    # start tiny web server
    from keep_alive import keep_alive
    keep_alive()
    bot.run(TOKEN)
