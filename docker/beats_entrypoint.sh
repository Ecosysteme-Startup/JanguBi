#!/bin/sh
# Beat Celery (même image que l'API) — un seul par environnement.
set -e
echo "--> beat celery"
exec celery -A apps.tasks beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler "$@"
