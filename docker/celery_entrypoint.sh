#!/bin/sh
# Worker Celery (même image que l'API). Réglables :
#   CELERY_QUEUES      files lues (défaut : default,celery,reco ; worker média : media)
#   CELERY_CONCURRENCY processus (1 en recette)
set -e
echo "--> worker celery (files : ${CELERY_QUEUES:-default,celery,reco})"
exec celery -A apps.tasks worker -l info --without-gossip --without-mingle --without-heartbeat \
  -Q "${CELERY_QUEUES:-default,celery,reco}" --concurrency "${CELERY_CONCURRENCY:-2}" \
  -n "${CELERY_NODE_NAME:-default}@%h" "$@"
