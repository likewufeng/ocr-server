def normalize_known_admin_text(text: str) -> str:
    """修正业务中已知行政区划的 OCR 误识别。"""
    if not text:
        return ""

    normalized = text.strip().replace(" ", "")
    exact_corrections = {
        "关池县公安局": "渑池县公安局",
        "池县公安局": "渑池县公安局",
        "林旗安局": "巴林右旗公安局",
    }
    if normalized in exact_corrections:
        return exact_corrections[normalized]

    phrase_corrections = {
        "淹池县": "渑池县",
        "关池县": "渑池县",
        "绳池县": "渑池县",
        "混池县": "渑池县",
    }

    for wrong, right in phrase_corrections.items():
        normalized = normalized.replace(wrong, right)

    return normalized
