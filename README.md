---

# Minecraft Server Discord Bot

## Overview

This project is a **Discord bot** that allows you to manage and interact with a **Minecraft server** directly from Discord.
It provides features like server start/stop, status checks and integration with a Minecraft Docker container.

---

## Features

* Start and stop the Minecraft server from Discord.
* Get real-time server status and player count.
* Fully configurable via a `.env` file.
* Works with Dockerized Minecraft servers.

---

## Requirements

* **Docker** installed on the host machine.
* A **Discord bot token**.
* RCON enabled on your Minecraft server.
* Git and Bash for setup.

---

## Setup

1. **Clone the repository**:

```bash
git clone git@github.com:Euriart/Minecraft-server-discord-bot.git
cd Minecraft-server-discord-bot
```

2. **Create a `.env` file**:

Use the provided script to generate it:

```bash
./setup.sh
```

Fill in all required variables, including as example:

```
DISCORD_TOKEN=<your-token>
RCONPWD=<your-password>
MC_CONTAINER=minecraft-neoforge
MC_VOLUME=~/minecraft:/data
MC_PORT_TCP=25565:25565/tcp
MC_PORT_UDP=25565:25565/udp
MC_IMAGE=itzg/minecraft-server:java21
TYPE=NEOFORGE
VERSION=1.21.1
MODLOADER_VERSION=21.1.218
MEMORY=5G
PUID=1000
GUID=1000
```

3. **Start the bot**:

```bash
./start.sh
```

---

## Environment Variables

| Variable            | Description                                      |
| ------------------- | -----------------------------------------------  |
| `DISCORD_TOKEN`     | Your Discord bot token.                          |
| `RCONPWD`           | Password for Minecraft RCON.                     |
| `MC_CONTAINER`      | Name of the Minecraft Docker container.          |
| `MC_VOLUME`         | Docker volume for persistent data.               |
| `MC_PORT_TCP`       | TCP port for the Minecraft server.               |
| `MC_PORT_UDP`       | UDP port for the Minecraft server.               |
| `MC_IMAGE`          | Docker image of the Minecraft server.            |
| `TYPE`              | Server type (e.g., `vanilla`, `NEOFORGE`).       |
| `VERSION`           | Minecraft version.                               |
| `MODLOADER_VERSION` | Modloader version if using Forge/Fabric/Neoforge.|
| `MEMORY`            | Maximum memory allocated to the server.          |
| `PUID`              | User ID for file permissions inside container.   |
| `GUID`              | Group ID for file permissions inside container.  |

---

## Usage

Once the bot is running:

* Use Discord commands to control the server.
* Check server status anytime with `!status`.
* Open or close the server with `!on` | `!off`.
* You can also use the scripts in the rcon folder to open the administration console `./rcon.sh` or execute only one command `./rcon_arg.sh <command>`.
---

## Security Notes

* **Never commit your `.env` file**. It contains sensitive information such as your Discord token and RCON password.
* Add `.env` to `.gitignore`:

```
.env
```

---

## Special thanks

Thanks to itzg for creating the docker image for the server.

---
## License

This project is licensed under the GPLv3 License.

---
