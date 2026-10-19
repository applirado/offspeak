"""Spoken punctuation and formatting commands ("Komma", "Klammer auf", "neue Zeile", ...)."""

import copy
import re

LANGUAGES = {"de": "Deutsch", "en": "English", "fr": "Français", "it": "Italiano"}

# The commands themselves are fixed; only how they are spoken is configurable, per language.
# id: (label, inserted text, behaviour)
COMMANDS: dict[str, tuple[str, str, str]] = {
    "period": ("Period", ".", "punct"),
    "comma": ("Comma", ",", "punct"),
    "colon": ("Colon", ":", "punct"),
    "semicolon": ("Semicolon", ";", "punct"),
    "question": ("Question mark", "?", "punct"),
    "exclamation": ("Exclamation mark", "!", "punct"),
    "ellipsis": ("Ellipsis", "…", "punct"),
    "quote": ("Quote (opens, then closes)", '"', "quote"),
    "quote_open": ("Opening quote", '"', "open"),
    "quote_close": ("Closing quote", '"', "close"),
    "paren_open": ("Opening parenthesis", "(", "open"),
    "paren_close": ("Closing parenthesis", ")", "close"),
    "hyphen": ("Hyphen (joins words)", "-", "join"),
    "slash": ("Slash (joins words)", "/", "join"),
    "newline": ("New line", "\n", "break"),
    "paragraph": ("New paragraph", "\n\n", "break"),
    "literal": ("Write next word literally", "", "escape"),
}

DEFAULT_PHRASES: dict[str, dict[str, list[str]]] = {
    "de": {
        "period": ["Punkt"], "comma": ["Komma"], "colon": ["Doppelpunkt"],
        "semicolon": ["Semikolon", "Strichpunkt"], "question": ["Fragezeichen"],
        "exclamation": ["Ausrufezeichen"], "ellipsis": ["Punkt Punkt Punkt"],
        "quote": ["Anführungszeichen", "Gänsefüßchen"], "quote_open": ["Anführungszeichen auf"],
        "quote_close": ["Anführungszeichen zu"], "paren_open": ["Klammer auf"], "paren_close": ["Klammer zu"],
        "hyphen": ["Bindestrich"], "slash": ["Schrägstrich"],
        "newline": ["neue Zeile"], "paragraph": ["neuer Absatz"], "literal": ["wörtlich"],
    },
    "en": {
        "period": ["period", "full stop"], "comma": ["comma"], "colon": ["colon"],
        "semicolon": ["semicolon"], "question": ["question mark"],
        "exclamation": ["exclamation mark", "exclamation point"], "ellipsis": ["dot dot dot"],
        "quote": ["quote"], "quote_open": ["open quote"], "quote_close": ["close quote", "unquote"],
        "paren_open": ["open parenthesis", "open bracket"], "paren_close": ["close parenthesis", "close bracket"],
        "hyphen": ["hyphen"], "slash": ["slash"],
        "newline": ["new line"], "paragraph": ["new paragraph"], "literal": ["literally"],
    },
    "fr": {
        "period": ["point"], "comma": ["virgule"], "colon": ["deux points"],
        "semicolon": ["point virgule"], "question": ["point d'interrogation"],
        "exclamation": ["point d'exclamation"], "ellipsis": ["points de suspension"],
        "quote": ["guillemets"], "quote_open": ["ouvrez les guillemets"],
        "quote_close": ["fermez les guillemets"], "paren_open": ["ouvrez la parenthèse"],
        "paren_close": ["fermez la parenthèse"], "hyphen": ["trait d'union"], "slash": ["barre oblique"],
        "newline": ["à la ligne", "nouvelle ligne"], "paragraph": ["nouveau paragraphe"],
        "literal": ["littéralement"],
    },
    "it": {
        "period": ["punto"], "comma": ["virgola"], "colon": ["due punti"],
        "semicolon": ["punto e virgola"], "question": ["punto interrogativo"],
        "exclamation": ["punto esclamativo"], "ellipsis": ["puntini di sospensione"],
        "quote": ["virgolette"], "quote_open": ["aperte virgolette"], "quote_close": ["chiuse virgolette"],
        "paren_open": ["aperta parentesi"], "paren_close": ["chiusa parentesi"],
        "hyphen": ["trattino"], "slash": ["barra"],
        "newline": ["a capo"], "paragraph": ["nuovo paragrafo"], "literal": ["letteralmente"],
    },
}


def default_phrases(language: str | None = None):
    if language is None:
        return copy.deepcopy(DEFAULT_PHRASES)
    return copy.deepcopy(DEFAULT_PHRASES.get(language, {}))


def phrases_with_defaults(table: dict[str, dict[str, list[str]]], language: str) -> dict[str, list[str]]:
    """User phrases for a language, falling back to the defaults for commands never customised."""
    merged = default_phrases(language)
    merged.update({k: list(v) for k, v in table.get(language, {}).items() if k in COMMANDS})
    return merged


def commands_for(language: str, table: dict[str, dict[str, list[str]]]) -> list[dict]:
    languages = list(LANGUAGES) if language in ("", "auto") else [language]
    result = []
    for lang in languages:
        if lang not in LANGUAGES:
            continue
        for cmd_id, phrases in phrases_with_defaults(table, lang).items():
            _label, symbol, kind = COMMANDS[cmd_id]
            result += [{"phrase": p, "symbol": symbol, "kind": kind, "lang": lang} for p in phrases if p.strip()]
    return result


# Words that precede a noun. After them "Punkt", "Komma", "quote" ... are words, not commands.
DETERMINERS = {
    "de": set("der die das den dem des ein eine einen einem eines einer kein keine keinen keinem keines keiner "
              "mein meine meinen meinem meines meiner dein deine deinen deinem deines sein seine seinen seinem "
              "seines ihr ihre ihren ihrem ihres unser unsere unseren unserem unseres euer eure euren eurem "
              "dieser diese diesen diesem dieses jeder jede jeden jedem jedes jener jene jenen welcher welche "
              "welchen welchem zum zur am im beim vom ins ans aufs".split()),
    "en": set("the a an this that these those my your his her its our their every each no another".split()),
    "fr": set("le la les un une des du au aux ce cet cette ces mon ma mes ton ta tes son sa ses notre nos "
              "votre vos leur leurs chaque quel quelle".split()),
    "it": set("il lo la i gli le un uno una del dello della dei degli delle al allo alla ai agli alle nel "
              "nello nella questo questa quel quello quella ogni mio mia tuo tua suo sua nostro nostra "
              "vostro vostra".split()),
}
# Adjectives between determiner and noun: inflected in German, a short list where adjectives precede nouns.
FR_ADJECTIVES = set("bon bonne mauvais mauvaise dernier dernière premier première petit petite grand grande "
                    "autre même seul seule nouveau nouvel nouvelle vrai vraie gros grosse".split())
IT_ADJECTIVES = set("buon buono buona ultimo ultima primo prima altro altra piccolo piccola grande solo sola "
                    "nuovo nuova vero vera".split())


def _adjective_after_determiner(lang: str, word: str, before: str) -> bool:
    if before not in DETERMINERS.get(lang, ()):
        return False
    if lang == "de":
        return word[0].islower() and word.endswith(("e", "er", "en", "em", "es"))
    if lang == "en":
        return before in ("the", "a", "an")
    return word in (FR_ADJECTIVES if lang == "fr" else IT_ADJECTIVES)


def _used_as_word(tokens: list[dict], start: int, end: int, cmd: dict) -> bool:
    """Tell "ein guter Punkt." (the noun) apart from "einverstanden, Punkt." (the command)."""
    if cmd["kind"] == "escape":
        return False
    prev = tokens[start - 1] if start else None
    if prev is None or prev["type"] == "asr":
        return False  # the recogniser marks a spoken command with a pause: "einverstanden, Punkt."
    lang = cmd.get("lang", "")
    prev_word = prev["t"].lower()
    if prev_word in DETERMINERS.get(lang, ()):
        return True
    before = tokens[start - 2] if start >= 2 and tokens[start - 2]["type"] == "word" else None
    if before and _adjective_after_determiner(lang, prev["t"], before["t"].lower()):
        return True
    # a dictated sentence end is followed by punctuation or a new sentence, not by "Punkt fehlt"
    if cmd["symbol"] in SENTENCE_END and end < len(tokens):
        after = tokens[end]
        return after["type"] == "word" and after["t"][0].islower()
    return False


TOKEN_RE = re.compile(r"\w+(?:['’\-./@]\w+)*|[^\w\s]")
ASR_PUNCT = set(",.;:!?…")
SENTENCE_END = {".", "?", "!", "…"}
NO_SPACE_BEFORE = {"punct", "close", "join", "break"}
NO_SPACE_AFTER = {"open", "join", "break"}
STRIP_ASR_BEFORE = {"punct", "close", "join", "break"}
STRIP_ASR_AFTER = {"punct", "open", "join", "break"}


def _norm(s: str) -> str:
    return re.sub(r"[\s\-]+", " ", s.lower().replace("’", "'")).strip()


def _match(tokens: list[dict], i: int, phrases: list[tuple[str, dict]]):
    for norm, cmd in phrases:
        acc, j, end = "", i, i
        while j < len(tokens) and len(acc) < len(norm):
            tok = tokens[j]
            if tok["type"] == "word":
                acc = f"{acc} {_norm(tok['t'])}".strip()
                end = j + 1
            elif tok["t"] not in ",.;:":  # ASR sometimes puts a comma inside "Klammer, auf"
                break
            j += 1
        if acc == norm:
            return cmd, end
    return None


def apply_voice_commands(text: str, commands: list[dict]) -> str:
    if not text or not commands:
        return text
    tokens, pos = [], 0
    for m in TOKEN_RE.finditer(text):
        t = m.group()
        tokens.append({"t": t, "ws": text[pos:m.start()], "type": "word" if t[0].isalnum() or t[0] == "_" else "asr"})
        pos = m.end()
    phrases = sorted(((_norm(c["phrase"]), c) for c in commands if c.get("phrase", "").strip()),
                     key=lambda p: -len(p[0]))

    out: list[dict] = []
    i, matched, literal_ws = 0, False, None
    while i < len(tokens):
        tok = tokens[i]
        if tok["type"] == "word":
            if literal_ws is not None:
                out.append({**tok, "ws": literal_ws})
                literal_ws = None
                i += 1
                continue
            hit = _match(tokens, i, phrases)
            if hit and _used_as_word(tokens, i, hit[1], hit[0]):
                hit = None
            if hit:
                cmd, i = hit
                matched = True
                if cmd["kind"] == "escape":
                    literal_ws = tok["ws"]
                else:
                    out.append({"type": "cmd", "t": cmd["symbol"], "kind": cmd["kind"], "ws": tok["ws"]})
                continue
        out.append(tok)
        i += 1
    if not matched:
        return text

    # quotes alternate per symbol; explicit opening/closing commands set the state
    is_open: dict[str, bool] = {}
    for tok in out:
        if tok["type"] == "cmd":
            if tok["kind"] == "quote":
                tok["kind"] = "close" if is_open.get(tok["t"]) else "open"
            if tok["kind"] in ("open", "close"):
                is_open[tok["t"]] = tok["kind"] == "open"

    # drop punctuation the recogniser put right next to a command ("Fragezeichen." -> "?")
    drop = set()
    for idx, tok in enumerate(out):
        if tok["type"] != "cmd":
            continue
        if tok["kind"] in STRIP_ASR_BEFORE:
            j = idx - 1
            while j >= 0 and out[j]["type"] == "asr" and out[j]["t"] in ASR_PUNCT:
                drop.add(j)
                j -= 1
        if tok["kind"] in STRIP_ASR_AFTER:
            j = idx + 1
            while j < len(out) and out[j]["type"] == "asr" and out[j]["t"] in ASR_PUNCT:
                drop.add(j)
                j += 1
    out = [t for idx, t in enumerate(out) if idx not in drop]

    res, cap_next = "", False
    for idx, tok in enumerate(out):
        prev = out[idx - 1] if idx else None
        glued_to_prev = prev is not None and prev["type"] == "cmd" and prev["kind"] in NO_SPACE_AFTER
        if tok["type"] == "cmd":
            kind = tok["kind"]
            if kind == "break":
                res = res.rstrip(" ")
                sep = ""
            else:
                sep = "" if prev is None or glued_to_prev or kind in NO_SPACE_BEFORE else " "
            res += sep + tok["t"]
            if kind == "break" or (kind == "punct" and tok["t"] in (".", "?", "!")):
                cap_next = True
            continue
        if prev is None or glued_to_prev:
            sep = ""
        elif prev["type"] == "cmd":
            before = out[idx - 2] if idx >= 2 else None
            decimal = (prev["t"] in ",." and tok["t"].isdigit() and before is not None and before["t"].isdigit())
            sep = "" if tok["type"] == "asr" or decimal else " "
        else:
            sep = tok["ws"]
        t = tok["t"]
        if cap_next and tok["type"] == "word":
            t = t[0].upper() + t[1:]
            cap_next = False
        res += sep + t
    return res.strip(" ")
