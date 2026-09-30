from config.env import env

# ---------------------------------------------------------------------------
# Recherche sémantique & RAG — GRATUIT par défaut (aucun coût LLM).
#
# Embeddings : modèle LOCAL fastembed (ONNX, sans torch), pas d'API payante.
# RAG : EXTRACTIF (restitue les vrais passages) — génération LLM optionnelle.
#
# Pour activer la recherche sémantique en dev/prod, mettre dans .env :
#   EMBEDDING_PROVIDER=local
#   PGVECTOR_ENABLED=True
# puis indexer les embeddings (compute_embeddings_task par livre) ou re-seed.
# Les défauts ci-dessous restent SÛRS pour la CI (aucun téléchargement de modèle,
# la suite tournant sous config.django.base).
# ---------------------------------------------------------------------------
GEMINI_API_KEY = env.str("GEMINI_API_KEY", default="")
EMBEDDING_PROVIDER = env.str("EMBEDDING_PROVIDER", default="stub")  # "local" en prod
PGVECTOR_ENABLED = env.bool("PGVECTOR_ENABLED", default=False)      # True en prod
# Versets envoyés au modèle par appel (mémoire bornée ; enregistrés après chaque paquet).
EMBEDDING_BATCH_SIZE = env.int("EMBEDDING_BATCH_SIZE", default=128)

# Modèle d'embeddings local (multilingue FR, 768 dims ; non normalisé -> on
# interroge en cosine côté pgvector). Cache persistant recommandé (volume).
FASTEMBED_MODEL = env.str(
    "FASTEMBED_MODEL",
    default="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
)
FASTEMBED_CACHE_DIR = env.str("FASTEMBED_CACHE_DIR", default="/app/.cache/fastembed")

# Génération LLM (Gemini) — OPTIONNELLE. Off par défaut : le RAG reste extractif.
RAG_GENERATION_ENABLED = env.bool("RAG_GENERATION_ENABLED", default=False)
GEMINI_MODEL_NAME = env.str("GEMINI_MODEL_NAME", default="gemini-2.5-flash")
