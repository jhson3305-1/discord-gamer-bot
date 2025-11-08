import os
import random
import logging

import discord
from discord.ext import commands
from discord import app_commands

from keepalive import keep_alive  # Render용 Flask keep-alive

logging.basicConfig(level=logging.INFO)

# ==============================
# 환경 변수 확인
# ==============================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID_RAW = os.getenv("GUILD_ID")

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN 환경 변수가 설정되지 않았습니다.")
    raise SystemExit(1)

if not GUILD_ID_RAW:
    print("❌ GUILD_ID 환경 변수가 설정되지 않았습니다.")
    raise SystemExit(1)

try:
    GUILD_ID = int(GUILD_ID_RAW)
except ValueError:
    print(f"❌ GUILD_ID 환경 변수 값이 올바르지 않습니다: {GUILD_ID_RAW}")
    raise SystemExit(1)

TEST_GUILD = discord.Object(id=GUILD_ID)

# ==============================
# 인텐트 & 봇 설정
# ==============================
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True  # 팀 분배용
# message_content 인텐트는 현재 필요 없음

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

COLOR_MAIN = discord.Color.blurple()
COLOR_SUCCESS = discord.Color.green()
COLOR_ALERT = discord.Color.red()


# ==============================
# 유틸 함수
# ==============================
def parse_csv(text: str):
    return [x.strip() for x in text.split(",") if x.strip()]


# ==============================
# 이벤트
# ==============================
@bot.event
async def on_ready():
    print(f"✅ 로그인 완료: {bot.user} (ID: {bot.user.id})")
    try:
        await tree.sync(guild=TEST_GUILD)
        print(f"✅ 슬래시 커맨드 동기화 완료 (Guild ID: {GUILD_ID})")
    except Exception as e:
        print(f"❌ 슬래시 커맨드 동기화 실패: {e}")


# ==============================
# /ping
# ==============================
@tree.command(name="ping", description="봇이 정상 작동 중인지 확인합니다.")
@app_commands.guilds(TEST_GUILD)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong! GamerToolBot 온라인입니다.", ephemeral=True)


# ==============================
# /help
# ==============================
@tree.command(name="help", description="GamerToolBot 기능 안내를 보여줍니다.")
@app_commands.guilds(TEST_GUILD)
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮 GamerToolBot 도움말",
        description="게임 커뮤니티를 위한 팀 관리 & 미니게임 봇",
        color=COLOR_MAIN,
    )
    embed.add_field(
        name="🎲 랜덤 / 미니게임",
        value=(
            "`/roulette` - 콤마(,)로 구분한 항목 중 랜덤 선택\n"
            "`/pinball` - 참가자들을 랜덤 순위로 섞기\n"
            "`/ladder` - 입력 순서와 섞인 순서를 매칭"
        ),
        inline=False,
    )
    embed.add_field(
        name="👥 팀 관련",
        value="`/team_split` - 현재 음성채널 인원을 팀으로 자동 분배",
        inline=False,
    )
    embed.set_footer(text="완전 무료 · 게임 서버 전용 유틸 봇")

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==============================
# /roulette
# ==============================
@tree.command(name="roulette", description="콤마(,)로 구분된 항목 중 하나를 무작위 선택합니다.")
@app_commands.describe(options="예: 치킨, 피자, 라면")
@app_commands.guilds(TEST_GUILD)
async def roulette(interaction: discord.Interaction, options: str):
    items = parse_csv(options)
    if len(items) < 2:
        await interaction.response.send_message("❗ 최소 2개 이상의 항목을 입력해주세요.", ephemeral=True)
        return

    choice = random.choice(items)
    embed = discord.Embed(
        title="🎯 룰렛 결과",
        description="옵션: " + ", ".join(f"`{x}`" for x in items) + f"\n\n👉 선택된 항목: **{choice}**",
        color=COLOR_MAIN,
    )
    await interaction.response.send_message(embed=embed)


# ==============================
# /pinball
# ==============================
@tree.command(name="pinball", description="핀볼 스타일로 무작위 순위를 생성합니다.")
@app_commands.describe(options="콤마(,)로 구분된 참가자 목록")
@app_commands.guilds(TEST_GUILD)
async def pinball(interaction: discord.Interaction, options: str):
    items = parse_csv(options)
    if len(items) < 2:
        await interaction.response.send_message("❗ 최소 2명 이상이 필요합니다.", ephemeral=True)
        return

    random.shuffle(items)
    lines = [f"{i+1}위: **{name}**" for i, name in enumerate(items)]
    embed = discord.Embed(
        title="🎳 핀볼 결과 (랜덤 순위)",
        description="\n".join(lines),
        color=COLOR_MAIN,
    )
    await interaction.response.send_message(embed=embed)


# ==============================
# /ladder
# ==============================
@tree.command(name="ladder", description="사다리 타기 스타일 매칭 (입력 순서 ➜ 섞인 순서)")
@app_commands.describe(options="콤마(,)로 구분된 항목들")
@app_commands.guilds(TEST_GUILD)
async def ladder(interaction: discord.Interaction, options: str):
    items = parse_csv(options)
    if len(items) < 2:
        await interaction.response.send_message("❗ 최소 2개 이상이 필요합니다.", ephemeral=True)
        return

    shuffled = items[:]
    random.shuffle(shuffled)
    lines = [f"`{a}` ➜ **{b}**" for a, b in zip(items, shuffled)]
    embed = discord.Embed(
        title="🪜 사다리 타기 결과",
        description="\n".join(lines),
        color=COLOR_MAIN,
    )
    await interaction.response.send_message(embed=embed)


# ==============================
# /team_split
# ==============================
@tree.command(name="team_split", description="현재 음성채널 인원을 지정한 팀 수로 나눕니다.")
@app_commands.describe(team_count="팀 수 (기본 2)")
@app_commands.guilds(TEST_GUILD)
async def team_split(interaction: discord.Interaction, team_count: int = 2):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❗ 먼저 음성 채널에 들어가주세요.", ephemeral=True)
        return

    if team_count < 2 or team_count > 10:
        await interaction.response.send_message("⚠️ 팀 수는 2~10 사이만 허용됩니다.", ephemeral=True)
        return

    channel = interaction.user.voice.channel
    members = [m for m in channel.members if not m.bot]

    if len(members) < team_count:
        await interaction.response.send_message("⚠️ 팀 수가 사람 수보다 많습니다.", ephemeral=True)
        return

    random.shuffle(members)
    teams = [members[i::team_count] for i in range(team_count)]

    desc = []
    for i, team in enumerate(teams, start=1):
        names = "\n".join(m.display_name for m in team)
        desc.append(f"**팀 {i}**\n{names}")

    embed = discord.Embed(
        title="👥 팀 분배 결과",
        description="\n\n".join(desc),
        color=COLOR_SUCCESS,
    )
    await interaction.response.send_message(embed=embed)


# ==============================
# 메인 실행
# ==============================
if __name__ == "__main__":
    keep_alive()  # Render용 포트 오픈 (Flask)
    bot.run(DISCORD_TOKEN)
