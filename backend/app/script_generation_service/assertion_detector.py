import re

ASSERTION_KEYWORDS = ("期望", "出现", "断言", "验证", "应该")

_KEYWORD_PATTERN = re.compile("|".join(re.escape(k) for k in ASSERTION_KEYWORDS))


def matched_assertion_keywords(description: str) -> list[str]:
    text = (description or "").strip()
    if not text:
        return []
    return [kw for kw in ASSERTION_KEYWORDS if kw in text]


def is_assertion_step(description: str) -> bool:
    return bool(matched_assertion_keywords(description))
