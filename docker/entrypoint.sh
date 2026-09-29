#!/bin/sh
# Entrypoint de l'API (image de production). Applique les migrations puis
# exécute la commande. `make deployer` (Infrastructure) migre déjà AVANT le
# démarrage par un conteneur éphémère : ici il n'y a alors plus rien à faire.
# Le worker et le beat ont leur propre entrypoint et ne migrent JAMAIS.
set -e
echo "--> migrations"
python manage.py migrate --noinput
echo "--> démarrage : $*"
exec "$@"
