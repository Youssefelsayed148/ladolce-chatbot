#!/usr/bin/env python3
"""Merge scraped_website_products.json and scraped_pdf_products.json into a
single deduplicated catalog (data/unique_products.json).

Matching approach:
- Website rows are grouped into "products" by (name, category) - weight-tiered
  products (e.g. a 500g/1kg pair) share a name+category and stay together as
  one group with multiple rows/prices.
- Each PDF row is fuzzy-matched (rapidfuzz) against website product groups,
  but ONLY within categories that are a plausible cross-source equivalent of
  its own PDF category (see CATEGORY_COMPATIBILITY below). Text similarity
  alone is not trusted across categories that represent a genuinely different
  product form - e.g. the PDF's "Date Paste" items ("Sesame Date Paste With
  Tahina") read as near-duplicates of website "Stuffed & Flavored Dates"
  items ("Sesasm Date With Tahina") by name alone, but a date paste/spread and
  a whole stuffed date are different physical products, so that category is
  deliberately given no compatible website category and always stays unique.
- A matched PDF row contributes no new data (PDF never has price/description/
  image in this run) - it's just absorbed; the website group's rows are kept
  as-is in the output.
- An unmatched PDF row becomes its own row in the output, price/description/
  image null as scraped.
"""

import json
import re
import sys
from pathlib import Path

from rapidfuzz import fuzz

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

STOPWORDS = {"with", "and", "the", "of"}
WORD_DIFF_RATIO_THRESHOLD = 75  # for a single differing word pair (e.g. jordan/jordanian)

# PDF category -> compatible website categories, most-preferred first.
CATEGORY_COMPATIBILITY = {
    "Plain Dates": ["Date Packs"],
    "Stuffed Dates": ["Stuffed & Flavored Dates", "Individual Dates"],
    "Date Paste": [],  # no equivalent product form on the website - never matched
}

MANUAL_REVIEW_NAME = "Sukkari Date Roche Crisp Franci With Cream"
MANUAL_REVIEW_NOTE = (
    "Pulled out of scraped_pdf_products.json before fuzzy matching: the product "
    "name was transcribed from a decorative script font on the catalogue page "
    "and is low-confidence (could plausibly be \"Crisp Franc\" or another "
    "reading). Needs visual confirmation against the source PDF before it's "
    "matched or added to the catalog."
)


def log(message):
    print(f"[merge_catalog] {message}", file=sys.stderr)


def load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def drop_source(row):
    return {k: v for k, v in row.items() if k != "source"}


def group_website_products(website_rows):
    groups = {}
    order = []
    for row in website_rows:
        key = (row["name"], row["category"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    return groups, order


def normalize_words(name):
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    words = []
    for word in cleaned.split():
        if word in STOPWORDS:
            continue
        if word.endswith("s") and len(word) > 3:
            word = word[:-1]  # crude singular fold
        words.append(word)
    return set(words)


def word_set_match_score(pdf_words, website_words):
    """A confidence score if the two word sets name the same product -
    allowing at most one differing-but-highly-similar word pair (to tolerate
    things like a plural/spelling variant, e.g. jordan/jordanian) - otherwise
    None.

    Deliberately NOT a raw whole-string fuzzy ratio: two names sharing all
    their boilerplate words but differing in the one word that names the
    actual flavor/variant (e.g. "Milk" vs "Dark" Chocolate, "Peanut" vs
    "Hazelnut") must NOT match, and whole-string ratios score those
    dangerously high because most of the string is still identical.
    """
    if pdf_words == website_words:
        return 100.0
    diff_pdf = pdf_words - website_words
    diff_web = website_words - pdf_words
    if len(diff_pdf) == 1 and len(diff_web) == 1:
        ratio = fuzz.ratio(next(iter(diff_pdf)), next(iter(diff_web)))
        if ratio >= WORD_DIFF_RATIO_THRESHOLD:
            return ratio
    return None


def best_match(pdf_name, pdf_category, groups, order):
    compatible_categories = CATEGORY_COMPATIBILITY.get(pdf_category, [])
    if not compatible_categories:
        return None, None, 0

    pdf_words = normalize_words(pdf_name)
    best_key = None
    best_score = None
    best_priority = None
    closest_candidate = None
    closest_candidate_score = -1

    for key in order:
        name, category = key
        if category not in compatible_categories:
            continue

        diagnostic_score = fuzz.WRatio(pdf_name, name)
        if diagnostic_score > closest_candidate_score:
            closest_candidate_score = diagnostic_score
            closest_candidate = key

        score = word_set_match_score(pdf_words, normalize_words(name))
        if score is None:
            continue
        priority = compatible_categories.index(category)
        if best_key is None or priority < best_priority or (priority == best_priority and score > best_score):
            best_key, best_score, best_priority = key, score, priority

    if best_key is None:
        return None, closest_candidate, closest_candidate_score
    return best_key, best_key, best_score


def main():
    website_rows = load("scraped_website_products.json")
    pdf_rows = load("scraped_pdf_products.json")

    manual_review_rows = [r for r in pdf_rows if r["name"] == MANUAL_REVIEW_NAME]
    pdf_rows = [r for r in pdf_rows if r["name"] != MANUAL_REVIEW_NAME]

    manual_review_output = []
    for row in manual_review_rows:
        entry = dict(row)
        entry["note"] = MANUAL_REVIEW_NOTE
        manual_review_output.append(entry)

    log(f"website rows: {len(website_rows)}, pdf rows (excl. manual review): {len(pdf_rows)}")

    groups, order = group_website_products(website_rows)

    price_conflicts = []
    unmatched_pdf_rows = []
    matched_pdf_count = 0

    for pdf_row in pdf_rows:
        matched_key, candidate_key, score = best_match(
            pdf_row["name"], pdf_row["category"], groups, order
        )
        if matched_key is None:
            unmatched_pdf_rows.append(pdf_row)
            log(
                f"UNMATCHED  [{pdf_row['category']}] {pdf_row['name']!r}"
                + (f" (closest website name {candidate_key[0]!r}, WRatio {score:.1f} - not a confident word-level match)"
                   if candidate_key else " (no compatible website category)")
            )
            continue

        matched_pdf_count += 1
        log(f"MATCHED    [{pdf_row['category']}] {pdf_row['name']!r} -> {matched_key[0]!r} ({matched_key[1]}), score {score:.1f}")

        pdf_price = pdf_row.get("price")
        if pdf_price is not None:
            for website_row in groups[matched_key]:
                website_price = website_row.get("price")
                if website_price is not None and website_price != pdf_price:
                    price_conflicts.append({
                        "name": pdf_row["name"],
                        "category": pdf_row["category"],
                        "variant": website_row.get("variant"),
                        "website_price": website_price,
                        "pdf_price": pdf_price,
                    })

    unique_products = []
    for key in order:
        for row in groups[key]:
            unique_products.append(drop_source(row))
    for row in unmatched_pdf_rows:
        unique_products.append(drop_source(row))

    (DATA_DIR / "unique_products.json").write_text(
        json.dumps(unique_products, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DATA_DIR / "price_conflicts.json").write_text(
        json.dumps(price_conflicts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DATA_DIR / "needs_manual_review.json").write_text(
        json.dumps(manual_review_output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"website rows: {len(website_rows)}")
    print(f"pdf rows: {len(pdf_rows) + len(manual_review_rows)} (pulled for manual review: {len(manual_review_rows)})")
    print(f"pdf rows merged as duplicates: {matched_pdf_count}")
    print(f"pdf rows kept as unique (unmatched): {len(unmatched_pdf_rows)}")
    print(f"price conflicts flagged: {len(price_conflicts)}")
    print(f"final unique product rows: {len(unique_products)}")


if __name__ == "__main__":
    main()
