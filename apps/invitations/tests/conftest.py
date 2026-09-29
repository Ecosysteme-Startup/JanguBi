import pytest

from apps.hierarchy.tests.factories import Tree


@pytest.fixture
def tree(db) -> Tree:
    return Tree()
