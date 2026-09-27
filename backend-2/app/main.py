import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import auth, craving_search, models, schemas, trust
from .database import Base, SessionLocal, engine, get_db

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Tabiko API (archived draft)", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before shipping past your own laptop
    allow_methods=["*"],
    allow_headers=["*"],
)

THEME_TOKENS_PATH = Path(__file__).parent / "themes" / "theme_tokens.json"
with open(THEME_TOKENS_PATH) as f:
    THEME_TOKENS = json.load(f)


def _serialize_review(db: Session, review: models.Review) -> schemas.ReviewOut:
    """ReviewOut carries reviewer badge info that isn't a plain column on
    Review (is_regular_here is computed), so build it explicitly rather
    than relying on from_attributes."""
    reviewer = review.user
    return schemas.ReviewOut(
        id=review.id,
        restaurant_id=review.restaurant_id,
        dish_id=review.dish_id,
        rating=review.rating,
        text=review.text,
        verification_tier=review.verification_tier,
        fraud_flag=review.fraud_flag,
        fraud_reason=review.fraud_reason,
        created_at=review.created_at,
        reviewer=schemas.ReviewerInfo(
            id=reviewer.id,
            name=reviewer.name,
            reviewer_type=reviewer.reviewer_type,
            is_critic_verified=reviewer.is_critic_verified,
            cuisine_specialty=reviewer.cuisine_specialty,
            is_regular_here=trust.is_regular_at_restaurant(db, reviewer.id, review.restaurant_id),
        ),
    )


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------- Auth ----------------

@app.post("/auth/register", response_model=schemas.TokenOut)
def register(payload: schemas.UserRegister, db: Session = Depends(get_db)):
    if db.query(models.User).filter_by(email=payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = models.User(
        name=payload.name,
        email=payload.email,
        password_hash=auth.hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return schemas.TokenOut(access_token=auth.create_access_token(user.id))


@app.post("/auth/login", response_model=schemas.TokenOut)
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(email=payload.email).first()
    if not user or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return schemas.TokenOut(access_token=auth.create_access_token(user.id))


@app.get("/auth/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@app.patch("/auth/me", response_model=schemas.UserOut)
def update_profile(
    payload: schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Self-declare reviewer_type/cuisine_specialty. Note: choosing
    food_critic here does NOT set is_critic_verified — that stays False
    until an admin confirms it (no admin flow exists yet), so the frontend
    must render 'self-identified' vs 'verified' critic differently."""
    if payload.reviewer_type is not None:
        current_user.reviewer_type = payload.reviewer_type
    if payload.cuisine_specialty is not None:
        current_user.cuisine_specialty = payload.cuisine_specialty
    db.commit()
    db.refresh(current_user)
    return current_user


# ---------------- Restaurants ----------------

@app.get("/restaurants", response_model=list[schemas.RestaurantOut])
def list_restaurants(
    cuisine: Optional[str] = None,
    type_tag: Optional[models.RestaurantType] = None,
    dietary: Optional[str] = None,
    good_for: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Restaurant)
    if cuisine:
        query = query.filter(models.Restaurant.cuisine_tags.ilike(f"%{cuisine}%"))
    if type_tag:
        query = query.filter(models.Restaurant.type_tag == type_tag)
    if dietary:
        query = query.filter(models.Restaurant.dietary_flags.ilike(f"%{dietary}%"))
    if good_for:
        query = query.filter(models.Restaurant.good_for.ilike(f"%{good_for}%"))
    return query.limit(100).all()


@app.get("/restaurants/{restaurant_id}", response_model=schemas.RestaurantOut)
def get_restaurant(restaurant_id: int, db: Session = Depends(get_db)):
    r = db.query(models.Restaurant).filter_by(id=restaurant_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return r


@app.get("/restaurants/{restaurant_id}/theme")
def get_restaurant_theme(restaurant_id: int, db: Session = Depends(get_db)):
    r = db.query(models.Restaurant).filter_by(id=restaurant_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    theme_id = r.theme_id or "multi_cuisine_default"
    return {"theme_id": theme_id, "tokens": THEME_TOKENS.get(theme_id, THEME_TOKENS["multi_cuisine_default"])}


@app.patch("/restaurants/{restaurant_id}/confirm-menu", response_model=schemas.RestaurantOut)
def confirm_menu(
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Any logged-in user can confirm a menu is current — crowdsourced freshness,
    same trust model as a review. Abuse of this is a fast-follow (rate-limit per user)."""
    r = db.query(models.Restaurant).filter_by(id=restaurant_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    r.menu_last_confirmed = datetime.utcnow()
    db.commit()
    db.refresh(r)
    return r


# ---------------- Dishes ----------------

@app.get("/restaurants/{restaurant_id}/dishes", response_model=list[schemas.DishOut])
def list_dishes(restaurant_id: int, db: Session = Depends(get_db)):
    return db.query(models.Dish).filter_by(restaurant_id=restaurant_id).all()


@app.post("/restaurants/{restaurant_id}/dishes", response_model=schemas.DishOut)
def add_dish(
    restaurant_id: int,
    payload: schemas.DishCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    restaurant = db.query(models.Restaurant).filter_by(id=restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    dish = models.Dish(restaurant_id=restaurant_id, name=payload.name, tags=payload.tags)
    db.add(dish)
    db.commit()
    db.refresh(dish)
    return dish


# ---------------- Reviews ----------------

@app.post("/reviews", response_model=schemas.ReviewOut)
def create_review(
    payload: schemas.ReviewCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    restaurant = db.query(models.Restaurant).filter_by(id=payload.restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    verified_tier = trust.resolve_verification_tier(
        restaurant, payload.claimed_verification_tier, payload.user_lat, payload.user_lon
    )

    review = models.Review(
        user_id=current_user.id,
        restaurant_id=payload.restaurant_id,
        dish_id=payload.dish_id,
        rating=payload.rating,
        text=payload.text,
        verification_tier=verified_tier,
    )
    trust.score_review(db, review)  # sets fraud_flag/fraud_reason before commit
    db.add(review)

    if review.dish_id:
        dish = db.query(models.Dish).filter_by(id=review.dish_id).first()
        if dish:
            total = dish.avg_rating * dish.review_count + review.rating
            dish.review_count += 1
            dish.avg_rating = total / dish.review_count

    db.commit()
    db.refresh(review)

    trust.update_hygiene_score(db, restaurant)  # after commit so this review is included
    db.commit()

    return _serialize_review(db, review)


@app.get("/reviews/restaurant/{restaurant_id}", response_model=list[schemas.ReviewOut])
def list_reviews_for_restaurant(restaurant_id: int, db: Session = Depends(get_db)):
    reviews = db.query(models.Review).filter_by(restaurant_id=restaurant_id).all()
    return [_serialize_review(db, r) for r in reviews]


@app.get("/reviews/flagged", response_model=list[schemas.ReviewOut])
def list_flagged_reviews(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Basic moderation queue. Restricted to admins once you have real users —
    for now any logged-in user can see it, since is_admin has no assignment
    flow yet. Tighten this before real users show up."""
    reviews = db.query(models.Review).filter_by(fraud_flag=True).all()
    return [_serialize_review(db, r) for r in reviews]


# ---------------- Craving search ----------------

@app.get("/search/craving", response_model=list[schemas.CravingSearchResult])
def craving_search_endpoint(q: str, db: Session = Depends(get_db)):
    results = craving_search.search_by_craving(db, q)
    return [{"restaurant": r, "relevance": score} for r, score in results]
