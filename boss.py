"""
아이온2 보스 젠 타이머 디스코드 봇
- !컷 으로 보스 처치 시간을 기록하면 다음 젠 시간을 계산하고 10분 전에 알림
- 참여 점수(랭킹), 레기온 보관함, 사다리타기 기능
실행: .env 에 DISCORD_TOKEN, CHANNEL_ID 를 넣고 python3 boss.py
"""
import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import collections
import json
import os
import re
import random
from dotenv import load_dotenv

# --- 1. 봇 설정 ---
load_dotenv()  # .env 파일에서 토큰/채널 ID 읽기 (토큰은 코드에 직접 쓰지 않음)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))  # 알림을 보낼 채널 ID
DATA_FILE = "boss_data.json"

KST = timezone(timedelta(hours=9))
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

# --- 2. 데이터 관리 로직 ---
def load_data():
    default_data = {"participation": {}, "items": {}, "timers": {}, "cooldowns": {}}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for key in default_data:
                    if key not in data: data[key] = default_data[key]
                return data
        except: return default_data
    return default_data

def save_data():
    # 💡 저장 시점에 이미 젠 시간이 지난 타이머들은 자동으로 정리합니다.
    now_kst = datetime.now(KST)
    expired_bosses = []
    for boss_name, time_str in boss_timers.items():
        respawn_time = datetime.fromisoformat(time_str)
        if respawn_time.tzinfo is None: respawn_time = respawn_time.replace(tzinfo=KST)
        if now_kst >= respawn_time:
            expired_bosses.append(boss_name)
            
    for boss_name in expired_bosses:
        boss_timers.pop(boss_name, None)

    all_data["timers"] = boss_timers
    all_data["participation"] = dict(participation_count)
    all_data["items"] = dict(storage_items)
    all_data["cooldowns"] = user_cooldowns
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)

all_data = load_data()
participation_count = collections.defaultdict(float, all_data["participation"])
storage_items = collections.defaultdict(int, all_data["items"])
user_cooldowns = all_data.get("cooldowns", {})
boss_timers = all_data.get("timers", {}) # 💡 타이머 데이터를 스케줄러와 무관하게 메모리에서 직접 관리합니다.

BOSS_CONFIG = {
    "가르투아": 12, "라그타": 12, "카르코티": 12, "비바츠라": 12, 
    "세트람": 6, "안사스": 6, "카시아": 6, "카샤파": 6, "타르탄": 6, 
    "데미로스": 4, "크나쉬": 4, "라와": 4, "우라무": 4,
    "테스트": 1
}

def format_score(score):
    return int(score) if float(score).is_integer() else round(score, 1)

async def send_boss_alert(boss_name):
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(f"⏰ **{boss_name}** 10분 전! 준비해 주세요! @everyone")

@bot.event
async def on_ready():
    if not scheduler.running: scheduler.start()

    now_kst = datetime.now(KST)
    expired_bosses = []
    
    # 서버 재부팅 시 저장되어 있던 타이머 복구 및 알림 스케줄러 재등록
    for boss_name, time_str in list(boss_timers.items()):
        respawn_time = datetime.fromisoformat(time_str)
        if respawn_time.tzinfo is None: respawn_time = respawn_time.replace(tzinfo=KST)
        
        if respawn_time <= now_kst:
            expired_bosses.append(boss_name)
            continue
            
        alert_time = respawn_time - timedelta(minutes=10)
        if alert_time > now_kst:
            scheduler.add_job(send_boss_alert, 'date', run_date=alert_time, args=[boss_name], id=f"{boss_name}_before")
            
    for boss_name in expired_bosses:
        boss_timers.pop(boss_name, None)
        
    save_data()
    print(f'[{bot.user.name}] 모든 기능 복구 및 가동 시작!')

# --- 3. 보스 관리 명령어 ---
@bot.command(name="컷")
async def boss_cut(ctx, name: str, *args):
    if name not in BOSS_CONFIG and name != "점검보스":
        await ctx.send(f"❌ '{name}'은(는) 목록에 없습니다.")
        return

    now_kst = datetime.now(KST)
    time_input = "0"
    members = []

    for arg in args:
        match = re.search(r'<@!?(\d+)>', arg)
        if match:
            member_id = int(match.group(1))
            member = ctx.guild.get_member(member_id)
            if member: members.append(member)
        elif not members and (arg.isdigit() or ":" in arg):
            time_input = arg

    is_maintenance = (name == "점검보스")
    is_12h_boss = (BOSS_CONFIG.get(name) == 12)
    
    if is_maintenance or is_12h_boss:
        point_to_add = 1.1
    else:
        point_to_add = 1.0

    recorded_names = []
    duplicate_names = []

    if members:
        for m in members:
            user_name = m.display_name
            last_time_str = user_cooldowns.get(user_name)
            is_duplicate = False
            
            if last_time_str:
                last_time = datetime.fromisoformat(last_time_str)
                if now_kst < last_time + timedelta(hours=1):
                    is_duplicate = True
            
            safe_name = discord.utils.escape_markdown(user_name)
            
            if is_duplicate:
                duplicate_names.append(safe_name)
            else:
                participation_count[user_name] += point_to_add
                user_cooldowns[user_name] = now_kst.isoformat()
                recorded_names.append(safe_name)
    
    if is_maintenance:
        save_data()
        msg = f"🛠️ **{name}** 보상 완료! (타이머 없음)"
        if recorded_names:
            msg += f"\n👥 참여({len(recorded_names)}명): {', '.join(recorded_names)}"
            msg += "\n🛠️ **점검보스 특별 점수 적용 (+1.1점)**"
        else:
            msg += "\n👥 참여 기록 없음 (멘션된 유저가 없거나 모두 중복입니다)"
            
        if duplicate_names:
            msg += f"\n⚠️ **중복 제외 (1시간 쿨타임):** {', '.join(duplicate_names)}"
        await ctx.send(msg)
        return

    try:
        clean_time = time_input.replace(":", "")
        if clean_time.isdigit() and len(clean_time) in [4, 6]:
            target_h = int(clean_time[:2])
            target_m = int(clean_time[2:4])
            target_s = int(clean_time[4:]) if len(clean_time) == 6 else 0
            kill_time = now_kst.replace(hour=target_h, minute=target_m, second=target_s, microsecond=0)
            if kill_time > now_kst + timedelta(hours=1): kill_time -= timedelta(days=1)
        else:
            kill_time = now_kst - timedelta(minutes=int(time_input))
    except:
        await ctx.send("❌ 시간 형식이 틀렸습니다. (예: 1048, 104800, 10:48)")
        return

    respawn_time = kill_time + timedelta(hours=BOSS_CONFIG[name])
    alert_time = respawn_time - timedelta(minutes=10)
    
    # 💡 타이머 데이터 기록
    boss_timers[name] = respawn_time.isoformat()
    
    job_id = f"{name}_before"
    if scheduler.get_job(job_id): scheduler.remove_job(job_id)
    
    if alert_time > now_kst:
        scheduler.add_job(send_boss_alert, 'date', run_date=alert_time, args=[name], id=job_id)
    else:
        await ctx.send("⚠️ 젠 시간이 10분 이하로 남았습니다! (알림 스케줄러에는 등록되지 않음)")

    save_data()

    msg = f"⚔️ **{name}** 처치! 다음 젠: `{respawn_time.strftime('%m/%d %H:%M:%S')}`"
    if recorded_names:
        msg += f"\n👥 참여({len(recorded_names)}명): {', '.join(recorded_names)}"
        if is_12h_boss:
            msg += "\n⭐ **12시간 보스 특별 점수 적용 (+1.1점)**"
        else:
            msg += "\n☀️ **일반 점수 적용 (+1점)**"
    else:
        msg += "\n👥 참여 기록 없음 (멘션된 유저가 없거나 모두 중복입니다)"
        
    if duplicate_names:
        msg += f"\n⚠️ **중복 제외 (1시간 쿨타임):** {', '.join(duplicate_names)}"
        
    await ctx.send(msg)

# 💡 스케줄러가 아닌 독립 저장소(boss_timers) 기준으로 현황을 계산하여 출력합니다.
@bot.command(name="보스현황")
async def show_status(ctx):
    now_kst = datetime.now(KST)
    active_bosses = []
    
    for boss_name, time_str in list(boss_timers.items()):
        respawn_time = datetime.fromisoformat(time_str)
        if respawn_time.tzinfo is None: respawn_time = respawn_time.replace(tzinfo=KST)
        
        remain = respawn_time - now_kst
        total_seconds = int(remain.total_seconds())
        
        # 실제 젠 시간이 아직 안 지난 보스들만 리스트에 담습니다.
        if total_seconds > 0:
            active_bosses.append((boss_name, respawn_time, remain))
        else:
            # 젠 시간이 지난 것은 저장소에서 제거합니다.
            boss_timers.pop(boss_name, None)
            
    save_data() # 데이터 실시간 정리 및 저장
    
    if not active_bosses:
        await ctx.send("📅 현재 예약된 보스 타이머가 없습니다.")
        return
    
    msg = "📅 **보스 젠 대기 현황**\n"
    # 남은 시간(젠 시간)이 가장 적은 보스부터 위에서 정렬하여 출력
    for boss_name, respawn_time, remain in sorted(active_bosses, key=lambda x: x[1]):
        total_seconds = int(remain.total_seconds())
        m, s = divmod(total_seconds, 60)
        h, m = divmod(m, 60)
        
        if h >= 24:
            days, hours = divmod(h, 24)
            time_left_str = f"{days}일 {hours}시간 {m}분 {s}초"
        else:
            time_left_str = f"{h}시간 {m}분 {s}초"

        msg += f"- {boss_name}: `{time_left_str}` 남음 ({respawn_time.strftime('%m/%d %H:%M:%S')})\n"
    await ctx.send(msg)

# 💡 특정 보스 타이머 단일 삭제 기능
@bot.command(name="타이머삭제")
async def delete_timer(ctx, boss_name: str):
    removed = False
    if boss_name in boss_timers:
        boss_timers.pop(boss_name)
        removed = True
        
    job_id = f"{boss_name}_before"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        removed = True
        
    if removed:
        save_data()
        await ctx.send(f"🗑️ **{boss_name}**의 타이머가 정상적으로 삭제되었습니다.")
    else:
        await ctx.send(f"❓ 현재 대기열에 **{boss_name}**의 타이머가 없습니다.")

# --- 4. 보관함 명령어 ---
@bot.command(name="보관")
async def add_item(ctx, item_name: str, count: int = 1):
    storage_items[item_name] += count
    save_data()
    await ctx.send(f"📦 **{item_name}** {count}개 보관 완료! (총 {storage_items[item_name]}개)")

@bot.command(name="보관함")
async def show_storage(ctx):
    if not storage_items:
        await ctx.send("📥 보관함이 비어 있습니다.")
        return
    
    sorted_items = sorted(storage_items.items(), key=lambda x: (0 if "[명화]" in x[0] else 1, x[0]))

    msg = "📜 **보관함 목록**\n"
    for item, count in sorted_items:
        msg += f"- {item} " + (f"**X{count}**" if count > 1 else "") + "\n"
    await ctx.send(msg)

@bot.command(name="보관삭제")
async def delete_item(ctx, item_name: str, count: int = 1):
    if item_name in storage_items:
        if storage_items[item_name] <= count: del storage_items[item_name]
        else: storage_items[item_name] -= count
        save_data()
        await ctx.send(f"🗑️ {item_name} {count}개 삭제 완료.")
    else: await ctx.send("❓ 해당 아이템이 보관함에 없습니다.")

# --- 아이템 전달 명령어 ---
@bot.command(name="전달")
async def transfer_item(ctx, item_key: str, new_owner: str, count: int = 1):
    """특정 아이템을 다른 사람 명의로 변경 (예: !전달 카시아장갑[A] B 1)"""
    if item_key not in storage_items or storage_items[item_key] < count:
        await ctx.send(f"❓ '{item_key}' 아이템이 부족하거나 보관함에 없습니다.")
        return

    # 정규식으로 '아이템명'과 '[소유자]'를 분리합니다.
    # 예: [명화]크나쉬[A] -> match.group(1): [명화]크나쉬 / match.group(2): A
    match = re.search(r'(.+)\[([^\]]+)\]$', item_key)
    if not match:
        await ctx.send("❌ 아이템 형식이 올바르지 않습니다. (예: `카시아장갑[소유자]`)")
        return

    base_item = match.group(1)
    new_item_key = f"{base_item}[{new_owner}]"

    # 기존 소유자에게서 차감
    storage_items[item_key] -= count
    if storage_items[item_key] <= 0:
        del storage_items[item_key]

    # 새 소유자에게 추가
    storage_items[new_item_key] += count
    save_data()

    await ctx.send(f"🔄 **{item_key}** {count}개를 **{new_owner}**님에게 전달했습니다!\n👉 (현재: {new_item_key} {storage_items[new_item_key]}개)")

@bot.command(name="일괄전달")
async def transfer_all_items(ctx, old_owner: str, new_owner: str):
    """한 사람이 가진 모든 아이템을 다른 사람에게 전부 넘김 (예: !일괄전달 A B)"""
    suffix = f"[{old_owner}]"
    keys_to_transfer = [key for key in list(storage_items.keys()) if key.endswith(suffix)]

    if not keys_to_transfer:
        await ctx.send(f"❓ '{old_owner}' 명의로 된 아이템이 보관함에 없습니다.")
        return

    transfer_count = 0
    for key in keys_to_transfer:
        count = storage_items[key]
        # [old_owner] 부분을 [new_owner]로 바꿔 새 키 생성
        base_item = key[:-len(suffix)]
        new_key = f"{base_item}[{new_owner}]"

        storage_items[new_key] += count
        del storage_items[key]
        transfer_count += count

    save_data()
    await ctx.send(f"🔄 **{old_owner}**님의 모든 보관함 아이템(총 {len(keys_to_transfer)}종류, {transfer_count}개)을 **{new_owner}**님에게 일괄 전달했습니다!")

@bot.command(name="명화초기화")
async def reset_myunghwa(ctx):
    keys_to_delete = [key for key in storage_items.keys() if key.startswith("[명화]")]
    
    if not keys_to_delete:
        await ctx.send("❓ 삭제할 '[명화]' 아이템이 없습니다.")
        return

    for key in keys_to_delete:
        del storage_items[key]
    
    save_data()
    await ctx.send(f"🎨 **[명화]** 태그가 붙은 아이템 {len(keys_to_delete)}종류를 모두 삭제했습니다.")

@bot.command(name="일반초기화")
async def reset_general(ctx):
    keys_to_delete = [key for key in storage_items.keys() if not key.startswith("[명화]")]
    
    if not keys_to_delete:
        await ctx.send("❓ 삭제할 일반 아이템이 없습니다.")
        return

    for key in keys_to_delete:
        del storage_items[key]
    
    save_data()
    await ctx.send(f"🧹 **[명화]**가 아닌 일반 아이템 {len(keys_to_delete)}종류를 모두 삭제했습니다.")

@bot.command(name="보관함초기화")
async def reset_storage(ctx):
    storage_items.clear()
    save_data()
    await ctx.send("🔥 보관함의 **모든** 아이템이 삭제되었습니다.")

# --- 5. 참여 관리 명령어 ---
@bot.command(name="랭킹")
async def show_ranking(ctx):
    if not participation_count:
        await ctx.send("기록 없음.")
        return
    sorted_rank = sorted(participation_count.items(), key=lambda x: x[1], reverse=True)
    msg = "🏆 **참여 랭킹**\n"
    for i, (name, count) in enumerate(sorted_rank, 1):
        safe_name = discord.utils.escape_markdown(name)
        msg += f"{i}위: {safe_name} ({format_score(count)}점)\n"
    await ctx.send(msg)

@bot.command(name="참여추가")
async def add_p(ctx, member: discord.Member, amount: float, *args):
    participation_count[member.display_name] += amount
    save_data()
    
    safe_name = discord.utils.escape_markdown(member.display_name)
    msg = f"✅ {safe_name} +{format_score(amount)}점"
    msg += f" (현재: {format_score(participation_count[member.display_name])}점)"
    
    await ctx.send(msg)

@bot.command(name="참여차감")
async def sub_p(ctx, member: discord.Member, amount: float):
    participation_count[member.display_name] -= amount
    if participation_count[member.display_name] < 0: participation_count[member.display_name] = 0
    save_data()
    safe_name = discord.utils.escape_markdown(member.display_name)
    await ctx.send(f"✅ {safe_name} -{format_score(amount)}점 (현재: {format_score(participation_count[member.display_name])}점)")

@bot.command(name="참여초기화")
async def reset_p(ctx):
    participation_count.clear()
    save_data()
    await ctx.send("🧹 모든 참여 데이터가 초기화되었습니다.")

@bot.command(name="타이머초기화")
async def reset_timers(ctx):
    boss_timers.clear()
    scheduler.remove_all_jobs()
    save_data()
    await ctx.send("⏹️ (전체) 타이머가 초기화되었습니다.")

@bot.command(name="사다리")
async def ladder_game(ctx, *names: str):
    if not names:
        await ctx.send("❌ 이름을 입력해 주세요.")
        return
    member_list = list(names)
    random.shuffle(member_list)
    msg = "🪜 **사다리타기 결과**\n"
    for i, name in enumerate(member_list, 1):
        safe_name = discord.utils.escape_markdown(name)
        msg += f"{i}등. {safe_name}\n"
    await ctx.send(msg)

# --- 6. 실행 ---
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("❌ .env 파일에 DISCORD_TOKEN 이 없습니다. (.env.example 참고)")
bot.run(TOKEN)
