import discord
from discord.ext import commands
import subprocess
import os
import asyncio

# ---------- CONFIG ----------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

ENV_FILE = "/app/host_config/.env"

def load_env():
    """Reads the .env file in real time and returns a dictionary with the values."""
    env = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env

def get_config():
    """Returns the updated environment variables on each call."""
    e = load_env()

    mc_type    = e.get("TYPE", os.getenv("TYPE", ""))
    mc_version = e.get("VERSION", os.getenv("VERSION", ""))
    modloader  = e.get("MODLOADER_VERSION", os.getenv("MODLOADER_VERSION", ""))
    rcon_pwd   = e.get("RCONPWD", os.getenv("RCONPWD", ""))
    memory     = e.get("MEMORY", os.getenv("MEMORY", ""))
    puid       = e.get("PUID", os.getenv("PUID", ""))
    guid       = e.get("GUID", os.getenv("GUID", ""))

    raw_status = e.get("STATUS", os.getenv("STATUS", "normal")).lower()
    status = raw_status if raw_status in ("normal", "debug") else "normal"

    # Seconds between watcher checks
    try:
        watch_interval = int(e.get("WATCH_INTERVAL", os.getenv("WATCH_INTERVAL", "30")))
    except ValueError:
        watch_interval = 30

    # Max seconds while waiting for the server to start up (verified via RCON)
    try:
        startup_timeout = int(e.get("STARTUP_TIMEOUT", os.getenv("STARTUP_TIMEOUT", "180")))
    except ValueError:
        startup_timeout = 180

    # Seconds without players before AUTOSTOP shuts down the server (for the warning message)
    try:
        autostop_timeout = int(e.get("AUTOSTOP_TIMEOUT_EST", os.getenv("AUTOSTOP_TIMEOUT_EST", "3600")))
    except ValueError:
        autostop_timeout = 3600

    return {
        "MC_CONTAINER":         e.get("MC_CONTAINER", os.getenv("MC_CONTAINER", "")),
        "MC_VOLUME":            e.get("MC_VOLUME", os.getenv("MC_VOLUME", "")),
        "MC_PORT_TCP":          e.get("MC_PORT_TCP", os.getenv("MC_PORT_TCP", "")),
        "MC_PORT_UDP":          e.get("MC_PORT_UDP", os.getenv("MC_PORT_UDP", "")),
        "MC_IMAGE":             e.get("MC_IMAGE", os.getenv("MC_IMAGE", "")),
        "MC_RCONPWD":           "RCON_PASSWORD=" + rcon_pwd,
        "TYPE":                 "TYPE=" + mc_type,
        "VERSION":              "VERSION=" + mc_version,
        "MODLOADER_VERSION":    mc_type + "_VERSION=" + modloader,
        "MEMORY":               "MEMORY=" + memory,
        "PUID":                 "PUID=" + puid,
        "GUID":                 "PGID=" + guid,
        "STATUS":               status,
        "WATCH_INTERVAL":       watch_interval,
        "STARTUP_TIMEOUT":      startup_timeout,
        "AUTOSTOP_TIMEOUT_EST": autostop_timeout,
    }

# ---------- Global state ----------

server         = False  # True = the bot started the server
manual_stop    = False  # True = Stopped by !off
checker_task   = None
notify_channel = None

# ---------- Utilities ----------

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()

def mc_running():
    container = get_config()["MC_CONTAINER"]
    return run_command([
        "docker", "ps",
        "--filter", f"name=^{container}$",
        "--format", "{{.Names}}"
    ]) == container

def mc_players():
    """Check for players via RCON. Returns -1 if the server is not yet ready."""
    container = get_config()["MC_CONTAINER"]
    output = run_command([
        "docker", "exec", container,
        "rcon-cli", "list"
    ])
    try:
        return int(output.split("There are ")[1].split(" ")[0])
    except Exception:
        return -1

async def wait_until_ready(timeout: int) -> bool:
    """
    It polls every 10 seconds using `rcon-cli list` until the server responds.
    It returns `True` if the server started within the timeout period, and `False` otherwise.
    """
    loop = asyncio.get_event_loop()
    elapsed = 0
    while elapsed < timeout:
        await asyncio.sleep(10)
        elapsed += 10
        players = await loop.run_in_executor(None, mc_players)
        if players >= 0:
            return True
    return False

# ---------- WATCHER — detects automatic shutdown ----------

async def container_watcher():
    """
    Check every WATCH_INTERVAL seconds to see if the container is still running
    using only `docker ps`—no RCON, no connect/disconnect logs.
    When the container stops on its own (due to the image's `AUTOSTOP` setting),
    notify the channel. If it was `!off`, `manual_stop` is already set to `True` and no notification is sent.
    """
    global server, checker_task, manual_stop


    while server:
        cfg = get_config()
        await asyncio.sleep(cfg["WATCH_INTERVAL"])

        if not server:  # !off stopped it while sleeping
            return

        loop = asyncio.get_event_loop()
        running = await loop.run_in_executor(None, mc_running)

        if not running:
            server = False
            checker_task = None
            if not manual_stop:
                # Remove the container after autostop
                container = get_config()["MC_CONTAINER"]
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: run_command(["docker", "rm", container])
                )
                await notify_channel.send(
                    "💤 The server has automatically shut down due to inactivity."
                )
            return
# ---------- Starting ----------

@bot.command()
@commands.cooldown(rate=1, per=60, type=commands.BucketType.guild)
async def on(ctx):
    global server, checker_task, notify_channel, manual_stop

    notify_channel = ctx.channel
    cfg = get_config()

    if cfg["STATUS"] == "debug":
        await ctx.send("🔧 The server is currently undergoing maintenance. Please try again later.")
        return

    if mc_running():
        await ctx.send("🟡 The server is already up and running.")
        return

    await ctx.send("🟢 Starting Minecraft...")

    autostop_h = cfg["AUTOSTOP_TIMEOUT_EST"] // 60

    run_command([
        "docker", "run", "-d",
        "--name", cfg["MC_CONTAINER"],
        "-p",    cfg["MC_PORT_TCP"],
        "-p",    cfg["MC_PORT_UDP"],
        "-v",    cfg["MC_VOLUME"],
        "-e", "EULA=TRUE",
        "-e", cfg["TYPE"],
        "-e", cfg["VERSION"],
        "-e", cfg["MODLOADER_VERSION"],
        "-e", cfg["MEMORY"],
        "-e", "ENABLE_RCON=true",
        "-e", cfg["MC_RCONPWD"],
        "-e", cfg["PUID"],
        "-e", cfg["GUID"],
        "-e", "ENABLE_AUTOSTOP=TRUE",
        "-e", f"AUTOSTOP_TIMEOUT_EST={cfg['AUTOSTOP_TIMEOUT_EST']}",
        "-e", f"AUTOSTOP_TIMEOUT_INIT={cfg['AUTOSTOP_TIMEOUT_EST']}",
        "-e", "AUTOSTOP_PERIOD=10",
        "-e", "ENABLE_ROLLING_LOGS=false",
        "-e", "LOG_TIMESTAMP=false",
        "-e", "REMOVE_OLD_LOGS=true",
        cfg["MC_IMAGE"]
    ])

    server = True
    manual_stop = False

    timeout = cfg["STARTUP_TIMEOUT"]
    await ctx.send(f"⏳ Waiting for the server to be ready (max. {timeout}s)...")

    ready = await wait_until_ready(timeout)

    if ready:
        checker_task = asyncio.create_task(container_watcher())
        await ctx.send(
            f"✅ Server ready!"
        )
    else:
        checker_task = asyncio.create_task(container_watcher())
        await ctx.send(
            f"⚠️ The container started, but RCON did not respond in {timeout}s. "
            f"The server may still be loading. Check with `!status`."
        )

@on.error
async def on_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏱️ Wait {int(error.retry_after)}s before using `!on` again.")

# ---------- Stoping ----------

async def shutdown_server():
    """Clean shutdown: Notifies the server via RCON before stopping the container."""
    global server, checker_task, manual_stop

    manual_stop = True
    server = False

    if checker_task:
        checker_task.cancel()
        checker_task = None

    container = get_config()["MC_CONTAINER"]

    # Clean shutdown via RCON so that Minecraft saves the world
    run_command([
        "docker", "exec", container,
        "rcon-cli", "stop"
    ])

    run_command(["docker", "wait", container])
    run_command(["docker", "rm",   container])

@bot.command()
@commands.cooldown(rate=1, per=30, type=commands.BucketType.guild)
async def off(ctx):
    if not mc_running():
        await ctx.send("🟡 The server is not online.")
        return

    await ctx.send("🔴 Stopping Minecraft...")
    await shutdown_server()
    await ctx.send("✅ Minecraft was manually shut down.")

@off.error
async def off_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏱️ Wait {int(error.retry_after)}s before using `!off` again.")

# ---------- State ----------

@bot.command()
@commands.cooldown(rate=1, per=15, type=commands.BucketType.guild)
async def status(ctx):
    global server, checker_task

    if mc_running():
        if not checker_task or checker_task.done():
            server = True
            checker_task = asyncio.create_task(container_watcher())

        players = mc_players()
        cfg = get_config()
        autostop_h = cfg["AUTOSTOP_TIMEOUT_EST"] // 60
        await ctx.send(
            f"🟢 Server online | 👥 Players: `{players}`"
        )
    else:
        await ctx.send("🔴 Server offline.")

@status.error
async def status_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏱️ Wait {int(error.retry_after)}s before using `!status` again.")

# ---------- CONFIG (only admins) ----------

@bot.command()
@commands.has_permissions(administrator=True)
async def config(ctx):
    cfg = get_config()
    status_icon = "🔧 debug" if cfg["STATUS"] == "debug" else "✅ normal"
    autostop_h  = cfg["AUTOSTOP_TIMEOUT_EST"] // 60
    lines = [
        f"**Current config** (read from `.env` file):",
        f"• State:            `{status_icon}`",
        f"• Container name:   `{cfg['MC_CONTAINER']}`",
        f"• Image:            `{cfg['MC_IMAGE']}`",
        f"• Memory:           `{cfg['MEMORY']}`",
        f"• Type:             `{cfg['TYPE']}`",
        f"• Version:          `{cfg['VERSION']}`",
        f"• Modloader:        `{cfg['MODLOADER_VERSION']}`",
        f"• Watcher interval: `{cfg['WATCH_INTERVAL']}s`",
        f"• Startup timeout:  `{cfg['STARTUP_TIMEOUT']}s`",
        f"• Autostop:         `{autostop_h} min`",
    ]
    await ctx.send("\n".join(lines))

@config.error
async def config_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 You do not have permission to use this command.")

# ---------- BOT ----------

@bot.event
async def on_ready():
    print(f"Connected as {bot.user}")

bot.run(load_env().get("DISCORD_TOKEN", os.getenv("DISCORD_TOKEN")))