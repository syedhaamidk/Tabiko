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


# Field weights for the searchable vector.
#
# The corpus used to be one flat bag of words per venue: name, cuisines, dish
# names, dish tags and review text concatenated, each term counting exactly once.
# Against a corpus of real dish text that ranked almost purely on the venue
# NAME, because a name is one short field and a menu is not. "cold brew" returned
# Cold Stone Creamery and Pizza Brew House -- venues with "brew" in their name
# and no cold brew anywhere -- ahead of anywhere that actually lists it.
# "butter chicken" returned a place called "C# chicken".
#
# What a reader is asking is "where can I eat this", so a dish on the menu is
# the strongest evidence, a place being *named* after the thing is weak, and
# everything else sits in between. Weights are applied as term-frequency
# multipliers before normalisation, which keeps the single-vector cosine and
# therefore the endpoint contract unchanged.
FIELD_WEIGHTS: dict[str, float] = {
    "dish_name": 4.0,
    "dish_tags": 2.0,
    "cuisine": 1.5,
    "review": 1.5,
    "name": 1.0,
    "occasion": 0.5,
    "accessibility": 0.5,
    "venue_type": 0.5,
}


def _weighted_tokens(restaurant: models.Restaurant) -> Counter:
    """Token counts for one venue, with each field weighted by how much it proves."""

    counts: Counter = Counter()

    def add(value: str | None, field: str) -> None:
        if not value:
            return
        weight = FIELD_WEIGHTS[field]
        for token in _tokenize(value):
            counts[token] += weight

    for dish in restaurant.dishes:
        add(dish.name, "dish_name")
        add(dish.tags, "dish_tags")

    add(restaurant.cuisine_tags, "cuisine")
    for review in restaurant.reviews:
        if review.text and not review.fraud_flag:
            add(review.text, "review")

    add(restaurant.name, "name")
    add(restaurant.good_for, "occasion")
    add(restaurant.accessibility_flags, "accessibility")
    if restaurant.type_tag:
        add(restaurant.type_tag.value.replace("_", " "), "venue_type")

    return counts


def _document_length(restaurant: models.Restaurant) -> float:
    """How much text a venue has, unweighted.

    Deliberately not the sum of the weighted counts. That sum conflates "this
    venue has a lot to say" with "we think the menu matters more than the name",
    and BM25 then divides by it. A venue with a ten-dish menu came out twenty
    times the average length and had its own dishes divided away, so searching
    "dosa" put a shop called Dosa Hut above MTR, which actually serves it.

    Length normalisation has to answer "is this document unusually long?", so it
    needs a plain token count. Weighting stays on the term-frequency side, where
    it belongs.
    """

    total = 0
    for dish in restaurant.dishes:
        total += len(_tokenize(dish.name))
        total += len(_tokenize(dish.tags or ""))
    total += len(_tokenize(restaurant.name))
    total += len(_tokenize(restaurant.cuisine_tags or ""))
    total += len(_tokenize(restaurant.good_for or ""))
    total += len(_tokenize(restaurant.accessibility_flags or ""))
    if restaurant.type_tag:
        total += len(_tokenize(restaurant.type_tag.value.replace("_", " ")))
    for review in restaurant.reviews:
        if review.text and not review.fraud_flag:
            total += len(_tokenize(review.text))
    return float(total)


BM25_K1 = 1.4
BM25_B = 0.72


def _bm25_score(
    query_tokens: list[str],
    document: dict[str, float],
    idf: dict[str, float],
    document_length: float,
    average_length: float,
) -> float:
    """Score one document against a query.

    Replaces cosine similarity, which was the wrong tool here for a specific and
    observable reason. Cosine L2-normalises every document across all its terms,
    so a venue with ten dishes has each of those dishes divided by the magnitude
    of the entire menu. MTR lists ten dishes and therefore scored each one lower
    than a venue whose entire identity was the word "dosa" -- a bigger, better
    documented menu ranked *below* a shop called Dosa Corner. Searching "dosa"
    put none of the four venues that actually have a dosa anywhere in the top
    twenty.

    BM25 fixes both halves. Term frequency saturates, so listing a dish twice
    does not double the score, but listing ten dishes does not divide it either.
    Length normalisation is a saturating penalty against the *average* document
    rather than a divisor over the whole one, so breadth is mildly discouraged
    instead of catastrophic.

    The endpoint contract is unchanged: still a relevance number, ordered
    descending, and still zero for anything with no term in common.
    """

    if average_length <= 0:
        return 0.0
    length_ratio = document_length / average_length
    total = 0.0
    for token in query_tokens:
        frequency = document.get(token)
        if not frequency:
            continue
        numerator = frequency * (BM25_K1 + 1.0)
        denominator = frequency + BM25_K1 * (1.0 - BM25_B + BM25_B * length_ratio)
        total += idf.get(token, 0.0) * numerator / denominator
    return total


@dataclass(frozen=True)
class _Index:
    """An immutable snapshot of the searchable corpus."""

    # Per-restaurant term counts, aligned with `order`. Weighted, so a dish name
    # contributes more than the same word appearing in the venue's name.
    documents: list[dict[str, float]] = field(default_factory=list)
    order: list[int] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)
    # Unweighted token counts, aligned with `documents`, plus their mean. These
    # feed BM25's length normalisation and are deliberately independent of the
    # field weights -- see `_document_length`.
    lengths: list[float] = field(default_factory=list)
    average_length: float = 0.0

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

    documents = [_weighted_tokens(restaurant) for restaurant in restaurants]
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(document.keys())
    if not document_frequency:
        return _Index()

    document_count = len(documents)
    idf = {
        token: math.log((document_count + 1) / (frequency + 1)) + 1
        for token, frequency in document_frequency.items()
    }
    lengths = [_document_length(restaurant) for restaurant in restaurants]
    return _Index(
        documents=documents,
        order=[restaurant.id for restaurant in restaurants],
        idf=idf,
        lengths=lengths,
        average_length=(sum(lengths) / len(lengths)) if lengths else 0.0,
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

    # A query made entirely of terms the corpus has never seen cannot be scored
    # honestly, so it returns nothing rather than a confident ranking.
    if not any(token in index.idf for token in query_tokens):
        return []

    lengths = index.lengths or [0.0] * len(index.documents)
    scored: list[tuple[int, float]] = []
    for position, document in enumerate(index.documents):
        if not document:
            continue
        score = _bm25_score(
            query_tokens,
            document,
            index.idf,
            lengths[position] if position < len(lengths) else 0.0,
            index.average_length,
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
