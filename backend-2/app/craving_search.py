"""
Craving-based search: "something spicy and comforting" -> ranked restaurants.

This is TF-IDF + cosine similarity over each restaurant's text corpus
(name, cuisine tags, dish names/tags, review text) — NOT a real embedding
model. It's a genuine placeholder, not a permanent choice: true semantic
search (the RAG-embedding approach from Codex/Benkyo) needs a model like
sentence-transformers, which downloads weights from huggingface.co — a
domain this sandbox can't reach, so it isn't installed/tested here.

TF-IDF still gets you real keyword-overlap ranking (e.g. "spicy" restaurants
score higher than "spicy" appearing zero times), which is enough to build
and test the search UI now. Swap `build_corpus`/`search` for an embedding
-based version once you're running this outside the sandbox.
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from . import models


def _restaurant_text(restaurant: models.Restaurant) -> str:
    parts = [
        restaurant.name,
        restaurant.cuisine_tags or "",
        (restaurant.type_tag.value if restaurant.type_tag else "").replace("_", " "),
    ]
    for dish in restaurant.dishes:
        parts.append(dish.name)
        parts.append(dish.tags or "")
    for review in restaurant.reviews:
        if review.text:
            parts.append(review.text)
    return " ".join(p for p in parts if p)


def search_by_craving(db: Session, query: str, limit: int = 20) -> list[tuple[models.Restaurant, float]]:
    restaurants = db.query(models.Restaurant).all()
    if not restaurants:
        return []

    corpus = [_restaurant_text(r) for r in restaurants]
    # Guard against an all-empty corpus (fresh DB with no dishes/reviews yet)
    if not any(corpus):
        return []

    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        matrix = vectorizer.fit_transform(corpus + [query])
    except ValueError:
        # happens if the corpus is too sparse for TF-IDF to build a vocabulary
        return []

    query_vec = matrix[-1]
    restaurant_vecs = matrix[:-1]
    scores = cosine_similarity(query_vec, restaurant_vecs).flatten()

    ranked = sorted(zip(restaurants, scores), key=lambda pair: pair[1], reverse=True)
    return [(r, float(s)) for r, s in ranked[:limit] if s > 0]
