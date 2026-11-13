import json, os

# Create auxiliary linguistic ambiguity cases (excluded from headline metrics)
auxiliary_cases = [
    {
        "case_id": "AUX_LING_0001",
        "family_id": "AUX_LINGUISTIC_AMBIGUITY",
        "database": "concert_singer",
        "request": "Archive old singers from the database",
        "gold_sql": "SELECT * FROM singer WHERE Age > 50;",
        "mutated_sql": "DELETE FROM singer WHERE Age > 40;",
        "note": "Prompt 'old' is linguistically ambiguous without schema-defined threshold.",
        "excluded_from_headline_metrics": True
    },
    {
        "case_id": "AUX_LING_0002",
        "family_id": "AUX_LINGUISTIC_AMBIGUITY",
        "database": "car_1",
        "request": "Remove unpopular cars from the catalog",
        "gold_sql": "SELECT * FROM cars_data WHERE Accelerate < 10;",
        "mutated_sql": "DELETE FROM cars_data WHERE Accelerate < 15;",
        "note": "Prompt 'unpopular' has no concrete relational definition.",
        "excluded_from_headline_metrics": True
    },
    {
        "case_id": "AUX_LING_0003",
        "family_id": "AUX_LINGUISTIC_AMBIGUITY",
        "database": "cinema",
        "request": "Update status for active films",
        "gold_sql": "SELECT * FROM film;",
        "mutated_sql": "UPDATE film SET Directed_by = 'Unknown';",
        "note": "'active' is undefined in cinema schema without date boundaries.",
        "excluded_from_headline_metrics": True
    }
]

os.makedirs('data/evaluation_splits', exist_ok=True)
with open('data/evaluation_splits/auxiliary_linguistic_ambiguity.json', 'w') as f:
    json.dump(auxiliary_cases, f, indent=2)
print(f"Saved {len(auxiliary_cases)} auxiliary linguistic ambiguity cases to data/evaluation_splits/auxiliary_linguistic_ambiguity.json")

