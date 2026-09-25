from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.bible.models import Book, Chapter, Testament, Verse
from apps.users.models import BaseUser
from apps.users.tests.factories import platform_identity


class BibleApiTests(APITestCase):
    def setUp(self):
        # Setup basic data
        self.testament_at = Testament.objects.create(slug="ancien", name="Ancien Testament", order=1)
        self.testament_nt = Testament.objects.create(slug="nouveau", name="Nouveau Testament", order=2)
        
        self.book1 = Book.objects.create(name="Genèse", slug="genese", testament=self.testament_at, order=1)
        self.book2 = Book.objects.create(name="Exode", slug="exode", testament=self.testament_at, order=2)
        
        self.chapter1 = Chapter.objects.create(book=self.book1, number=1)
        self.chapter2 = Chapter.objects.create(book=self.book1, number=2)
        
        self.verse1 = Verse.objects.create(chapter=self.chapter1, number=1, text="Au commencement Dieu...")
        self.verse2 = Verse.objects.create(chapter=self.chapter1, number=2, text="La terre était sans forme...")
        
        # Populate TSV for search simulation
        from apps.bible.services.index_service import IndexService
        IndexService.populate_tsv_for_book(self.book1.id)

    def test_list_testaments(self):
        url = reverse("api:bible:testament-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["slug"], "ancien")

    def test_testament_books(self):
        url = reverse("api:bible:testament-books", args=["ancien"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["name"], "Genèse")

    def test_testament_books_no_verses(self):
        url = reverse("api:bible:testament-books", args=["ancien"])
        response = self.client.get(url)
        self.assertNotIn("verses", response.data[0])
        self.assertNotIn("chapters", response.data[0])

    def test_list_books(self):
        url = reverse("api:bible:book-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_list_books_filter_testament(self):
        url = reverse("api:bible:book-list") + "?testament=nouveau"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_book_detail(self):
        url = reverse("api:bible:book-detail", args=[self.book1.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Genèse")
        self.assertNotIn("chapters", response.data)

    def test_book_detail_404(self):
        url = reverse("api:bible:book-detail", args=[999999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_book_detail_expand_chapters(self):
        url = reverse("api:bible:book-detail", args=[self.book1.id]) + "?expand=chapters"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("chapters", response.data)
        self.assertEqual(len(response.data["chapters"]), 2)

    def test_list_chapters(self):
        url = reverse("api:bible:chapter-list", args=[self.book1.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_list_verses(self):
        url = reverse("api:bible:verse-list", args=[self.book1.id, 1])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["results"][0]["text"], "Au commencement Dieu...")

    def test_list_verses_excerpt(self):
        url = reverse("api:bible:verse-list", args=[self.book1.id, 1]) + "?excerpt=true"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Even though text isn't > 250, we verify endpoint accepts it and processes
        self.assertEqual(response.data["results"][0]["text"], "Au commencement Dieu...")

    def test_search_endpoint(self):
        url = reverse("api:bible:search") + "?q=Dieu"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # We grouped by book
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["book"]["name"], "Genèse")
        self.assertEqual(len(response.data[0]["matches"]), 1)
        self.assertEqual(response.data[0]["matches"][0]["verse"]["number"], 1)

    def test_search_requires_q_param(self):
        url = reverse("api:bible:search")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_pagination(self):
        url = reverse("api:bible:search") + "?q=Dieu&limit=1"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Search API does not follow DRF PageNumberPagination by default, it just limits results inside `SearchService`. 
        # But we ensure the limit is respected (we only have 1 match for Dieu anyway here).
        self.assertEqual(len(response.data[0]["matches"]), 1)

    @patch("apps.bible.views.import_file_task.delay")
    @patch("apps.bible.views.Path.exists", return_value=True)
    def test_import_api_requires_admin(self, mock_exists, mock_delay):
        url = reverse("api:bible:import-file")
        response = self.client.post(url, {"filename": "bible.json", "source": "b"})
        # Not authenticated
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # Norm user
        user = BaseUser.objects.create_user(
            email="test@test.com", password="pwd",
            role="fidele", phone_number="+221771000001",
            is_active=True, is_verified=True,
        )
        self.client.force_authenticate(user=user)
        response = self.client.post(url, {"filename": "bible.json", "source": "b"})
        # Not admin
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Admin
        admin = platform_identity(BaseUser.objects.create_superuser(email="admin@test.com", password="pwd"))
        self.client.force_authenticate(user=admin)
        response = self.client.post(url, {"filename": "bible.json", "source": "b"})
        # Accepted
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_import_invalid_file(self):
        admin = platform_identity(BaseUser.objects.create_superuser(email="admin2@test.com", password="pwd"))
        self.client.force_authenticate(user=admin)
        url = reverse("api:bible:import-file")
        response = self.client.post(url, {"filename": "bible.json"})  # missing source
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
