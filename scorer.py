"""
scorer.py — Job scoring engine for Job Hunter Agent.

Scores each job 0-100 against a given resume text using:
  - Token overlap between resume and job description
  - Role-title keyword bonuses
  - Location preference bonuses
  - Visa/sponsorship bonus for international roles
  - Seniority penalty (avoids senior-only roles for freshers)
  - Remote-work detection
  - Visa/relocation keyword detection

No LLM is used; all scoring is deterministic and reproducible.
"""

import json
import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_ROLES = [
    "software engineer", "sde", "software developer", "developer",
    "backend", "full stack", "fullstack", "python developer",
    "java developer", "frontend developer", "frontend engineer",
    "ai engineer", "ml engineer", "machine learning", "data engineer",
    "full-stack", "backend engineer",
]

SENIOR_KEYWORDS = [
    "senior", "sr.", "sr ", "lead ", "principal", "staff engineer",
    "engineering manager", "head of", "director", "vp of",
    "10+ years", "8+ years", "7+ years",
]

LOCATION_SCORES = {
    "bengaluru": 20, "bangalore": 20,
    "mysuru": 15, "mysore": 15,
    "pune": 10, "mumbai": 10,
    "india": 5,
}

VISA_KEYWORDS = [
    "visa sponsorship", "visa support", "relocation support",
    "relocation assistance", "we sponsor", "we will sponsor",
    "h-1b", "h1b", "work authorization", "right to work provided",
]

REMOTE_KEYWORDS = [
    "remote", "work from home", "wfh", "fully remote", "hybrid",
    "distributed team",
]

FRESHER_FRIENDLY = [
    "fresher", "fresh graduate", "entry level", "entry-level",
    "0-2 years", "0-1 year", "junior", "associate", "trainee",
    "graduate engineer", "campus",
]

# Maps experience tier label → (regex patterns, keyword phrases)
# Tiers: "fresher" → 0-1 yr, "junior" → 1-3 yr, "mid" → 3-6 yr, "senior" → 6+ yr
_EXPERIENCE_TIERS: list[tuple[str, list[str], list[str]]] = [
    ("fresher", [
        r"0\s*[-–]\s*[12]\s*(?:years?|yrs?)",
        r"less\s+than\s+1\s*(?:year|yr)",
    ], [
        "fresher", "fresh graduate", "entry level", "entry-level",
        "no experience", "0 years", "graduate engineer", "trainee", "campus hire",
    ]),
    ("junior", [
        r"[12]\s*[-–]\s*[34]\s*(?:years?|yrs?)",
        r"1\s*(?:year|yr)\s+(?:of\s+)?experience",
        r"2\s*(?:years?|yrs?)\s+(?:of\s+)?experience",
    ], [
        "junior", "associate engineer", "associate developer",
        "1-3 years", "2-3 years",
    ]),
    ("mid", [
        r"[34]\s*[-–]\s*[56]\s*(?:years?|yrs?)",
        r"3\s*[-–]\s*5\s*(?:years?|yrs?)",
        r"[345]\s*(?:years?|yrs?)\s+(?:of\s+)?experience",
    ], [
        "3+ years", "4+ years", "5+ years",
        "mid-level", "mid level",
    ]),
    ("senior", [
        r"[6-9]\s*[-–]\s*\d+\s*(?:years?|yrs?)",
        r"1[0-9]\+?\s*(?:years?|yrs?)",
        r"[6789]\+\s*(?:years?|yrs?)",
        r"6\s*(?:years?|yrs?)\s+(?:of\s+)?experience",
    ], [
        "senior", "staff engineer", "principal", "lead engineer",
        "7+ years", "8+ years", "10+ years",
    ]),
]

# Skills likely on target resumes
SKILL_KEYWORDS = {
    "python", "java", "javascript", "typescript", "react", "spring",
    "django", "flask", "fastapi", "sql", "mysql", "postgres", "mongodb",
    "docker", "kubernetes", "git", "aws", "gcp", "azure", "linux",
    "rest", "api", "microservices", "ci/cd", "tensorflow", "pytorch",
    "scikit", "pandas", "numpy", "html", "css", "node", "express",
    "redis", "kafka", "rabbitmq", "graphql", "selenium", "junit",
    "pytest", "agile", "scrum",
}


def _tokenize(text: str) -> set[str]:
    """Return lower-cased word tokens from text."""
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9+#._]{1,}", text.lower()))


def detect_visa_sponsorship(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in VISA_KEYWORDS)


def detect_remote(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in REMOTE_KEYWORDS)


def detect_fresher_friendly(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in FRESHER_FRIENDLY)


def detect_experience_level(text: str) -> str:
    """
    Detect the required experience level from job text.
    Returns one of: 'fresher', 'junior', 'mid', 'senior', or '' (unknown).
    Checks from most-specific (fresher) to broadest (senior) so that
    a job saying '0-2 years' isn't mis-classified as 'senior'.
    """
    low = text.lower()
    for tier, patterns, keywords in _EXPERIENCE_TIERS:
        if any(kw in low for kw in keywords):
            return tier
        if any(re.search(pat, low) for pat in patterns):
            return tier
    return ""



def detect_senior_only(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in SENIOR_KEYWORDS) and not detect_fresher_friendly(low)


def extract_tags(title: str, description: str) -> list[str]:
    combined = (title + " " + description).lower()
    tags = []
    for role in TARGET_ROLES:
        if role in combined:
            tags.append(role)
    if detect_remote(combined):
        tags.append("remote")
    if detect_visa_sponsorship(combined):
        tags.append("visa-sponsorship")
    if detect_fresher_friendly(combined):
        tags.append("fresher-friendly")
    return list(dict.fromkeys(tags))  # deduplicate, preserve order


def score_job(job: dict, resume_text: str) -> int:
    """
    Score a job against resume text. Returns 0-100.

    Breakdown:
      - Token overlap (resume ∩ job description / job tokens): up to 40 pts
      - Skill keyword match (target skills found in job): up to 20 pts
      - Role title match: +15
      - Location bonus: up to +20
      - Fresher-friendly: +5
      - Visa sponsorship (international): +5
      - Senior-only penalty: -25
    """
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    loc = (job.get("location") or "").lower()
    combined = title + " " + desc

    resume_tokens = _tokenize(resume_text)
    job_tokens = _tokenize(combined)

    # Token overlap component (capped at 40)
    if job_tokens:
        overlap = len(resume_tokens & job_tokens) / max(1, len(job_tokens))
        token_score = min(40, round(overlap * 160))
    else:
        token_score = 0

    # Skill match component (capped at 20)
    matched_skills = SKILL_KEYWORDS & _tokenize(combined)
    skill_score = min(20, len(matched_skills) * 2)

    # Role title bonus
    role_bonus = 15 if any(r in title for r in TARGET_ROLES) else 0

    # Location bonus
    loc_bonus = 0
    for kw, pts in LOCATION_SCORES.items():
        if kw in loc:
            loc_bonus = max(loc_bonus, pts)

    # Fresher-friendly bonus
    fresher_bonus = 5 if detect_fresher_friendly(combined) else 0

    # Visa/sponsorship bonus (only helpful for international roles)
    visa_bonus = 5 if detect_visa_sponsorship(combined) else 0

    # Senior penalty
    senior_penalty = -25 if detect_senior_only(combined) else 0

    total = (token_score + skill_score + role_bonus + loc_bonus
             + fresher_bonus + visa_bonus + senior_penalty)
    return max(0, min(100, total))


def best_resume_match(job: dict, resumes: dict[str, str]) -> tuple[int, str]:
    """
    Given a job and a dict of {resume_name: resume_text}, return
    (best_score, best_resume_name).
    """
    if not resumes:
        return 0, ""
    ranked = sorted(
        ((score_job(job, text), name) for name, text in resumes.items()),
        reverse=True,
    )
    return ranked[0]
