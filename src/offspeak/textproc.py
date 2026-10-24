import difflib
import re

from offspeak.commands import apply_voice_commands

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
TRANSCRIPT_TAG_RE = re.compile(r"</?transcript>", re.IGNORECASE)
NON_SPEECH_RE = re.compile(r"\[(BLANK_AUDIO|MUSIC|NOISE|SILENCE|INAUDIBLE)[^\]]*\]|\((music|silence|noise)\)", re.IGNORECASE)


def apply_replacements(text: str, replacements: list[dict]) -> str:
    for r in replacements:
        original, new = r.get("original", ""), r.get("with", "")
        if original:
            pattern = rf"(?<!\w){re.escape(original)}(?!\w)"
            text = re.sub(pattern, lambda _m, new=new: new, text, flags=re.IGNORECASE)
    return text


def clean_transcript(text: str) -> str:
    text = NON_SPEECH_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_llm_output(output: str, transcript: str) -> str:
    output = THINK_RE.sub("", output)
    output = TRANSCRIPT_TAG_RE.sub("", output).strip()
    for q in ('"', "'", "“”", "„“"):
        open_q, close_q = (q, q) if len(q) == 1 else (q[0], q[1])
        if len(output) > 1 and output.startswith(open_q) and output.endswith(close_q) and not transcript.startswith(open_q):
            output = output[1:-1].strip()
    return output


VOWELS = set("aeiouäöüy")


def _same_start(a: str, b: str) -> bool:
    # recognisers often swap a leading vowel ("Ulama" for "Ollama")
    return a[0] == b[0] or (a[0] in VOWELS and b[0] in VOWELS)


def _squeeze(s: str) -> str:
    """Doubled letters sound like single ones: "ollama" -> "olama"."""
    return re.sub(r"(.)\1+", r"\1", s)


def _likeness(a: str, b: str) -> float:
    return max(difflib.SequenceMatcher(None, a, b).ratio(),
               difflib.SequenceMatcher(None, _squeeze(a), _squeeze(b)).ratio())


def _compact(s: str) -> str:
    return re.sub(r"[\s\-]", "", s)


def _distinct_spelling(term: str) -> bool:
    """Short terms are fixed only when their spelling cannot be an ordinary word ("YAML", "OAuth", "npm")."""
    return not re.fullmatch(r"[A-ZÄÖÜ]?[a-zäöüß]+", term) or term.islower()


def correct_vocabulary(text: str, vocabulary: list[str], threshold: float = 0.75) -> str:
    """Snap near-miss spellings ("Databurse", "Data verse") to vocabulary terms."""
    tokens = list(re.finditer(r"\w+", text))
    candidates: list[tuple[float, int, int, str | None]] = []
    for term in vocabulary:
        target = re.sub(r"\W", "", term.lower())
        # short terms are too close to ordinary words ("Teams" vs "Team"): only fix their case ("Yaml" -> "YAML")
        short = len(target) < 6
        if short and not _distinct_spelling(term):
            continue
        n = len(re.findall(r"\w+", term))
        for size in (n, n + 1):
            for i in range(len(tokens) - size + 1):
                window = tokens[i:i + size]
                # words may be joined by spaces or hyphens, or by a dot inside a name ("llama.cpp")
                if any(not re.fullmatch(r"[ \-]*|\.", text[a.end():b.start()]) for a, b in zip(window, window[1:])):
                    continue
                candidate = "".join(t.group() for t in window).lower()
                start, end = window[0].start(), window[-1].end()
                found = text[start:end]
                if candidate == target:
                    # "npm" stays as "Npm" at the start of a sentence; only "NPM" and the like are fixed
                    if short and term.islower() and found == term.capitalize():
                        continue
                    score = 1.0
                elif short or abs(len(candidate) - len(target)) > max(2, len(target) // 5):
                    continue
                elif _same_start(candidate, target):
                    score = _likeness(candidate, target)
                    if score < threshold:
                        continue
                else:
                    # a different first letter needs an otherwise near-identical word ("slang chain" -> "LangChain")
                    score = difflib.SequenceMatcher(None, candidate, target).ratio()
                    if score < 0.88:
                        continue
                # exact hits (also "Power-Platform" for "Power Platform") only reserve their span
                keep = found == term or (candidate == target and " " in term and _compact(found) == _compact(term))
                candidates.append((score, start, end, None if keep else term))
    accepted: list[tuple[int, int, str | None]] = []
    # best match first; among equal ones the longer, so "Fast API" beats "API" and "Azure DevOps" beats "Azure"
    for score, start, end, term in sorted(candidates, key=lambda c: (-c[0], c[1] - c[2])):
        if not any(s < end and start < e for s, e, _ in accepted):
            accepted.append((start, end, term))
    for start, end, term in sorted(accepted, reverse=True):
        if term is not None:
            text = text[:start] + term + text[end:]
    return text


def postprocess(text: str, vocabulary: list[str], replacements: list[dict], commands: list[dict]) -> str:
    """Rule-based clean-up of a raw transcript, in the order the app applies it."""
    return apply_replacements(correct_vocabulary(apply_voice_commands(text, commands), vocabulary), replacements)


def similarity(a: str, b: str) -> float:
    """Word-level similarity in [0, 1]."""
    return difflib.SequenceMatcher(None, re.findall(r"\w+", a.lower()), re.findall(r"\w+", b.lower())).ratio()


def word_count(text: str) -> int:
    return len(text.split())
