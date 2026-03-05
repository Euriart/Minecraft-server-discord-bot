import discord
from discord.ext import commands
import subprocess
import os
import asyncio

# ---------- CONFIG ----------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

MC_CONTAINER = str(os.getenv("MC_CONTAINER"))
MC_VOLUME = str(os.getenv("MC_VOLUME"))
MC_PORT_TCP = str(os.getenv("MC_PORT_TCP"))
MC_PORT_UDP = str(os.getenv("MC_PORT_UDP"))
MC_IMAGE = str(os.getenv("MC_IMAGE"))
MC_RCONPWD = "RCON_PASSWORD=" + str(os.getenv("RCONPWD"))
TYPE = "TYPE=" + str(os.getenv("TYPE"))
VERSION = "VERSION=" + str(os.getenv("VERSION"))
MODLOADER_VERSION = str(os.getenv("TYPE")) + "_VERSION=" + str(os.getenv("MODLOADER_VERSION"))
MEMORY ="MEMORY=" + str(os.getenv("MEMORY"))
PUID = "PUID=" + str(os.getenv("PUID"))
GUID = "PGID=" + str(os.getenv("GUID"))

# ---------- ESTADO GLOBAL ----------

server = False
checker_task = None
notify_channel = None

# ---------- UTILIDADES ----------

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()

def mc_running():
    return run_command([
        "docker", "ps",
        "--filter", f"name=^{MC_CONTAINER}$",
        "--format", "{{.Names}}"
    ]) == MC_CONTAINER

def mc_players():
    output = run_command([
        "docker", "exec", MC_CONTAINER,
        "rcon-cli", "list"
    ])
    try:
        return int(output.split("There are ")[1].split(" ")[0])
    except Exception:
        return -1  # error

# ---------- CHECKER AUTOMÁTICO ----------

async def player_checker():
    global server

    while server:
        await asyncio.sleep(120)

        if not mc_running():
            server = False
            return

        players = mc_players()

        if players == 0:
            await notify_channel.send(
                "⚠️ No hay jugadores conectados. Si sigue vacío en 2 minutos se cerrará el servidor."
            )

            await asyncio.sleep(60)

            players = mc_players()
            if players == 0 and server:
                await notify_channel.send(
                    "🔴 Servidor vacío durante 4 minutos. Apagando Minecraft..."
                )
                await shutdown_server()
                return

# ---------- ARRANQUE ----------

@bot.command()
async def on(ctx):
    global server, checker_task, notify_channel

    notify_channel = ctx.channel

    if mc_running():
        await ctx.send("🟡 El servidor ya está en marcha.")
        return

    await ctx.send("🟢 Iniciando Minecraft...")

    run_command([
        "docker", "run", "-d",
        "--name", MC_CONTAINER,
        "-p", MC_PORT_TCP,
        "-p", MC_PORT_UDP,
        "-v", MC_VOLUME,
        "-e", "EULA=TRUE",
        "-e", TYPE,
        "-e", VERSION,
        "-e", MODLOADER_VERSION,
        "-e", MEMORY,
        "-e", "ENABLE_RCON=true",
        "-e", MC_RCONPWD,
        "-e", PUID,
        "-e", GUID,
        "-e", "ENABLE_ROLLING_LOGS=false",
        "-e", "LOG_TIMESTAMP=false",
        "-e", "REMOVE_OLD_LOGS=true",
        MC_IMAGE
    ])

    server = True
    checker_task = asyncio.create_task(player_checker())

    await ctx.send("✅ Minecraft arrancado y monitorizando jugadores.")

# ---------- APAGADO ----------

async def shutdown_server():
    global server, checker_task

    server = False

    if checker_task:
        checker_task.cancel()
        checker_task = None

    run_command([
        "docker", "exec", MC_CONTAINER,
        "rcon-cli", "stop"
    ])

    run_command(["docker", "wait", MC_CONTAINER])
    run_command(["docker", "rm", MC_CONTAINER])

@bot.command()
async def off(ctx):
    if not mc_running():
        await ctx.send("🟡 El servidor no está activo.")
        return

    await ctx.send("🔴 Deteniendo Minecraft...")
    await shutdown_server()
    await ctx.send("✅ Minecraft detenido manualmente.")

# ---------- ESTADO ----------

@bot.command()
async def status(ctx):
    global server, checker_task

    if mc_running():
        if not checker_task or checker_task.done():
            server = True
            checker_task = asyncio.create_task(player_checker())

        players = mc_players()
        await ctx.send(f"🟢 Servidor activo | 👥 Jugadores: {players}")
    else:
        await ctx.send("🔴 Servidor apagado.")

# ---------- BOT ----------

@bot.event
async def on_ready():
    print(f"Conectado como {bot.user}")

bot.run(os.getenv("DISCORD_TOKEN"))

