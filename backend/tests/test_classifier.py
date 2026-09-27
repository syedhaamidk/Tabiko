from app.classifier import classify_from_raw_tag
from app.models import RestaurantType


def test_classifier_reconciles_multiple_raw_tags():
    cuisine, type_tag, theme_id = classify_from_raw_tag(
        "South Indian; chinese; south_indian"
    )

    assert cuisine == "South Indian, Chinese"
    assert type_tag == RestaurantType.unclassified
    assert theme_id == "south_indian"


def test_classifier_normalizes_source_formatting():
    assert classify_from_raw_tag("North-Indian") == (
        "North Indian",
        RestaurantType.unclassified,
        "north_indian",
    )


def test_classifier_falls_back_for_missing_or_unknown_values():
    assert classify_from_raw_tag(None) == (
        "Multi-cuisine",
        RestaurantType.unclassified,
        "multi_cuisine_default",
    )
    assert classify_from_raw_tag("unmapped_source_value") == (
        "Multi-cuisine",
        RestaurantType.unclassified,
        "multi_cuisine_default",
    )
    assert classify_from_raw_tag("Indian") == (
        "Multi-cuisine",
        RestaurantType.unclassified,
        "multi_cuisine_default",
    )


def test_explicit_type_tokens_are_not_inferred_from_cuisine_alone():
    assert classify_from_raw_tag("fine_dining") == (
        "Multi-cuisine",
        RestaurantType.fine_dine,
        "fine_dine",
    )
    assert classify_from_raw_tag("microbrewery") == (
        "Multi-cuisine",
        RestaurantType.bar_microbrewery,
        "multi_cuisine_default",
    )
