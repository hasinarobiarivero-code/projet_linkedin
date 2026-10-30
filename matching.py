"""Helpers for matching LinkedIn company profiles to company records."""

import re
import unicodedata
import urllib.parse


STOP_WORDS = {
    "sarl", "sas", "sasu", "sa", "sci", "eurl", "snc", "gmbh", "ltd", "llc", "inc",
    "corp", "co", "cie", "de", "la", "le", "les", "du", "des", "et", "and", "the",
    "en", "france", "group", "groupe", "d", "l", "b", "v", "scp", "selarl", "earl"
}

FOREIGN_COUNTRIES = {
    "united states", "usa", "etats-unis", "india", "inde", "united kingdom",
    "royaume-uni", "london", "california", "new york", "texas", "florida",
    "australia", "australie", "canada", "brazil", "bresil", "singapore"
}


def strip_accents(text: str) -> str:
    """Remove accents and lowercase text for robust comparison."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def extract_distinctive_tokens(text: str) -> set[str]:
    """Extract distinctive name tokens, excluding stop words and legal forms."""
    words = re.findall(r"[a-z0-9]+", strip_accents(text))
    return {word for word in words if word not in STOP_WORDS and len(word) > 1}


def clean_company_name(name: str) -> str:
    """Clean a company name for LinkedIn/Google searches."""
    if not name:
        return ""
    cleaned = re.sub(r"\(.*?\)|\[.*?\]", "", name)
    legal_suffixes = [
        r"\bS\.?A\.?R\.?L\.?\b",
        r"\bS\.?A\.?S\.?U?\.?\b",
        r"\bS\.?A\.?\b",
        r"\bE\.?U\.?R\.?L\.?\b",
        r"\bS\.?N\.?C\.?\b",
        r"\bS\.?C\.?I\.?\b",
        r"\bL\.?T\.?D\.?\b",
        r"\bL\.?L\.?C\.?\b",
        r"\bI\.?N\.?C\.?\b",
        r"\bG\.?M\.?B\.?H\.?\b",
        r"\bB\.?V\.?\b",
        r"\bS\.?P\.?A\.?\b",
        r"\bS\.?L\.?\b",
    ]
    for pattern in legal_suffixes:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[-–|/\\].*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or name.strip()


def clean_linkedin_title(title: str) -> str:
    """Remove LinkedIn suffixes from a company title."""
    cleaned = re.sub(r"\s*[-|:]\s*LinkedIn.*$", "", title, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s*[-|:]\s*(Présentation|Overview|Accueil|Avis|Jobs|Emplois).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def calculate_precision_resemblance(cand: dict, company: dict) -> tuple[float, dict]:
    """
    Calculate a company-profile match percentage from names, domains, and location.

    The returned details include whether the score passes the existing validation
    threshold, the name F1 score, and whether a domain matched.
    """
    cand_name = strip_accents(clean_linkedin_title(cand.get("name") or ""))
    raw_url = urllib.parse.unquote(cand.get("link") or "")
    cand_url = strip_accents(raw_url)
    cand_desc = strip_accents(cand.get("snippet") or "")
    cand_slug_match = re.search(r"/company/([a-z0-9_\-%]+)", cand_url)
    cand_slug = urllib.parse.unquote(cand_slug_match.group(1)) if cand_slug_match else ""

    comp_name = strip_accents(company.get("companyName") or "")
    trade_name = strip_accents(company.get("tradeName") or "")
    country = (company.get("countryCode") or "fr").lower().strip()
    street = strip_accents(company.get("street") or company.get("streetName") or "")
    location = strip_accents(company.get("location") or company.get("region") or "")
    domains = [strip_accents(domain) for domain in company.get("domains") or []]
    comp_url = strip_accents(company.get("url") or "")
    if comp_url and comp_url not in domains:
        domains.append(comp_url)

    best_f1 = 0.0
    cand_tokens = extract_distinctive_tokens(cand_name)
    slug_tokens = extract_distinctive_tokens(cand_slug.replace("-", " "))
    all_cand_tokens = cand_tokens or slug_tokens

    for target in [comp_name, trade_name]:
        if not target:
            continue
        comp_tokens = extract_distinctive_tokens(target)
        if not comp_tokens:
            continue

        inter = comp_tokens & all_cand_tokens
        if not inter:
            continue

        cov_comp = len(inter) / len(comp_tokens)
        cov_cand = len(inter) / len(all_cand_tokens) if all_cand_tokens else 0
        f1 = (2 * cov_comp * cov_cand) / (cov_comp + cov_cand) if (cov_comp + cov_cand) > 0 else 0
        if f1 > best_f1:
            best_f1 = f1

    score = best_f1 * 70.0

    domain_match = False
    for domain in domains:
        clean_domain = re.sub(r"^https?://(?:www\.)?|/.*$", "", domain)
        domain_name = clean_domain.split(".")[0]
        domain_tokens = extract_distinctive_tokens(domain_name)
        if domain_tokens and (
            domain_tokens.issubset(cand_tokens | slug_tokens)
            or domain_name in cand_slug
        ):
            score += 20.0
            domain_match = True
            break

    cand_full_text = f"{cand_desc} {cand_name}"
    if country == "fr":
        is_foreign = any(country_name in cand_full_text for country_name in FOREIGN_COUNTRIES)
        mentions_france = any(
            place in cand_full_text
            for place in [
                "france", "paris", "lyon", "marseille", "toulouse", "bordeaux",
                "nantes", "lille", "rennes", "strasbourg", "montpellier",
            ]
        )
        if is_foreign and not mentions_france:
            score -= 40.0

    if location and len(location) > 2 and location in cand_full_text:
        score += 5.0

    if street and len(street) > 3:
        words = [word for word in re.split(r"\W+", street) if len(word) > 3]
        if any(word in cand_full_text for word in words):
            score += 5.0

    final_score = max(0.0, min(round(score, 1), 100.0))
    is_valid = final_score >= 65.0 and (
        best_f1 >= 0.65 or (domain_match and best_f1 >= 0.50)
    )

    return final_score, {
        "is_valid": is_valid,
        "name_f1": round(best_f1, 2),
        "domain_match": domain_match,
    }