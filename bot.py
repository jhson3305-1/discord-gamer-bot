import discord
from discord import app_commands
import asyncio
import random
import time
import logging
from typing import Dict, List
import os

# =========================
# 기본 설정
# =========================

logging.basicConfig(level=logging.INFO)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# GUILD_ID도 환경 변수로 빼도 되고, 그냥 숫자로 고정해도 됨
GUILD_ID = int(os.getenv("GUILD_ID", "1436425761656668284"))
TEST_GUILD = discord.Object(id=GUILD_ID)

intents = discord.Intents.default()
intents.voice_states = True  # 음성 채널 기능용 (특권 아님)


# =========================
# Bot 클래스
# =========================

class GamerToolBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        # 포인트 시스템: guild_id -> {user_id -> points}
        self.points: Dict[int, Dict[int, int]] = {}

        # VC 활동 기록: guild_id -> {user_id -> total_seconds}
        self.vc_time: Dict[int, Dict[int, float]] = {}
        # VC 입장 시각: guild_id -> {user_id -> join_timestamp}
        self.vc_join: Dict[int, Dict[int, float]] = {}

        # 토너먼트: guild_id -> tournament_data
        self.tournaments: Dict[int, Dict] = {}

        # 스케줄 이벤트: guild_id -> {event_id -> data}
        self.scheduled_events: Dict[int, Dict[int, Dict]] = {}
        # 이벤트 task: guild_id -> {event_id -> task}
        self.event_tasks: Dict[int, Dict[int, asyncio.Task]] = {}
        self.next_event_id = 1

    async def setup_hook(self):
        # 글로벌로 정의한 커맨드를 TEST_GUILD용으로 복사 후, 그 길드에만 동기화
        self.tree.copy_global_to(guild=TEST_GUILD)
        await self.tree.sync(guild=TEST_GUILD)
        print(f"✅ 슬래시 커맨드 동기화 완료 (Guild ID: {GUILD_ID})")

    # ---------- 포인트 ----------

    def add_points(self, guild_id: int, user_id: int, amount: int):
        if guild_id not in self.points:
            self.points[guild_id] = {}
        self.points[guild_id][user_id] = self.points[guild_id].get(user_id, 0) + amount

    # ---------- VC 기록 ----------

    def _ensure_vc_maps(self, guild_id: int):
        if guild_id not in self.vc_time:
            self.vc_time[guild_id] = {}
        if guild_id not in self.vc_join:
            self.vc_join[guild_id] = {}

    def record_vc_join(self, member: discord.Member):
        gid = member.guild.id
        self._ensure_vc_maps(gid)
        self.vc_join[gid][member.id] = time.time()

    def record_vc_leave(self, member: discord.Member):
        gid = member.guild.id
        self._ensure_vc_maps(gid)
        start = self.vc_join[gid].pop(member.id, None)
        if start is not None:
            duration = time.time() - start
            self.vc_time[gid][member.id] = self.vc_time[gid].get(member.id, 0) + duration

    # ---------- 스케줄 이벤트 ----------

    async def run_scheduled_event(self, guild_id: int, event_id: int):
        """간단한 자동 룰렛 이벤트 실행 루프"""
        while True:
            await asyncio.sleep(1)
            guild_events = self.scheduled_events.get(guild_id, {})
            data = guild_events.get(event_id)
            if not data or not data.get("active"):
                break

            now = time.time()
            if now >= data["next_run"]:
                channel = self.get_channel(data["channel_id"])
                if channel:
                    choice = random.choice(data["options"])
                    opts_str = " / ".join(f"`{o}`" for o in data["options"])
                    embed = discord.Embed(
                        title=f"🎲 정기 이벤트 룰렛 - {data['name']}",
                        description=f"{opts_str}\n\n👉 **{choice}**",
                        color=discord.Color.blurple()
                    )
                    await channel.send(embed=embed)
                data["next_run"] = now + data["interval"]

    def start_event_task(self, guild_id: int, event_id: int):
        if guild_id not in self.event_tasks:
            self.event_tasks[guild_id] = {}
        task = asyncio.create_task(self.run_scheduled_event(guild_id, event_id))
        self.event_tasks[guild_id][event_id] = task


bot = GamerToolBot()

COLOR_MAIN = discord.Color.blurple()
COLOR_SUCCESS = discord.Color.green()
COLOR_ALERT = discord.Color.red()
COLOR_ALT = discord.Color.orange()


# =========================
# 이벤트 핸들러
# =========================

@bot.event
async def on_ready():
    print(f"✅ 로그인 완료: {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_voice_state_update(member: discord.Member,
                                before: discord.VoiceState,
                                after: discord.VoiceState):
    if member.bot:
        return

    if before.channel is None and after.channel is not None:
        bot.record_vc_join(member)
    elif before.channel is not None and after.channel is None:
        bot.record_vc_leave(member)
    # 채널 이동은 단순화


# =========================
# 공통: 관리자 체크
# =========================

def is_admin_or_mod(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild


# =========================
# 0. /ping
# =========================

@bot.tree.command(name="ping", description="봇 상태를 확인합니다.")
async def ping(interaction: discord.Interaction):
    try:
        await interaction.response.send_message("🏓 Pong!", ephemeral=True)
    except Exception as e:
        print("PING ERROR:", repr(e))


# =========================
# 1. 게임 유틸
# =========================

# 1-1. /roulette

@bot.tree.command(name="roulette", description="여러 후보 중 하나를 랜덤으로 선택합니다.")
@app_commands.describe(options="쉼표(,)로 구분 (예: 치킨, 피자, 라면)")
async def roulette(interaction: discord.Interaction, options: str):
    items = [o.strip() for o in options.split(",") if o.strip()]
    if len(items) < 2:
        await interaction.response.send_message("❗ 최소 2개 이상 입력해주세요.", ephemeral=True)
        return

    choice = random.choice(items)
    options_list = "\n".join(
        f"{'👉 ' if o == choice else ''}`{o}`"
        for o in items
    )

    embed = discord.Embed(
        title="🎰 룰렛 결과",
        description="입력한 항목들 중에서 하나를 랜덤으로 선택했습니다.",
        color=COLOR_MAIN
    )
    embed.add_field(name="후보 목록", value=options_list, inline=False)
    embed.add_field(name="✅ 최종 당첨", value=f"**{choice}**", inline=False)
    await interaction.response.send_message(embed=embed)


# 1-2. /roulette_anim

@bot.tree.command(name="roulette_anim", description="애니메이션 연출로 룰렛을 굴립니다.")
@app_commands.describe(options="쉼표(,)로 구분")
async def roulette_anim(interaction: discord.Interaction, options: str):
    items = [o.strip() for o in options.split(",") if o.strip()]
    if len(items) < 2:
        await interaction.response.send_message("❗ 최소 2개 이상 입력해주세요.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🎰 룰렛 굴리는 중...",
        description="돌아가는 중입니다...",
        color=COLOR_ALT
    )
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()

    pointer_index = 0
    rounds = len(items) * 2 + random.randint(3, 6)

    for i in range(rounds):
        pointer_index = (pointer_index + 1) % len(items)
        lines = []
        for idx, name in enumerate(items):
            if idx == pointer_index:
                lines.append(f"👉 **{name}**")
            else:
                lines.append(f"・{name}")
        frame = discord.Embed(
            title="🎰 룰렛 굴리는 중...",
            description="\n".join(lines),
            color=COLOR_ALT
        )
        await msg.edit(embed=frame)
        await asyncio.sleep(0.12 + (i * 0.01))

    choice = items[pointer_index]
    lines = []
    for idx, name in enumerate(items):
        if idx == pointer_index:
            lines.append(f"✅ **{name}** (당첨!)")
        else:
            lines.append(f"・{name}")

    result = discord.Embed(
        title="🎉 룰렛 결과",
        description="\n".join(lines),
        color=COLOR_SUCCESS
    )
    await msg.edit(embed=result)


# 1-3. /pinball (동시 낙하, 순위)

@bot.tree.command(
    name="pinball",
    description="여러 후보(공)를 동시에 떨어뜨려 도착 순서대로 순위를 정합니다."
)
@app_commands.describe(options="쉼표(,)로 구분")
async def pinball(interaction: discord.Interaction, options: str):
    items = [o.strip() for o in options.split(",") if o.strip()]
    n = len(items)

    if n < 2:
        await interaction.response.send_message("❗ 최소 2개 이상 입력해주세요.", ephemeral=True)
        return

    circled_nums = [
        "①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩",
        "⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳"
    ]
    balls = [circled_nums[i] if i < len(circled_nums) else str(i + 1) for i in range(n)]

    max_height = max(6, min(12, n + 3))
    heights = [max_height] * n
    finished_order: List[int] = []
    max_frames = 50

    mapping_text = "\n".join(f"{balls[i]} : `{items[i]}`" for i in range(n))

    intro = discord.Embed(
        title="🕹 핀볼 시작!",
        description="각 후보가 공이 되어 동시에 떨어집니다.\n아래 슬롯(🟦)에 먼저 도착하는 순서대로 순위를 매깁니다.",
        color=COLOR_ALT
    )
    intro.add_field(name="공 매핑", value=mapping_text, inline=False)
    await interaction.response.send_message(embed=intro)
    msg = await interaction.original_response()

    frame = 0
    last_board_str = ""

    while len(finished_order) < n and frame < max_frames:
        frame += 1

        for i in range(n):
            if i in finished_order:
                continue
            if heights[i] > 0:
                step = random.choice([0, 1])
                heights[i] = max(0, heights[i] - step)
                if heights[i] == 0:
                    finished_order.append(i)

        lines = []
        for h in range(max_height, 0, -1):
            row_cells = []
            for i in range(n):
                if heights[i] == h and i not in finished_order:
                    sym = balls[i]
                else:
                    sym = "·"
                row_cells.append(f"{sym} ")
            lines.append("".join(row_cells))
        slot_row = "🟦 " * n
        lines.append(slot_row)

        board_str = "\n".join(lines)
        last_board_str = board_str

        if finished_order:
            preview = " → ".join(balls[i] for i in finished_order)
            desc = f"```{board_str}```\n도착 순서(진행 중): {preview}"
        else:
            desc = f"```{board_str}```\n도착 대기 중..."

        embed = discord.Embed(
            title="🕹 핀볼 진행 중...",
            description=desc,
            color=COLOR_ALT
        )
        embed.add_field(name="공 매핑", value=mapping_text, inline=False)
        await msg.edit(embed=embed)
        await asyncio.sleep(0.18)

    if len(finished_order) < n:
        remaining = [i for i in range(n) if i not in finished_order]
        finished_order.extend(remaining)

    ranking_lines = []
    for rank, idx in enumerate(finished_order, start=1):
        ranking_lines.append(f"{rank}위 : {balls[idx]} → `{items[idx]}`")

    result = discord.Embed(
        title="🏁 핀볼 최종 결과",
        color=COLOR_SUCCESS
    )
    result.add_field(
        name="최종 보드",
        value=f"```{last_board_str}```",
        inline=False
    )
    result.add_field(
        name="공 매핑",
        value=mapping_text,
        inline=False
    )
    result.add_field(
        name="도착 순서 (순위)",
        value="\n".join(ranking_lines),
        inline=False
    )
    await msg.edit(embed=result)


# 1-4. /ladder

@bot.tree.command(
    name="ladder",
    description="플레이어를 결과에 무작위로 매칭합니다."
)
@app_commands.describe(
    players="쉼표로 구분된 이름들",
    results="쉼표로 구분된 결과들 (개수 동일)"
)
async def ladder(interaction: discord.Interaction, players: str, results: str):
    ps = [p.strip() for p in players.split(",") if p.strip()]
    rs = [r.strip() for r in results.split(",") if r.strip()]

    if not ps or not rs:
        await interaction.response.send_message("❗ 플레이어와 결과를 모두 입력해주세요.", ephemeral=True)
        return
    if len(ps) != len(rs):
        await interaction.response.send_message(
            f"❗ 인원 수와 결과 수가 같아야 합니다. ({len(ps)} vs {len(rs)})",
            ephemeral=True
        )
        return

    shuffled = rs[:]
    random.shuffle(shuffled)

    lines = [f"**{p}** 👉 `{r}`" for p, r in zip(ps, shuffled)]

    embed = discord.Embed(
        title="🪜 사다리 매칭 결과",
        description="\n".join(lines),
        color=COLOR_MAIN
    )
    await interaction.response.send_message(embed=embed)


# 1-5. /team_split

@bot.tree.command(
    name="team_split",
    description="현재 음성채널 인원을 랜덤으로 팀에 나눕니다."
)
@app_commands.describe(team_count="팀 개수 (기본 2)")
async def team_split(interaction: discord.Interaction, team_count: int = 2):
    if team_count < 2:
        await interaction.response.send_message("❗ 팀 수는 최소 2개 이상입니다.", ephemeral=True)
        return

    vs = interaction.user.voice
    if not vs or not vs.channel:
        await interaction.response.send_message("❗ 먼저 음성 채널에 들어가주세요.", ephemeral=True)
        return

    members = [m for m in vs.channel.members if not m.bot]
    if len(members) < team_count:
        await interaction.response.send_message(
            f"❗ 팀 수({team_count})보다 인원이 적습니다. ({len(members)}명)",
            ephemeral=True
        )
        return

    random.shuffle(members)
    teams = [[] for _ in range(team_count)]
    for i, m in enumerate(members):
        teams[i % team_count].append(m)

    embed = discord.Embed(
        title=f"🎲 팀 랜덤 분배 - {vs.channel.name}",
        description=f"총 {len(members)}명 / {team_count}팀",
        color=COLOR_MAIN
    )
    for i, team in enumerate(teams, start=1):
        val = "\n".join(m.mention for m in team) if team else "인원 없음"
        embed.add_field(name=f"팀 {i}", value=val, inline=True)

    await interaction.response.send_message(embed=embed)


# 1-6. /captain_draft

@bot.tree.command(
    name="captain_draft",
    description="캡틴을 뽑고 드래프트 방식으로 팀을 나눕니다."
)
@app_commands.describe(team_count="팀/캡틴 수 (기본 2)")
async def captain_draft(interaction: discord.Interaction, team_count: int = 2):
    if team_count < 2:
        await interaction.response.send_message("❗ 팀 수는 최소 2 이상입니다.", ephemeral=True)
        return

    vs = interaction.user.voice
    if not vs or not vs.channel:
        await interaction.response.send_message("❗ 먼저 음성 채널에 들어가주세요.", ephemeral=True)
        return

    members = [m for m in vs.channel.members if not m.bot]
    if len(members) < team_count * 2:
        await interaction.response.send_message(
            f"❗ 한 팀당 최소 2명 필요합니다. (필요 {team_count*2}, 현재 {len(members)})",
            ephemeral=True
        )
        return

    random.shuffle(members)
    captains = members[:team_count]
    pool = members[team_count:]

    teams = [[c] for c in captains]
    direction = 1
    idx = 0
    for p in pool:
        teams[idx].append(p)
        idx += direction
        if idx >= team_count:
            idx = team_count - 1
            direction = -1
        elif idx < 0:
            idx = 0
            direction = 1

    embed = discord.Embed(
        title=f"🏅 주장 드래프트 결과 - {vs.channel.name}",
        description="스네이크 드래프트 방식으로 팀을 구성했습니다.",
        color=COLOR_SUCCESS
    )
    embed.add_field(
        name="캡틴 목록",
        value="\n".join(c.mention for c in captains),
        inline=False
    )
    for i, team in enumerate(teams, start=1):
        captain = team[0]
        mem_txt = "\n".join(m.mention for m in team[1:]) if len(team) > 1 else "팀원 없음"
        embed.add_field(
            name=f"팀 {i} (캡틴: {captain.display_name})",
            value=mem_txt,
            inline=True
        )

    await interaction.response.send_message(embed=embed)


# =========================
# 2. /auto_teams
# =========================

@bot.tree.command(
    name="auto_teams",
    description="현재 음성 채널 인원을 팀 채널로 자동 분배합니다."
)
@app_commands.describe(team_size="팀당 인원 수 (예: 5)")
async def auto_teams(interaction: discord.Interaction, team_size: int):
    if team_size < 1:
        await interaction.response.send_message("❗ 팀당 인원은 1 이상이어야 합니다.", ephemeral=True)
        return

    vs = interaction.user.voice
    if not vs or not vs.channel:
        await interaction.response.send_message("❗ 먼저 음성 채널에 들어가주세요.", ephemeral=True)
        return

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("길드를 찾을 수 없습니다.", ephemeral=True)
        return

    members = [m for m in vs.channel.members if not m.bot]
    if not members:
        await interaction.response.send_message("❗ 이동할 인원이 없습니다.", ephemeral=True)
        return

    from math import ceil
    team_count = ceil(len(members) / team_size)

    me = guild.me
    if not me or not me.guild_permissions.manage_channels or not me.guild_permissions.move_members:
        await interaction.response.send_message(
            "❗ 제가 `채널 관리`와 `멤버 이동` 권한을 가지고 있어야 합니다.",
            ephemeral=True
        )
        return

    category = vs.channel.category
    new_channels = []
    for i in range(1, team_count + 1):
        ch = await guild.create_voice_channel(
            name=f"팀 {i}",
            category=category
        )
        new_channels.append(ch)

    random.shuffle(members)
    for idx, m in enumerate(members):
        target_ch = new_channels[idx % team_count]
        try:
            await m.move_to(target_ch)
        except Exception as e:
            print("MOVE ERROR:", m, e)

    embed = discord.Embed(
        title="🧩 자동 팀 채널 분배 완료",
        description=f"{len(members)}명을 {team_count}개 팀 채널로 분배했습니다.",
        color=COLOR_MAIN
    )
    for i, ch in enumerate(new_channels, start=1):
        embed.add_field(name=f"팀 {i}", value=ch.mention, inline=True)

    await interaction.response.send_message(embed=embed)


# =========================
# 3. 포인트 & 랭킹
# =========================

@bot.tree.command(
    name="points_add",
    description="특정 유저에게 포인트를 추가합니다. (관리자 전용)"
)
@app_commands.describe(user="대상 유저", amount="추가할 포인트")
async def points_add(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin_or_mod(interaction.user):
        await interaction.response.send_message("❗ 관리자만 사용 가능합니다.", ephemeral=True)
        return

    if amount == 0:
        await interaction.response.send_message("0은 의미가 없습니다.", ephemeral=True)
        return

    gid = interaction.guild.id  # type: ignore
    bot.add_points(gid, user.id, amount)
    total = bot.points[gid][user.id]
    await interaction.response.send_message(
        f"✅ {user.mention} 님에게 `{amount}` 포인트 부여 (총 {total}점)",
        ephemeral=True
    )


@bot.tree.command(name="points_me", description="내 포인트를 확인합니다.")
async def points_me(interaction: discord.Interaction):
    gid = interaction.guild.id  # type: ignore
    point = bot.points.get(gid, {}).get(interaction.user.id, 0)
    await interaction.response.send_message(
        f"🎯 현재 포인트: **{point}점**",
        ephemeral=True
    )


@bot.tree.command(
    name="leaderboard",
    description="포인트 랭킹 TOP10을 표시합니다."
)
async def leaderboard(interaction: discord.Interaction):
    gid = interaction.guild.id  # type: ignore
    data = bot.points.get(gid, {})
    if not data:
        await interaction.response.send_message("아직 포인트 데이터가 없습니다.", ephemeral=True)
        return

    sorted_users = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = []
    for rank, (uid, pt) in enumerate(sorted_users, start=1):
        member = interaction.guild.get_member(uid)  # type: ignore
        name = member.display_name if member else f"User {uid}"
        lines.append(f"{rank}위: **{name}** - `{pt}`점")

    embed = discord.Embed(
        title="🏆 포인트 랭킹 TOP 10",
        description="\n".join(lines),
        color=COLOR_SUCCESS
    )
    await interaction.response.send_message(embed=embed)


# =========================
# 4. VC 활동 랭킹
# =========================

@bot.tree.command(
    name="vc_rank",
    description="음성채널 활동 시간 랭킹 TOP10을 보여줍니다."
)
async def vc_rank(interaction: discord.Interaction):
    gid = interaction.guild.id  # type: ignore
    data = dict(bot.vc_time.get(gid, {}))

    now = time.time()
    for uid, start in bot.vc_join.get(gid, {}).items():
        data[uid] = data.get(uid, 0) + (now - start)

    if not data:
        await interaction.response.send_message("아직 기록된 VC 활동 데이터가 없습니다.", ephemeral=True)
        return

    sorted_users = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = []
    for rank, (uid, sec) in enumerate(sorted_users, start=1):
        member = interaction.guild.get_member(uid)  # type: ignore
        name = member.display_name if member else f"User {uid}"
        hours = sec / 3600
        lines.append(f"{rank}위: **{name}** - `{hours:.1f}시간`")

    embed = discord.Embed(
        title="📊 VC 활동 시간 랭킹 TOP 10",
        description="\n".join(lines),
        color=COLOR_MAIN
    )
    await interaction.response.send_message(embed=embed)


# =========================
# 5. 토너먼트 (싱글 엘리미네이션)
# =========================

def build_tournament_embed(guild: discord.Guild, t: Dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 토너먼트: {t['name']}",
        color=COLOR_MAIN
    )
    rounds: Dict[int, List[str]] = {}
    for mid, m in t["matches"].items():
        r = m["round"]
        if r not in rounds:
            rounds[r] = []
        status = "❔"
        if m["winner"] is not None:
            status = f"✅ ({m['winner']})"
        rounds[r].append(f"#{mid}: {m['team1']} vs {m['team2']} {status}")

    for r in sorted(rounds.keys()):
        embed.add_field(
            name=f"{r} 라운드",
            value="\n".join(rounds[r]),
            inline=False
        )

    if t.get("next_round_seed"):
        embed.add_field(
            name="다음 라운드 시드(부전승 포함)",
            value=", ".join(t["next_round_seed"]),
            inline=False
        )

    if t["active"]:
        embed.set_footer(text="승자를 입력하려면 /tournament_result 사용")
    else:
        embed.set_footer(text="토너먼트 종료")
    return embed


@bot.tree.command(
    name="tournament_create",
    description="싱글 엘리미네이션 토너먼트를 생성합니다."
)
@app_commands.describe(
    name="토너먼트 이름",
    participants="참가 팀/유저 이름들 (쉼표, 2~16개)"
)
async def tournament_create(interaction: discord.Interaction, name: str, participants: str):
    if not is_admin_or_mod(interaction.user):
        await interaction.response.send_message("❗ 관리자만 사용 가능합니다.", ephemeral=True)
        return

    parts = [p.strip() for p in participants.split(",") if p.strip()]
    if len(parts) < 2 or len(parts) > 16:
        await interaction.response.send_message("❗ 참가자는 2~16개여야 합니다.", ephemeral=True)
        return

    gid = interaction.guild.id  # type: ignore
    if gid in bot.tournaments and bot.tournaments[gid].get("active"):
        await interaction.response.send_message(
            "❗ 이미 진행 중인 토너먼트가 있습니다. /tournament_end 후 다시 생성하세요.",
            ephemeral=True
        )
        return

    random.shuffle(parts)

    matches = {}
    match_id = 1
    current_round = 1
    next_round_seed: List[str] = []

    queue = parts[:]
    while len(queue) > 1:
        t1 = queue.pop(0)
        t2 = queue.pop(0)
        matches[match_id] = {"round": current_round, "team1": t1, "team2": t2, "winner": None}
        match_id += 1
    if queue:
        next_round_seed.append(queue.pop(0))

    bot.tournaments[gid] = {
        "name": name,
        "active": True,
        "matches": matches,
        "current_round": current_round,
        "next_match_id": match_id,
        "next_round_seed": next_round_seed
    }

    await interaction.response.send_message(
        embed=build_tournament_embed(interaction.guild, bot.tournaments[gid]),
        ephemeral=False
    )


@bot.tree.command(
    name="tournament_result",
    description="특정 경기의 승자를 기록하고 다음 라운드를 진행합니다."
)
@app_commands.describe(
    match_id="경기 번호 (# 제외 숫자)",
    winner="승자 이름 (해당 경기의 팀 이름과 일치해야 함)"
)
async def tournament_result(interaction: discord.Interaction, match_id: int, winner: str):
    if not is_admin_or_mod(interaction.user):
        await interaction.response.send_message("❗ 관리자만 사용 가능합니다.", ephemeral=True)
        return

    gid = interaction.guild.id  # type: ignore
    t = bot.tournaments.get(gid)
    if not t or not t.get("active"):
        await interaction.response.send_message("진행 중인 토너먼트가 없습니다.", ephemeral=True)
        return

    m = t["matches"].get(match_id)
    if not m:
        await interaction.response.send_message("해당 경기 ID를 찾을 수 없습니다.", ephemeral=True)
        return
    if m["winner"] is not None:
        await interaction.response.send_message("이미 승자가 기록된 경기입니다.", ephemeral=True)
        return
    if winner not in (m["team1"], m["team2"]):
        await interaction.response.send_message(
            f"승자는 `{m['team1']}` 또는 `{m['team2']}` 이어야 합니다.",
            ephemeral=True
        )
        return

    m["winner"] = winner

    current_round = t["current_round"]
    round_matches = [mm for mm in t["matches"].values() if mm["round"] == current_round]
    if all(mm["winner"] is not None for mm in round_matches):
        winners = [mm["winner"] for mm in round_matches]
        winners += t.get("next_round_seed", [])
        t["next_round_seed"] = []

        if len(winners) == 1:
            t["active"] = False
            champion = winners[0]
            embed = build_tournament_embed(interaction.guild, t)
            embed.add_field(name="🏆 우승", value=f"**{champion}**", inline=False)
            await interaction.response.send_message(embed=embed)
            return
        else:
            t["current_round"] += 1
            nr = t["current_round"]
            random.shuffle(winners)
            queue = winners[:]
            while len(queue) > 1:
                t1 = queue.pop(0)
                t2 = queue.pop(0)
                mid = t["next_match_id"]
                t["matches"][mid] = {"round": nr, "team1": t1, "team2": t2, "winner": None}
                t["next_match_id"] += 1
            if queue:
                t["next_round_seed"].append(queue.pop(0))

    await interaction.response.send_message(
        embed=build_tournament_embed(interaction.guild, t),
        ephemeral=False
    )


@bot.tree.command(
    name="tournament_view",
    description="현재 토너먼트 상태를 보여줍니다."
)
async def tournament_view(interaction: discord.Interaction):
    gid = interaction.guild.id  # type: ignore
    t = bot.tournaments.get(gid)
    if not t:
        await interaction.response.send_message("현재 등록된 토너먼트가 없습니다.", ephemeral=True)
        return
    await interaction.response.send_message(
        embed=build_tournament_embed(interaction.guild, t),
        ephemeral=False
    )


@bot.tree.command(
    name="tournament_end",
    description="진행 중인 토너먼트를 종료합니다. (관리자)"
)
async def tournament_end(interaction: discord.Interaction):
    if not is_admin_or_mod(interaction.user):
        await interaction.response.send_message("❗ 관리자만 사용 가능합니다.", ephemeral=True)
        return
    gid = interaction.guild.id  # type: ignore
    t = bot.tournaments.get(gid)
    if not t or not t.get("active"):
        await interaction.response.send_message("진행 중인 토너먼트가 없습니다.", ephemeral=True)
        return
    t["active"] = False
    await interaction.response.send_message("✅ 토너먼트를 종료했습니다.", ephemeral=True)


# =========================
# 6. 스케줄 이벤트 (자동 룰렛)
# =========================

@bot.tree.command(
    name="event_create_roulette",
    description="정해진 주기로 자동 룰렛 이벤트를 실행합니다. (관리자)"
)
@app_commands.describe(
    name="이벤트 이름",
    interval_minutes="실행 주기 (분 단위, 최소 5)",
    options="룰렛 후보들 (쉼표로 구분)"
)
async def event_create_roulette(
    interaction: discord.Interaction,
    name: str,
    interval_minutes: int,
    options: str
):
    if not is_admin_or_mod(interaction.user):
        await interaction.response.send_message("❗ 관리자만 사용 가능합니다.", ephemeral=True)
        return

    if interval_minutes < 5:
        await interaction.response.send_message("❗ 최소 5분 이상으로 설정해주세요.", ephemeral=True)
        return

    items = [o.strip() for o in options.split(",") if o.strip()]
    if len(items) < 2:
        await interaction.response.send_message("❗ 최소 2개 이상 입력해주세요.", ephemeral=True)
        return

    gid = interaction.guild.id  # type: ignore
    if gid not in bot.scheduled_events:
        bot.scheduled_events[gid] = {}

    event_id = bot.next_event_id
    bot.next_event_id += 1

    bot.scheduled_events[gid][event_id] = {
        "name": name,
        "type": "roulette",
        "channel_id": interaction.channel.id,
        "interval": interval_minutes * 60,
        "options": items,
        "active": True,
        "next_run": time.time() + interval_minutes * 60
    }

    bot.start_event_task(gid, event_id)

    await interaction.response.send_message(
        f"✅ 이벤트 생성 완료! (ID: {event_id}, {interval_minutes}분마다 실행)",
        ephemeral=True
    )


@bot.tree.command(
    name="event_list",
    description="등록된 자동 이벤트 목록을 보여줍니다."
)
async def event_list(interaction: discord.Interaction):
    gid = interaction.guild.id  # type: ignore
    events = bot.scheduled_events.get(gid, {})
    if not events:
        await interaction.response.send_message("등록된 이벤트가 없습니다.", ephemeral=True)
        return

    lines = []
    for eid, ev in events.items():
        status = "ON" if ev.get("active") else "OFF"
        lines.append(
            f"ID {eid}: {ev['name']} ({ev['type']}) - 매 {int(ev['interval']/60)}분 / 상태: {status}"
        )

    embed = discord.Embed(
        title="🕒 자동 이벤트 목록",
        description="\n".join(lines),
        color=COLOR_MAIN
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="event_cancel",
    description="특정 자동 이벤트를 중지합니다. (관리자)"
)
@app_commands.describe(event_id="중지할 이벤트 ID")
async def event_cancel(interaction: discord.Interaction, event_id: int):
    if not is_admin_or_mod(interaction.user):
        await interaction.response.send_message("❗ 관리자만 사용 가능합니다.", ephemeral=True)
        return

    gid = interaction.guild.id  # type: ignore
    events = bot.scheduled_events.get(gid, {})
    ev = events.get(event_id)
    if not ev:
        await interaction.response.send_message("해당 ID의 이벤트를 찾을 수 없습니다.", ephemeral=True)
        return

    ev["active"] = False
    await interaction.response.send_message("✅ 이벤트를 중지했습니다.", ephemeral=True)


# =========================
# 실행
# =========================

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN 환경 변수가 설정되지 않았습니다.")
        exit(1)
    bot.run(DISCORD_TOKEN)