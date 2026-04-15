"""
Translation AI MCP Server
Language tools powered by MEOK AI Labs.
"""


import sys, os
sys.path.insert(0, os.path.expanduser('~/clawd/meok-labs-engine/shared'))
from auth_middleware import check_access

import time
import re
import unicodedata
from collections import defaultdict, Counter
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("translation-ai", instructions="MEOK AI Labs MCP Server")

_call_counts: dict[str, list[float]] = defaultdict(list)
FREE_TIER_LIMIT = 50
WINDOW = 86400


def _check_rate_limit(tool_name: str) -> None:
    now = time.time()
    _call_counts[tool_name] = [t for t in _call_counts[tool_name] if now - t < WINDOW]
    if len(_call_counts[tool_name]) >= FREE_TIER_LIMIT:
        raise ValueError(f"Rate limit exceeded for {tool_name}. Free tier: {FREE_TIER_LIMIT}/day.")
    _call_counts[tool_name].append(now)


# Character range-based language detection
SCRIPT_RANGES = {
    "latin": (0x0000, 0x024F),
    "cyrillic": (0x0400, 0x04FF),
    "greek": (0x0370, 0x03FF),
    "arabic": (0x0600, 0x06FF),
    "hebrew": (0x0590, 0x05FF),
    "devanagari": (0x0900, 0x097F),
    "thai": (0x0E00, 0x0E7F),
    "cjk": (0x4E00, 0x9FFF),
    "hangul": (0xAC00, 0xD7AF),
    "hiragana": (0x3040, 0x309F),
    "katakana": (0x30A0, 0x30FF),
}

# Common words for language identification within Latin script
LANGUAGE_MARKERS = {
    "en": ["the", "is", "are", "was", "were", "have", "has", "been", "would", "could", "should", "with", "this", "that", "from"],
    "fr": ["le", "la", "les", "des", "est", "sont", "avec", "dans", "pour", "une", "que", "qui", "nous", "vous", "aussi"],
    "de": ["der", "die", "das", "ist", "und", "ein", "eine", "nicht", "mit", "auf", "den", "dem", "sich", "werden", "auch"],
    "es": ["el", "la", "los", "las", "es", "son", "con", "para", "una", "que", "por", "como", "pero", "del", "esta"],
    "it": ["il", "lo", "la", "gli", "sono", "con", "per", "una", "che", "non", "come", "del", "della", "questo", "anche"],
    "pt": ["o", "a", "os", "as", "com", "para", "uma", "que", "por", "como", "mas", "nao", "esta", "pelo", "mais"],
    "nl": ["de", "het", "een", "van", "is", "dat", "niet", "met", "voor", "zijn", "dit", "ook", "maar", "nog", "als"],
    "sv": ["och", "att", "det", "som", "den", "med", "har", "kan", "inte", "var", "ett", "jag", "han", "hon", "ska"],
    "pl": ["jest", "nie", "tak", "jak", "ale", "czy", "dla", "ten", "pod", "nad", "bez", "przy", "przez"],
    "tr": ["bir", "ve", "bu", "ile", "icin", "var", "olan", "gibi", "daha", "sonra", "kadar", "hem"],
}

# Common word translations for basic translation
BASIC_DICT = {
    "en-fr": {"hello": "bonjour", "goodbye": "au revoir", "yes": "oui", "no": "non", "please": "s'il vous plait",
              "thank you": "merci", "good": "bon", "bad": "mauvais", "water": "eau", "food": "nourriture"},
    "en-de": {"hello": "hallo", "goodbye": "auf wiedersehen", "yes": "ja", "no": "nein", "please": "bitte",
              "thank you": "danke", "good": "gut", "bad": "schlecht", "water": "wasser", "food": "essen"},
    "en-es": {"hello": "hola", "goodbye": "adios", "yes": "si", "no": "no", "please": "por favor",
              "thank you": "gracias", "good": "bueno", "bad": "malo", "water": "agua", "food": "comida"},
    "en-it": {"hello": "ciao", "goodbye": "arrivederci", "yes": "si", "no": "no", "please": "per favore",
              "thank you": "grazie", "good": "buono", "bad": "cattivo", "water": "acqua", "food": "cibo"},
    "en-pt": {"hello": "ola", "goodbye": "adeus", "yes": "sim", "no": "nao", "please": "por favor",
              "thank you": "obrigado", "good": "bom", "bad": "mau", "water": "agua", "food": "comida"},
    "en-ja": {"hello": "konnichiwa", "goodbye": "sayonara", "yes": "hai", "no": "iie", "please": "onegaishimasu",
              "thank you": "arigatou", "good": "ii", "bad": "warui"},
}


@mcp.tool()
def translate_text(
    text: str,
    source_language: str = "auto",
    target_language: str = "en", api_key: str = "") -> dict:
    """Translate text between languages using built-in dictionary and word mapping.

    Args:
        text: Text to translate
        source_language: Source language code (e.g. en, fr, de, es) or 'auto' for detection
        target_language: Target language code
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("translate_text")

    if source_language == "auto":
        detection = _detect_language_internal(text)
        source_language = detection["language"]

    src = source_language.lower()[:2]
    tgt = target_language.lower()[:2]

    if src == tgt:
        return {"translated_text": text, "source_language": src, "target_language": tgt, "note": "Source and target languages are the same"}

    # Try direct dictionary
    dict_key = f"{src}-{tgt}"
    reverse_key = f"{tgt}-{src}"

    word_dict = BASIC_DICT.get(dict_key, {})
    if not word_dict and reverse_key in BASIC_DICT:
        word_dict = {v: k for k, v in BASIC_DICT[reverse_key].items()}

    # Translate via English as pivot if needed
    if not word_dict and src != "en" and tgt != "en":
        src_to_en = BASIC_DICT.get(f"{src}-en", {v: k for k, v in BASIC_DICT.get(f"en-{src}", {}).items()})
        en_to_tgt = BASIC_DICT.get(f"en-{tgt}", {})
        if src_to_en and en_to_tgt:
            word_dict = {k: en_to_tgt.get(v, v) for k, v in src_to_en.items()}

    words = text.lower().split()
    translated_words = []
    translated_count = 0

    for word in words:
        clean = re.sub(r'[^\w]', '', word)
        if clean in word_dict:
            translated_words.append(word_dict[clean])
            translated_count += 1
        else:
            translated_words.append(word)

    translated_text = " ".join(translated_words)
    coverage = translated_count / len(words) * 100 if words else 0

    return {
        "original_text": text,
        "translated_text": translated_text,
        "source_language": src,
        "target_language": tgt,
        "word_count": len(words),
        "words_translated": translated_count,
        "coverage": f"{coverage:.0f}%",
        "note": "Basic dictionary translation. For production use, integrate with a full translation API (DeepL, Google Translate)." if coverage < 80 else "Translation complete.",
        "confidence": "high" if coverage > 80 else "medium" if coverage > 40 else "low",
    }


def _detect_language_internal(text: str) -> dict:
    chars = [c for c in text if not c.isspace() and not c.isdigit()]
    if not chars:
        return {"language": "unknown", "confidence": 0}

    script_counts = Counter()
    for c in chars:
        cp = ord(c)
        for script, (start, end) in SCRIPT_RANGES.items():
            if start <= cp <= end:
                script_counts[script] += 1
                break

    if not script_counts:
        return {"language": "unknown", "confidence": 0}

    dominant_script = script_counts.most_common(1)[0][0]

    if dominant_script == "cjk":
        return {"language": "zh", "script": "cjk", "confidence": 85}
    elif dominant_script == "hangul":
        return {"language": "ko", "script": "hangul", "confidence": 90}
    elif dominant_script in ("hiragana", "katakana"):
        return {"language": "ja", "script": dominant_script, "confidence": 90}
    elif dominant_script == "cyrillic":
        return {"language": "ru", "script": "cyrillic", "confidence": 75}
    elif dominant_script == "arabic":
        return {"language": "ar", "script": "arabic", "confidence": 80}
    elif dominant_script == "devanagari":
        return {"language": "hi", "script": "devanagari", "confidence": 85}
    elif dominant_script == "thai":
        return {"language": "th", "script": "thai", "confidence": 90}
    elif dominant_script == "greek":
        return {"language": "el", "script": "greek", "confidence": 85}
    elif dominant_script == "hebrew":
        return {"language": "he", "script": "hebrew", "confidence": 85}

    # Latin script - use word markers
    words = set(re.findall(r'\b\w+\b', text.lower()))
    scores = {}
    for lang, markers in LANGUAGE_MARKERS.items():
        match_count = sum(1 for m in markers if m in words)
        scores[lang] = match_count / len(markers) * 100

    if scores:
        best = max(scores, key=scores.get)
        return {"language": best, "script": "latin", "confidence": round(scores[best])}

    return {"language": "en", "script": "latin", "confidence": 30}


@mcp.tool()
def detect_language(
    text: str,
    detailed: bool = True, api_key: str = "") -> dict:
    """Detect the language of input text using script and word analysis.

    Args:
        text: Text to analyze
        detailed: Include detailed breakdown
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("detect_language")

    result = _detect_language_internal(text)

    language_names = {
        "en": "English", "fr": "French", "de": "German", "es": "Spanish",
        "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish",
        "pl": "Polish", "tr": "Turkish", "ru": "Russian", "ar": "Arabic",
        "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "hi": "Hindi",
        "th": "Thai", "el": "Greek", "he": "Hebrew",
    }

    result["language_name"] = language_names.get(result["language"], result["language"])
    result["text_length"] = len(text)
    result["word_count"] = len(text.split())

    if detailed:
        words = set(re.findall(r'\b\w+\b', text.lower()))
        all_scores = {}
        for lang, markers in LANGUAGE_MARKERS.items():
            match_count = sum(1 for m in markers if m in words)
            if match_count > 0:
                all_scores[language_names.get(lang, lang)] = f"{match_count}/{len(markers)} markers"
        result["marker_analysis"] = all_scores

    return result


@mcp.tool()
def check_grammar(
    text: str,
    language: str = "en", api_key: str = "") -> dict:
    """Check text for common grammar and style issues.

    Args:
        text: Text to check
        language: Language code (currently supports 'en' for English)
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("check_grammar")

    issues = []
    sentences = re.split(r'[.!?]+', text)
    words = text.split()

    # Double spaces
    double_spaces = [(m.start(), m.end()) for m in re.finditer(r'  +', text)]
    for pos_start, pos_end in double_spaces:
        issues.append({"type": "formatting", "message": "Double space detected", "position": pos_start, "severity": "minor"})

    # Repeated words
    for i in range(len(words) - 1):
        if words[i].lower() == words[i + 1].lower() and words[i].lower() not in ("that", "had", "very"):
            issues.append({"type": "repetition", "message": f"Repeated word: '{words[i]}'", "severity": "warning"})

    # Common mistakes (English)
    if language == "en":
        mistake_patterns = [
            (r'\btheir\s+(?:is|was|are)\b', "Possible confusion: 'their' (possessive) vs 'there' (location)"),
            (r"\byour\s+(?:a|an|the|going|doing|coming)\b", "Possible confusion: 'your' (possessive) vs 'you're' (you are)"),
            (r"\bits\s+(?:a|an|the|been|going)\b", "Check: should this be 'it's' (it is)?"),
            (r"\beffect\s+(?:the|a|my|your)\b", "Check: 'effect' (noun) vs 'affect' (verb)"),
            (r"\bthen\b.*\bthen\b", "Consider varying word choice: 'then' used multiple times"),
            (r"\bcould of\b", "Error: 'could of' should be 'could have'"),
            (r"\bshould of\b", "Error: 'should of' should be 'should have'"),
            (r"\bwould of\b", "Error: 'would of' should be 'would have'"),
            (r"\balot\b", "Error: 'alot' should be 'a lot'"),
            (r"\bdefinately\b", "Spelling: 'definately' should be 'definitely'"),
            (r"\bseperate\b", "Spelling: 'seperate' should be 'separate'"),
            (r"\boccured\b", "Spelling: 'occured' should be 'occurred'"),
            (r"\brecieve\b", "Spelling: 'recieve' should be 'receive'"),
            (r"\buntill\b", "Spelling: 'untill' should be 'until'"),
        ]

        for pattern, message in mistake_patterns:
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            for m in matches:
                issues.append({"type": "grammar", "message": message, "position": m.start(), "text": m.group(), "severity": "error"})

    # Sentence-level checks
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent.split()) > 40:
            issues.append({"type": "style", "message": f"Long sentence ({len(sent.split())} words). Consider splitting.", "severity": "suggestion"})
        if sent[0].islower() and sent != sentences[0].strip():
            issues.append({"type": "capitalization", "message": "Sentence should start with a capital letter", "text": sent[:30], "severity": "warning"})

    # Passive voice detection (simple heuristic)
    passive_pattern = r'\b(?:is|are|was|were|been|be|being)\s+\w+ed\b'
    passive_matches = re.findall(passive_pattern, text, re.IGNORECASE)
    if len(passive_matches) > 2:
        issues.append({"type": "style", "message": f"Frequent passive voice detected ({len(passive_matches)} instances). Consider active voice.", "severity": "suggestion"})

    score = max(0, 100 - len([i for i in issues if i["severity"] == "error"]) * 10 - len([i for i in issues if i["severity"] == "warning"]) * 3 - len([i for i in issues if i["severity"] == "suggestion"]))

    return {
        "text_length": len(text),
        "word_count": len(words),
        "sentence_count": len([s for s in sentences if s.strip()]),
        "issues_found": len(issues),
        "grammar_score": score,
        "issues": issues,
        "summary": {
            "errors": len([i for i in issues if i["severity"] == "error"]),
            "warnings": len([i for i in issues if i["severity"] == "warning"]),
            "suggestions": len([i for i in issues if i["severity"] == "suggestion"]),
            "minor": len([i for i in issues if i["severity"] == "minor"]),
        },
    }


@mcp.tool()
def adjust_tone(
    text: str,
    target_tone: str = "professional", api_key: str = "") -> dict:
    """Analyze text tone and provide recommendations for adjustment.

    Args:
        text: Text to analyze
        target_tone: Desired tone: professional, casual, formal, friendly, academic, persuasive
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("adjust_tone")

    words = text.lower().split()
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]

    # Tone indicators
    casual_words = {"gonna", "wanna", "gotta", "kinda", "sorta", "yeah", "nope", "hey", "ok", "cool", "awesome", "stuff", "things", "like", "basically", "literally"}
    formal_words = {"therefore", "furthermore", "moreover", "consequently", "nevertheless", "henceforth", "herein", "whereby", "thus", "hence"}
    emotional_words = {"amazing", "terrible", "incredible", "awful", "fantastic", "horrible", "wonderful", "disgusting", "brilliant", "dreadful"}

    casual_count = sum(1 for w in words if w in casual_words)
    formal_count = sum(1 for w in words if w in formal_words)
    emotional_count = sum(1 for w in words if w in emotional_words)
    exclamation_count = text.count("!")
    question_count = text.count("?")
    avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences) if sentences else 0
    contraction_count = len(re.findall(r"\w+'\w+", text))

    # Current tone assessment
    if casual_count > formal_count and contraction_count > 2:
        current_tone = "casual"
    elif formal_count > casual_count and avg_sentence_length > 20:
        current_tone = "formal"
    elif exclamation_count > 2 or emotional_count > 3:
        current_tone = "enthusiastic"
    elif avg_sentence_length > 25:
        current_tone = "academic"
    else:
        current_tone = "neutral"

    # Recommendations based on target tone
    tone_tips = {
        "professional": {
            "do": ["Use clear, concise language", "Maintain a respectful tone", "Use industry-appropriate terminology", "Structure with clear headings/sections"],
            "avoid": ["Slang and colloquialisms", "Excessive exclamation marks", "Overly casual contractions", "Emotional language"],
            "sentence_length": "15-25 words per sentence",
        },
        "casual": {
            "do": ["Use contractions (it's, you're, we're)", "Write short, punchy sentences", "Use conversational language", "Address the reader directly (you)"],
            "avoid": ["Jargon and overly formal language", "Long, complex sentences", "Passive voice", "Stuffy phrasing"],
            "sentence_length": "8-15 words per sentence",
        },
        "formal": {
            "do": ["Use complete words (do not vs don't)", "Employ precise vocabulary", "Use passive voice where appropriate", "Maintain objectivity"],
            "avoid": ["Contractions", "Colloquialisms", "First person (I, we) where possible", "Informal transitions"],
            "sentence_length": "18-30 words per sentence",
        },
        "friendly": {
            "do": ["Use warm, inviting language", "Include personal touches", "Ask questions to engage", "Use 'we' and 'you' frequently"],
            "avoid": ["Cold or impersonal language", "Overly technical jargon", "Negative framing", "Long paragraphs"],
            "sentence_length": "10-18 words per sentence",
        },
        "academic": {
            "do": ["Cite evidence and sources", "Use hedging language (suggests, indicates)", "Define technical terms", "Use third person"],
            "avoid": ["Absolute claims without evidence", "Informal language", "Anecdotal evidence", "Emotional appeals"],
            "sentence_length": "20-30 words per sentence",
        },
        "persuasive": {
            "do": ["Use power words (proven, guaranteed, exclusive)", "Include social proof", "Create urgency", "Use active voice"],
            "avoid": ["Weak qualifiers (maybe, perhaps)", "Passive voice", "Long-winded explanations", "Negative framing"],
            "sentence_length": "10-20 words per sentence",
        },
    }

    tips = tone_tips.get(target_tone, tone_tips["professional"])

    specific_changes = []
    if target_tone == "professional" and casual_count > 0:
        specific_changes.append(f"Replace {casual_count} casual words/phrases with professional alternatives")
    if target_tone in ("formal", "academic") and contraction_count > 0:
        specific_changes.append(f"Expand {contraction_count} contractions to full forms")
    if target_tone == "casual" and formal_count > 0:
        specific_changes.append(f"Simplify {formal_count} formal words")
    if target_tone in ("casual", "friendly") and avg_sentence_length > 20:
        specific_changes.append("Break long sentences into shorter ones")
    if target_tone in ("professional", "formal") and exclamation_count > 1:
        specific_changes.append(f"Reduce exclamation marks (found {exclamation_count})")

    return {
        "current_tone": current_tone,
        "target_tone": target_tone,
        "tone_match": current_tone == target_tone,
        "analysis": {
            "casual_indicators": casual_count,
            "formal_indicators": formal_count,
            "emotional_words": emotional_count,
            "contractions": contraction_count,
            "exclamations": exclamation_count,
            "avg_sentence_length": round(avg_sentence_length, 1),
        },
        "recommendations": tips,
        "specific_changes": specific_changes,
    }


@mcp.tool()
def validate_localization(
    strings: list[dict],
    target_locale: str = "en-US", api_key: str = "") -> dict:
    """Validate localized strings for common internationalization issues.

    Args:
        strings: List of dicts with keys: key, value, source_locale (optional)
        target_locale: Target locale code (e.g. en-US, fr-FR, de-DE, ja-JP)
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("validate_localization")

    issues = []
    warnings = []
    passed = []

    locale_info = {
        "en-US": {"date_format": "MM/DD/YYYY", "number_sep": ",", "decimal": ".", "currency_pos": "before", "rtl": False},
        "en-GB": {"date_format": "DD/MM/YYYY", "number_sep": ",", "decimal": ".", "currency_pos": "before", "rtl": False},
        "de-DE": {"date_format": "DD.MM.YYYY", "number_sep": ".", "decimal": ",", "currency_pos": "after", "rtl": False},
        "fr-FR": {"date_format": "DD/MM/YYYY", "number_sep": " ", "decimal": ",", "currency_pos": "after", "rtl": False},
        "ja-JP": {"date_format": "YYYY/MM/DD", "number_sep": ",", "decimal": ".", "currency_pos": "before", "rtl": False},
        "ar-SA": {"date_format": "DD/MM/YYYY", "number_sep": ",", "decimal": ".", "currency_pos": "after", "rtl": True},
        "he-IL": {"date_format": "DD/MM/YYYY", "number_sep": ",", "decimal": ".", "currency_pos": "after", "rtl": True},
    }

    locale_config = locale_info.get(target_locale, locale_info.get("en-US"))

    for s in strings:
        key = s.get("key", "unknown")
        value = s.get("value", "")
        source = s.get("source_locale", "en-US")

        # Check for hardcoded formats
        if re.search(r'\d{1,2}/\d{1,2}/\d{4}', value):
            issues.append({"key": key, "issue": "Hardcoded date format detected. Use locale-aware formatting.", "severity": "error"})

        # Check for concatenated strings (common i18n anti-pattern)
        if re.search(r'\b\w+\s*\+\s*\w+', value):
            issues.append({"key": key, "issue": "Possible string concatenation. Use parameterized strings for proper word order.", "severity": "warning"})

        # Check for placeholders
        placeholders = re.findall(r'\{[\w.]+\}|%[sd@]|\$\{[\w.]+\}', value)
        if placeholders:
            passed.append({"key": key, "note": f"Contains {len(placeholders)} placeholder(s): {placeholders}"})

        # Check for hardcoded currency symbols
        if re.search(r'[$\u00a3\u20ac\u00a5]', value):
            warnings.append({"key": key, "issue": "Hardcoded currency symbol. Use locale-aware currency formatting.", "severity": "warning"})

        # Check for untranslated content (source and target the same)
        if source != target_locale and value and all(ord(c) < 128 for c in value if c.isalpha()):
            if target_locale.startswith(("ja", "zh", "ko", "ar", "he", "th", "hi")):
                warnings.append({"key": key, "issue": "String appears to be in Latin script but target locale uses a different script. May be untranslated.", "severity": "warning"})

        # Length check (translations often expand)
        expansion_rates = {"de": 1.3, "fr": 1.2, "es": 1.2, "it": 1.15, "ja": 0.6, "zh": 0.6, "ko": 0.8}
        lang = target_locale[:2]
        expected_expansion = expansion_rates.get(lang, 1.0)
        if len(value) > 100 and expected_expansion > 1.1:
            warnings.append({"key": key, "issue": f"Long string ({len(value)} chars). {lang.upper()} translations typically expand {expected_expansion}x. Check UI layout.", "severity": "info"})

        # RTL check
        if locale_config["rtl"] and not any(0x0590 <= ord(c) <= 0x08FF for c in value if c.isalpha()):
            if len(value) > 3:
                warnings.append({"key": key, "issue": "Target locale is RTL but string contains no RTL characters. May be untranslated.", "severity": "warning"})

        if not any(i["key"] == key for i in issues) and not any(w["key"] == key for w in warnings):
            passed.append({"key": key, "status": "OK"})

    return {
        "target_locale": target_locale,
        "locale_config": locale_config,
        "total_strings": len(strings),
        "errors": len(issues),
        "warnings": len(warnings),
        "passed": len(passed),
        "issues": issues,
        "warnings_list": warnings,
        "validation_score": round((len(passed) / len(strings) * 100) if strings else 100, 1),
    }


if __name__ == "__main__":
    mcp.run()
