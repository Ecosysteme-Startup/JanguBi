import logging
from functools import lru_cache
from typing import List, Optional, Protocol

from django.conf import settings
from django.db import transaction

from apps.bible.models import Verse
from apps.core.exceptions import ApplicationError

logger = logging.getLogger(__name__)

# Dimension des embeddings (doit correspondre à Verse.embedding = VectorField(768)
# et au modèle local par défaut paraphrase-multilingual-mpnet-base-v2 = 768).
EMBEDDING_DIM = 768

# Modèle local par défaut : multilingue (FR), normalisé L2 (=> cosine direct),
# sans préfixe query/passage. ~1 Go, ONNX (pas de torch).
DEFAULT_LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


class EmbedderProvider(Protocol):
    """Protocol for embedding providers."""

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        ...


class StubEmbedder:
    """Provider de secours : renvoie des vecteurs zéro (CI/tests, ou aucun provider
    réel configuré). Ne fait aucun appel réseau ni chargement de modèle."""

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        logger.warning(
            "Using StubEmbedder for %d texts. Set EMBEDDING_PROVIDER=local "
            "(fastembed) for real semantic search.",
            len(texts),
        )
        return [[0.0] * EMBEDDING_DIM for _ in texts]


@lru_cache(maxsize=1)
def _get_fastembed_model(model_name: str, cache_dir: Optional[str]):
    """Singleton paresseux du modèle fastembed (chargement ONNX coûteux ~1 Go).
    Import local pour ne pas tirer onnxruntime au démarrage de Django."""
    from fastembed import TextEmbedding  # import paresseux volontaire

    logger.info("Loading fastembed model '%s' (cache_dir=%s)...", model_name, cache_dir)
    return TextEmbedding(model_name=model_name, cache_dir=cache_dir)


class FastEmbedEmbedder:
    """Embeddings LOCAUX gratuits via fastembed (ONNX, CPU). Aucun coût API.

    mpnet-base-v2 est normalisé L2 et n'exige pas de préfixe — on passe le texte
    brut. Le modèle est chargé paresseusement et mémoïsé (un seul par worker)."""

    def __init__(self, model_name: Optional[str] = None, cache_dir: Optional[str] = None):
        self.model_name = model_name or getattr(settings, "FASTEMBED_MODEL", DEFAULT_LOCAL_MODEL)
        self.cache_dir = cache_dir or getattr(settings, "FASTEMBED_CACHE_DIR", None)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        model = _get_fastembed_model(self.model_name, self.cache_dir)
        # .embed() renvoie un générateur de np.ndarray (float32) -> list[float].
        return [vector.tolist() for vector in model.embed(texts)]


class GeminiEmbedder:
    """Provider payant optionnel (Google Gemini). Conservé pour compatibilité ;
    non utilisé par défaut (EMBEDDING_PROVIDER=local)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", None)
        self.model = "gemini-embedding-001"
        # Clé via header (pas dans l'URL : évite la fuite en logs/traces réseau).
        self.url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model}:batchEmbedContents"
        )

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not self.api_key:
            logger.warning("GEMINI_API_KEY is not set. Falling back to zeros.")
            return [[0.0] * EMBEDDING_DIM for _ in texts]

        import time

        import httpx
        from tenacity import (
            retry,
            retry_if_exception,
            stop_after_attempt,
            wait_exponential,
        )

        def _is_retryable(exc: BaseException) -> bool:
            # Ne retenter QUE le réseau et les 5xx ; pas les 4xx (clé invalide,
            # quota mal formé, requête invalide) — déterministes, inutile d'insister.
            if isinstance(exc, httpx.RequestError):
                return True
            if isinstance(exc, httpx.HTTPStatusError):
                return exc.response.status_code >= 500
            return False

        @retry(
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(5),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        def _make_request(client, payload):
            response = client.post(
                self.url,
                json=payload,
                headers={"x-goog-api-key": self.api_key},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

        all_embeddings: List[List[float]] = []
        chunk_size = 100
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i:i + chunk_size]
            requests = [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": txt}]},
                    "outputDimensionality": EMBEDDING_DIM,
                }
                for txt in chunk
            ]
            payload = {"requests": requests}

            with httpx.Client() as client:
                data = _make_request(client, payload)
                for emb in data.get("embeddings", []):
                    all_embeddings.append(emb["values"])

            if i + chunk_size < len(texts):
                time.sleep(5.0)  # rester sous ~15 RPM

        return all_embeddings


def _build_provider(provider_name: str) -> EmbedderProvider:
    name = (provider_name or "stub").lower()
    if name == "stub":
        return StubEmbedder()
    if name == "gemini":
        return GeminiEmbedder()
    if name in ("local", "fastembed", "mpnet"):
        return FastEmbedEmbedder()
    logger.error("Unknown embedding provider '%s'. Falling back to stub.", provider_name)
    return StubEmbedder()


class EmbeddingService:
    """Génération et stockage des embeddings de versets."""

    def __init__(self, provider: Optional[EmbedderProvider] = None):
        self.provider = provider or _build_provider(getattr(settings, "EMBEDDING_PROVIDER", "stub"))

    # Pas de transaction sur tout le livre : une par paquet (plus bas), pour qu'un calcul interrompu
    # garde les paquets déjà faits.
    def compute_bulk_embeddings(self, book_id: int, *, force: bool = False) -> int:
        """Calcule et stocke les embeddings des versets d'un livre.

        Par défaut, idempotent : ne (re)calcule que les versets dont l'embedding
        est NULL (filtrage SQL, pas d'heuristique fragile). `force=True` recalcule
        tout le livre. Retourne le nombre de versets embeddés.
        """
        qs = Verse.objects.filter(chapter__book_id=book_id)
        if not force:
            qs = qs.filter(embedding__isnull=True)
        # select_related anti-N+1 : on lit chapter.book.name pour construire le texte.
        verses = list(
            qs.select_related("chapter__book").order_by("chapter__number", "number")
        )
        if not verses:
            logger.info("No verses to embed for book_id %s (force=%s).", book_id, force)
            return 0

        # Par paquets bornés, enregistrés au fil de l'eau : un livre entier d'un seul appel (2 500 versets
        # pour les Psaumes) faisait monter le modèle au-delà de 3 Go — tué par le noyau en recette le
        # 30/09/2026, sans rien avoir enregistré. Un calcul interrompu reprend où il s'était arrêté
        # (seuls les versets encore NULL sont sélectionnés).
        size = max(1, int(getattr(settings, "EMBEDDING_BATCH_SIZE", 128)))
        for start in range(0, len(verses), size):
            batch = verses[start : start + size]
            # "Genèse 1:1 - Au commencement Dieu créa le ciel et la terre."
            texts = [f"{v.chapter.book.name} {v.chapter.number}:{v.number} - {v.text}" for v in batch]
            vectors = self.provider.embed_texts(texts)
            if len(vectors) != len(batch):
                raise ApplicationError(
                    f"Embedding provider returned {len(vectors)} vectors for {len(batch)} verses."
                )
            for verse, vector in zip(batch, vectors):
                verse.embedding = vector
            with transaction.atomic():
                Verse.objects.bulk_update(batch, ["embedding"], batch_size=500)
        logger.info("Computed embeddings for %d verses in book_id %s.", len(verses), book_id)
        return len(verses)

    def compute_query_embedding(self, text: str) -> List[float]:
        """Embedding d'une requête de recherche (1 vecteur)."""
        if not text or not text.strip():
            return []
        vectors = self.provider.embed_texts([text])
        return vectors[0] if vectors else []
