"""Tests du durcissement de l'EmbeddingService (BUG-audit C2).

- sélection du provider local (fastembed) SANS charger le modèle ;
- idempotence : seuls les versets à embedding NULL sont (re)calculés ;
- `force=True` recalcule tout.
"""

import pytest
from django.test import override_settings

from apps.bible.models import Book, Chapter, Testament, Verse
from apps.bible.services.embedding_service import (
    EmbeddingService,
    FastEmbedEmbedder,
    StubEmbedder,
)


@pytest.fixture
def book(db):
    t = Testament.objects.create(slug="ancien", name="AT", order=1)
    b = Book.objects.create(name="Genèse", testament=t, order=1)
    c = Chapter.objects.create(book=b, number=1)
    Verse.objects.create(chapter=c, number=1, text="Au commencement Dieu créa.")
    Verse.objects.create(chapter=c, number=2, text="La terre était informe et vide.")
    return b


@override_settings(EMBEDDING_PROVIDER="local")
def test_local_provider_selected_without_loading_model():
    # Instancier le service en mode 'local' ne doit PAS charger le modèle ONNX.
    service = EmbeddingService()
    assert isinstance(service.provider, FastEmbedEmbedder)


@pytest.mark.django_db
def test_compute_bulk_only_embeds_null_embeddings(book):
    # v1 a déjà un embedding non-null -> ne doit pas être recalculé.
    v1, v2 = Verse.objects.order_by("number")
    v1.embedding = [0.5] * 768
    v1.save(update_fields=["embedding"])

    service = EmbeddingService(provider=StubEmbedder())
    count = service.compute_bulk_embeddings(book.id)

    assert count == 1  # seul v2 (embedding NULL) embeddé
    v1.refresh_from_db()
    v2.refresh_from_db()
    assert v1.embedding[0] == 0.5  # inchangé
    assert v2.embedding is not None and len(v2.embedding) == 768


@pytest.mark.django_db
def test_compute_bulk_force_recomputes_all(book):
    v1, v2 = Verse.objects.order_by("number")
    v1.embedding = [0.5] * 768
    v1.save(update_fields=["embedding"])

    service = EmbeddingService(provider=StubEmbedder())
    count = service.compute_bulk_embeddings(book.id, force=True)

    assert count == 2  # tout recalculé
    v1.refresh_from_db()
    assert v1.embedding[0] == 0.0  # écrasé par le stub


@pytest.mark.django_db
def test_compute_query_embedding_empty_query_returns_empty():
    service = EmbeddingService(provider=StubEmbedder())
    assert service.compute_query_embedding("   ") == []


@pytest.mark.django_db
def test_compute_bulk_raises_application_error_on_count_mismatch(book):
    from apps.core.exceptions import ApplicationError

    class _BadProvider:
        def embed_texts(self, texts):
            return []  # nombre de vecteurs != nombre de versets

    service = EmbeddingService(provider=_BadProvider())
    with pytest.raises(ApplicationError):
        service.compute_bulk_embeddings(book.id)


class _Compteur(StubEmbedder):
    """Enregistre la taille de chaque appel ; peut échouer au n-ième, comme un OOM en plein livre."""

    def __init__(self, echec_au=None):
        self.appels = []
        self.echec_au = echec_au

    def embed_texts(self, texts):
        self.appels.append(len(texts))
        if self.echec_au is not None and len(self.appels) == self.echec_au:
            raise MemoryError("simulé")
        return super().embed_texts(texts)


@pytest.fixture
def gros_livre(db):
    t = Testament.objects.create(slug="ancien", name="AT", order=1)
    b = Book.objects.create(name="Psaumes", testament=t, order=1)
    c = Chapter.objects.create(book=b, number=1)
    Verse.objects.bulk_create([Verse(chapter=c, number=n, text=f"verset {n}") for n in range(1, 301)])
    return b


@pytest.mark.django_db
@override_settings(EMBEDDING_BATCH_SIZE=128)
def test_a_big_book_is_embedded_by_bounded_batches(gros_livre):
    # Recette du 30/09/2026 : tout un livre d'un seul appel au modèle → tué par le noyau à 3 Go.
    fournisseur = _Compteur()

    count = EmbeddingService(provider=fournisseur).compute_bulk_embeddings(gros_livre.id)

    assert fournisseur.appels == [128, 128, 44]
    assert count == 300
    assert not Verse.objects.filter(chapter__book=gros_livre, embedding__isnull=True).exists()


@pytest.mark.django_db
@override_settings(EMBEDDING_BATCH_SIZE=128)
def test_an_interrupted_book_keeps_its_finished_batches_and_resumes(gros_livre):
    with pytest.raises(MemoryError):
        EmbeddingService(provider=_Compteur(echec_au=2)).compute_bulk_embeddings(gros_livre.id)
    assert Verse.objects.filter(chapter__book=gros_livre, embedding__isnull=False).count() == 128

    reprise = _Compteur()
    count = EmbeddingService(provider=reprise).compute_bulk_embeddings(gros_livre.id)

    assert reprise.appels == [128, 44]  # seul le reste est recalculé
    assert count == 172
