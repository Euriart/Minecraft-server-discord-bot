#!/bin/bash

CONTAINER="minecraft-neoforge"

sudo docker exec -it "$CONTAINER" rcon-cli "$@"
