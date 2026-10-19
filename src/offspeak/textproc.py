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


def correct_vocabulary(text: str, vocabulary: list[str], threshold: float = 0.75) -> str:
    """Snap near-miss spellings ("Databurse", "Data verse") to vocabulary terms."""
    tokens = list(re.finditer(r"\w+", text))
    candidates: list[tuple[float, int, int, str | None]] = []
    for term in vocabulary:
        target = re.sub(r"\W", "", term.lower())
        # short terms are too close to ordinary words ("Teams" vs "Team")
        if len(target) < 6:
            continue
        n = len(term.split())
        for size in (n, n + 1):
            for i in range(len(tokens) - size + 1):
                window = tokens[i:i + size]
                if any(not re.fullmatch(r"[ \-]*", text[a.end():b.start()]) for a, b in zip(window, window[1:])):
                    continue
                candidate = "".join(t.group() for t in window).lower()
                start, end = window[0].start(), window[-1].end()
                if candidate == target:
                    score = 1.0
                elif (candidate[0] == target[0] and abs(len(candidate) - len(target)) <= max(2, len(target) // 5)):
                    score = difflib.SequenceMatcher(None, candidate, target).ratio()
                    if score < threshold:
                        continue
                else:
                    continue
                # exact hits (also "Power-Platform" for "Power Platform") only reserve their span
                keep = text[start:end] == term or (candidate == target and " " in term)
                candidates.append((score, start, end, None if keep else term))
    accepted: list[tuple[int, int, str | None]] = []
    for score, start, end, term in sorted(candidates, key=lambda c: (-c[0], c[2] - c[1])):
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
