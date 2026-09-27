"""Craving search over restaurant, dish, and review text.

A small TF-IDF/cosine implementation with no model download or heavy runtime
dependency. It can be replaced with embedding search later without changing the
endpoint contract.

Two things this module is careful about, both learned from running it against
real data rather than a handful of seeded rows:

**It is cached, because rebuilding it is not free.** The index is derived from
every restaurant, dish and review, so building it per query meant loading 7,728
places plus their dishes and reviews on every keystroke-driven search. It is
rebuilt only when the underlying row counts change, which a few COUNT queries
settle in well under a millisecond.

**It refuses to answer questions it cannot answer.** The corpus is whatever text
exists: names, cuisines and tags, plus dish and review text when there is any.
Most places have no dish or review text at all, so a craving like "comfort food"
matches nothing in the corpus. A naive cosine similarity then scores the query as
just "food" and cheerfully returns venues named "Food" and "FOOD COURT". When a
query term is absent from the entire corpus, the honest answer is "we have no
text for that", so the caller is told rather than handed a confident ranking of
irrelevant places.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, selectinload

from . import models

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "i",
    "in",
    "is",
    "of",
    "on",
    "or",
    "some",
    "that",
    "the",
    "to",
    "want",
    "with",
}


def _tokenize(value: str) -> list[str]:
    return [
        token
        for token in _TOKEN_PATTERN.findall(value.lower())
        if len(token) > 1 and token not in _STOP_WORDS
    ]


def _restaurant_text(restaurant: models.Restaurant) -> str:
    parts = [
        restaurant.name,
        restaurant.cuisine_tags or "",
        restaurant.good_for or "",
        restaurant.accessibility_flags or "",
        restaurant.type_tag.value.replace("_", " ") if restaurant.type_tag else "",
    ]
    parts.extend(dish.name for dish in restaurant.dishes)
    parts.extend(dish.tags or "" for dish in restaurant.dishes)
    parts.extend(
        review.text
        for review in restaurant.reviews
        if review.text and not review.fraud_flag
    )
    return " ".join(part for part in parts if part)


def _normalized_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(token for token in tokens if token in idf)
    if not counts:
        return {}
    vector = {token: count * idf[token] for token, count in counts.items()}
    magnitude = math.sqrt(sum(value * value for value in vector.values()))
    return {token: value / magnitude for token, value in vector.items()}


@dataclass(frozen=True)
class _Index:
    """An immutable snapshot of the searchable corpus."""

    # Per-restaurant unit vectors, aligned with `order`.
    vectors: list[dict[str, float]] = field(default_factory=list)
    order: list[int] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.order


@dataclass(frozen=True)
class CravingSearchResult:
    restaurant: models.Restaurant
    relevance: float
    # Query terms with no occurrence anywhere in the corpus. Non-empty means the
    # ranking below is answering a narrower question than the reader asked.
    unmatched_terms: tuple[str, ...] = ()


_index: _Index | None = None
_index_signature: tuple[int, int, int, int] | None = None
_lock = threading.Lock()


def _corpus_signature(db: Session) -> tuple[int, int, int, int]:
    """A cheap fingerprint of the searchable corpus.

    Counts rather than content because there is no updated_at on these tables to
    hash against. Editing a dish name without changing any count would keep a
    stale index, which is the one case this cannot see.
    """

    restaurants = db.query(models.Restaurant).count()
    dishes = db.query(models.Dish).count()
    reviews = db.query(models.Review).count()
    # Max id catches appends cheaply; the counts catch deletes.
    newest = (
        db.query(models.Review.id).order_by(models.Review.id.desc()).limit(1).scalar()
        or 0
    )
    return (restaurants, dishes, reviews, newest)


def _build_index(db: Session) -> _Index:
    # selectinload keeps this at two queries instead of one per restaurant, which
    # is what made the previous per-query build unusably slow.
    restaurants = (
        db.query(models.Restaurant)
        .options(
            selectinload(models.Restaurant.dishes),
            selectinload(models.Restaurant.reviews),
        )
        .order_by(models.Restaurant.id)
        .all()
    )
    if not restaurants:
        return _Index()

    documents = [_tokenize(_restaurant_text(restaurant)) for restaurant in restaurants]
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(set(document))
    if not document_frequency:
        return _Index()

    document_count = len(documents)
    idf = {
        token: math.log((document_count + 1) / (frequency + 1)) + 1
        for token, frequency in document_frequency.items()
    }
    return _Index(
        vectors=[_normalized_vector(document, idf) for document in documents],
        order=[restaurant.id for restaurant in restaurants],
        idf=idf,
    )


def _get_index(db: Session) -> _Index:
    global _index, _index_signature

    signature = _corpus_signature(db)
    with _lock:
        if _index is None or _index_signature != signature:
            _index = _build_index(db)
            _index_signature = signature
        return _index


def invalidate_index() -> None:
    """Drop the cached index. Called after writes that change the corpus."""

    global _index, _index_signature
    with _lock:
        _index = None
        _index_signature = None


def search_by_craving(
    db: Session, query: str, limit: int = 20
) -> list[tuple[models.Restaurant, float, tuple[str, ...]]]:
    """Rank venues by text similarity, reporting any query terms it could not use."""

    index = _get_index(db)
    if index.is_empty():
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # A term the corpus has never seen cannot contribute to a cosine score, so a
    # ranking built from it would answer a different question than the one asked.
    # No term is exempt from this: a craving word like "comfort" that appears in
    # no dish, review or place name is exactly the gap worth reporting, and
    # exempting it is what let "comfort food" rank venues named "Food".
    unmatched = tuple(
        sorted({token for token in query_tokens if token not in index.idf})
    )

    query_vector = _normalized_vector(query_tokens, index.idf)
    if not query_vector:
        return []

    scored: list[tuple[int, float]] = []
    for position, document_vector in enumerate(index.vectors):
        if not document_vector:
            continue
        score = sum(
            query_value * document_vector.get(token, 0.0)
            for token, query_value in query_vector.items()
        )
        if score > 0:
            scored.append((index.order[position], score))

    if not scored:
        return []

    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    page = scored[:limit]
    by_id = {
        restaurant.id: restaurant for restaurant in _load(db, [pid for pid, _ in page])
    }
    results = [
        (restaurant, round(score, 6), unmatched)
        for pid, score in page
        if (restaurant := by_id.get(pid)) is not None
    ]
    results.sort(key=lambda row: (-row[1], row[0].name, row[0].id))
    return results


def _load(db: Session, ids: list[int]) -> list[models.Restaurant]:
    if not ids:
        return []
    return db.query(models.Restaurant).filter(models.Restaurant.id.in_(ids)).all()
