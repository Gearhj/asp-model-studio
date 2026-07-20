from __future__ import annotations

import re


BUREAU_PREFIX_PATTERNS = [
    re.compile(r"^(ALL|BCC|BCA|BCX|REV|ILN|IQT|MTA|MTF|AUT|COL|PUB|FIP)\d+$", re.IGNORECASE),
]

BUREAU_SEMANTIC_PATTERN = re.compile(
    r"bureau|fico|credit|tradeline|trade|inquir|delinq|derog|revolv|install|mortgage|bankrupt|public|utilization|thin.?file|risk.?estimate",
    re.IGNORECASE,
)

BUREAU_SPECIAL_VALUES = {
    -1: "No trade history",
    -2: "No recent activity",
    -3: "Inquiry not found",
    -7: "Bureau exception",
    -8: "Frozen, blocked, or unavailable",
    -9: "Unknown or unscorable response",
    96: "Bureau exception",
    97: "Suppressed value",
    98: "Unavailable value",
    99: "Unknown value",
    999: "Unknown value",
    9999: "Unknown value",
}


def name_signals(column: str) -> list[str]:
    signals: list[str] = []
    if any(pattern.search(column) for pattern in BUREAU_PREFIX_PATTERNS):
        signals.append("The variable name matches a configured bureau attribute prefix.")
    if BUREAU_SEMANTIC_PATTERN.search(column):
        signals.append("The variable name contains bureau or credit-attribute terminology.")
    return signals

