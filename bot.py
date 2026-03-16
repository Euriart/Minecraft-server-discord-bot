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

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")

def load_env():
    """Lee el .env en tiempo real y devuelve un dict con los valores."""
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
    """Devuelve las variables de entorno actualizadas en cada llamada."""
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

    # CHECKER_INTERVAL: segundos entre cada comprobación de jugadores (default 300 = 5 min)
    try:
        checker_interval = int(e.get("CHECKER_INTERVAL", os.getenv("CHECKER_INTERVAL", "300")))
    except ValueError:
        checker_interval = 300

    # STARTUP_TIMEOUT: segundos máximos esperando a que el servidor arranque (default 180 = 3 min)
    try:
        startup_timeout = int(e.get("STARTUP_TIMEOUT", os.getenv("STARTUP_TIMEOUT", "180")))
    except ValueError:
        startup_timeout = 180

    return {
        "MC_CONTAINER":      e.get("MC_CONTAINER", os.getenv("MC_CONTAINER", "")),
        "MC_VOLUME":         e.get("MC_VOLUME", os.getenv("MC_VOLUME", "")),
        "MC_PORT_TCP":       e.get("MC_PORT_TCP", os.getenv("MC_PORT_TCP", "")),
        "MC_PORT_UDP":       e.get("MC_PORT_UDP", os.getenv("MC_PORT_UDP", "")),
        "MC_IMAGE":          e.get("MC_IMAGE", os.getenv("MC_IMAGE", "")),
        "MC_RCONPWD":        "RCON_PASSWORD=" + rcon_pwd,
        "TYPE":              "TYPE=" + mc_type,
        "VERSION":           "VERSION=" + mc_version,
        "MODLOADER_VERSION": mc_type + "_VERSION=" + modloader,
        "MEMORY":            "MEMORY=" + memory,
        "PUID":              "PUID=" + puid,
        "GUID":              "PGID=" + guid,
        "STATUS":            status,
        "CHECKER_INTERVAL":  checker_interval,
        "STARTUP_TIMEOUT":   startup_timeout,
    }

# ---------- ESTADO GLOBAL ----------

server = False
checker_task = None
notify_channel = None

# ---------- UTILIDADES ----------

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
    container = get_config()["MC_CONTAINER"]
    output = run_command([
        "docker", "exec", container,
        "rcon-cli", "list"
    ])
    try:
        return int(output.split("There are ")[1].split(" ")[0])
    except Exception:
        return -1  # error / servidor aún arrancando

async def wait_until_ready(timeout: int) -> bool:
    """
    Hace polling cada 10 s hasta que rcon-cli responde correctamente
    o se agota el timeout. Devuelve True si arrancó, False si timeout.
    Corre en un executor para no bloquear el event loop.
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

# ---------- CHECKER AUTOMÁTICO ----------

async def player_checker():
    global server

    while server:
        cfg = get_config()
        interval = cfg["CHECKER_INTERVAL"]
        await asyncio.sleep(interval)

        if not mc_running():
            server = False
            return

        players = mc_players()

        if players == 0:
            await notify_channel.send(
                f"⚠️ No hay jugadores conectados. "
                f"Si sigue vacío en {interval // 60} min se cerrará el servidor."
            )

            await asyncio.sleep(interval)

            players = mc_players()
            if players == 0 and server:
                await notify_channel.send(
                    "🔴 Servidor vacío. Apagando Minecraft..."
                )
                await shutdown_server()
                return

# ---------- ARRANQUE ----------

@bot.command()
@commands.cooldown(rate=1, per=60, type=commands.BucketType.guild)
async def on(ctx):
    global server, checker_task, notify_channel

    notify_channel = ctx.channel
    cfg = get_config()

    if cfg["STATUS"] == "debug":
        await ctx.send("🔧 El servidor está en mantenimiento. Inténtalo más tarde.")
        return

    if mc_running():
        await ctx.send("🟡 El servidor ya está en marcha.")
        return

    await ctx.send("🟢 Iniciando Minecraft...")

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
        "-e", "ENABLE_ROLLING_LOGS=false",
        "-e", "LOG_TIMESTAMP=false",
        "-e", "REMOVE_OLD_LOGS=true",
        cfg["MC_IMAGE"]
    ])

    server = True

    # Esperar a que el servidor esté realmente listo
    timeout = cfg["STARTUP_TIMEOUT"]
    await ctx.send(f"⏳ Esperando a que el servidor esté listo (máx. {timeout}s)...")

    ready = await wait_until_ready(timeout)

    if ready:
        checker_task = asyncio.create_task(player_checker())
        await ctx.send(
            f"✅ ¡Servidor listo!"
        )
    else:
        # Arrancó el contenedor pero RCON no respondió — avisamos pero seguimos monitorizando
        checker_task = asyncio.create_task(player_checker())
        await ctx.send(
            f"⚠️ El contenedor arrancó pero RCON no respondió en {timeout}s. "
            f"Puede que el servidor aún esté cargando. Comprueba con `!status`."
        )

@on.error
async def on_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        remaining = int(error.retry_after)
        await ctx.send(f"⏱️ Espera {remaining}s antes de volver a usar `!on`.")

# ---------- APAGADO ----------

async def shutdown_server():
    global server, checker_task

    server = False

    if checker_task:
        checker_task.cancel()
        checker_task = None

    container = get_config()["MC_CONTAINER"]

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
        await ctx.send("🟡 El servidor no está activo.")
        return

    await ctx.send("🔴 Deteniendo Minecraft...")
    await shutdown_server()
    await ctx.send("✅ Minecraft detenido manualmente.")

@off.error
async def off_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        remaining = int(error.retry_after)
        await ctx.send(f"⏱️ Espera {remaining}s antes de volver a usar `!off`.")

# ---------- ESTADO ----------

@bot.command()
@commands.cooldown(rate=1, per=15, type=commands.BucketType.guild)
async def status(ctx):
    global server, checker_task

    if mc_running():
        if not checker_task or checker_task.done():
            server = True
            checker_task = asyncio.create_task(player_checker())

        players = mc_players()
        cfg = get_config()
        await ctx.send(
            f"🟢 Servidor activo | 👥 Jugadores: `{players}` | "
        )
    else:
        await ctx.send("🔴 Servidor apagado.")

@status.error
async def status_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        remaining = int(error.retry_after)
        await ctx.send(f"⏱️ Espera {remaining}s antes de volver a usar `!status`.")

# ---------- CONFIG (solo admins) ----------

@bot.command()
@commands.has_permissions(administrator=True)
async def config(ctx):
    """Solo admins. Muestra la configuración activa leída del .env en este momento."""
    cfg = get_config()
    status_icon = "🔧 debug" if cfg["STATUS"] == "debug" else "✅ normal"
    lines = [
        f"**Configuración actual** (leída en vivo del `.env`):",
        f"• Estado:     `{status_icon}`",
        f"• Contenedor: `{cfg['MC_CONTAINER']}`",
        f"• Imagen:     `{cfg['MC_IMAGE']}`",
        f"• Memoria:    `{cfg['MEMORY']}`",
        f"• Tipo:       `{cfg['TYPE']}`",
        f"• Versión:    `{cfg['VERSION']}`",
        f"• Modloader:  `{cfg['MODLOADER_VERSION']}`",
        f"• Intervalo checker: `{cfg['CHECKER_INTERVAL']}s`",
        f"• Timeout arranque:  `{cfg['STARTUP_TIMEOUT']}s`",
    ]
    await ctx.send("\n".join(lines))

@config.error
async def config_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 No tienes permisos para usar este comando.")

# ---------- BOT ----------

@bot.event
async def on_ready():
    print(f"Conectado como {bot.user}")

bot.run(os.getenv("DISCORD_TOKEN"))
