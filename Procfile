release: python manage.py migrate
# ASGI (Daphne) : WebSocket et SSE (docs/TEMPS-REEL.md). gunicorn (WSGI) ne sert ni l'un ni l'autre.
web: daphne -b 0.0.0.0 -p $PORT config.asgi:application
# Files Celery séparées (config/settings/celery.py) : default, media (ffmpeg, 1 à 2 en parallèle), reco.
worker: REMAP_SIGTERM=SIGQUIT celery -A apps.tasks worker -Q default,celery -l info --without-gossip --without-mingle --without-heartbeat
worker_media: REMAP_SIGTERM=SIGQUIT celery -A apps.tasks worker -Q media -n media@%h --concurrency=2 --prefetch-multiplier=1 -l info --without-gossip --without-mingle --without-heartbeat
worker_reco: REMAP_SIGTERM=SIGQUIT celery -A apps.tasks worker -Q reco -n reco@%h --concurrency=1 --prefetch-multiplier=1 -l info --without-gossip --without-mingle --without-heartbeat
beat: REMAP_SIGTERM=SIGQUIT celery -A apps.tasks beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
