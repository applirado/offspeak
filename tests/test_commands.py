import pytest

from offspeak.commands import COMMANDS, DEFAULT_PHRASES, LANGUAGES, apply_voice_commands, commands_for

DE = commands_for("de", {})


@pytest.mark.parametrize("spoken,expected", [
    ("Er sagte Anführungszeichen hallo Anführungszeichen", 'Er sagte "hallo"'),
    ("Er sagte Anführungszeichen, hallo Anführungszeichen.", 'Er sagte "hallo".'),
    ("Agenda Doppelpunkt neue Zeile Budget Komma Termine", "Agenda:\nBudget, Termine"),
    ("Das ist Klammer auf vorläufig Klammer zu fertig.", "Das ist (vorläufig) fertig."),
    ("Ist das klar Fragezeichen.", "Ist das klar?"),
    ("Ist das klar, Fragezeichen.", "Ist das klar?"),
    ("Das ist gut, Punkt. Das auch. Punkt.", "Das ist gut. Das auch."),
    ("Ja, okay, einverstanden, Punkt.", "Ja, okay, einverstanden."),
    ("Kann das sein? Fragezeichen.", "Kann das sein?"),
    ("Ein wichtiger Punkt fehlt. Der Punkt ist klar.", "Ein wichtiger Punkt fehlt. Der Punkt ist klar."),
    ("Aber das ist wirklich ein guter Punkt.", "Aber das ist wirklich ein guter Punkt."),
    ("Das ist der springende Punkt.", "Das ist der springende Punkt."),
    ("Kommen wir zum Punkt.", "Kommen wir zum Punkt."),
    ("Hier fehlt ein Komma.", "Hier fehlt ein Komma."),
    ("Füge eine neue Zeile ein.", "Füge eine neue Zeile ein."),
    ("Das ist ein guter Punkt, Punkt.", "Das ist ein guter Punkt."),
    ("Ich bin einverstanden Punkt", "Ich bin einverstanden."),
    ("Das war ein guter Tag Punkt", "Das war ein guter Tag."),
    ("Hallo Team Komma neuer Absatz wie besprochen", "Hallo Team,\n\nWie besprochen"),
    ("Power Bindestrich Platform und ein Ordner Schrägstrich Datei", "Power-Platform und ein Ordner/Datei"),
    ("sag wörtlich Komma", "sag Komma"),
    ("Moment Punkt Punkt Punkt", "Moment…"),
    ("Klammer, auf siehe oben Klammer zu", "(siehe oben)"),
    ("2 Komma 5 Prozent", "2,5 Prozent"),
    ("Anführungszeichen auf A Anführungszeichen zu und Anführungszeichen B Anführungszeichen", '"A" und "B"'),
    ("Das ist ein guter Punkt Punkt neue Zeile viele Grüße", "Das ist ein guter Punkt.\nViele Grüße"),
    ("Erledigt Punkt neuer Absatz nächstes Thema", "Erledigt.\n\nNächstes Thema"),
    ("die Folien Klammer auf neu Klammer zu", "die Folien (neu)"),
])
def test_german_commands(spoken, expected):
    assert apply_voice_commands(spoken, DE) == expected


def test_text_without_commands_is_untouched():
    text = "Das läuft auf Azure ,  ganz  ohne Befehle (wirklich)."
    assert apply_voice_commands(text, DE) == text


def test_english_and_language_selection():
    en = commands_for("en", {})
    assert apply_voice_commands("She said quote hi unquote comma then left period", en) == 'She said "hi", then left.'
    assert apply_voice_commands("first line new line second", en) == "first line\nSecond"
    assert apply_voice_commands("The trial period ends today, period.", en) == "The trial period ends today."
    assert apply_voice_commands("We got a direct quote from the vendor.", en) == "We got a direct quote from the vendor."
    assert apply_voice_commands("It ends after the trial period.", en) == "It ends after the trial period."
    assert apply_voice_commands("It was a long period period new line best regards", en) == \
        "It was a long period.\nBest regards"
    assert apply_voice_commands("send me the slides open parenthesis the new ones close parenthesis question mark",
                                en) == "send me the slides (the new ones)?"
    assert apply_voice_commands("Draw a new line here.", en) == "Draw a new line here."
    # Parakeet often writes the command as one word, and a spoken "comma" as ","
    assert apply_voice_commands("Hi Tom, Newline, Newline. The migration is done.", en) == \
        "Hi Tom,\n\nThe migration is done."
    assert apply_voice_commands("Hi Tom. New paragraph. Thanks.", en) == "Hi Tom\n\nThanks."
    assert apply_voice_commands("Print the newline character.", en) == "Print the newline character."


def test_french_and_italian_nouns():
    assert apply_voice_commands("C'est un bon point.", commands_for("fr", {})) == "C'est un bon point."
    assert apply_voice_commands("D'accord, point.", commands_for("fr", {})) == "D'accord."
    assert apply_voice_commands("Questo è il punto.", commands_for("it", {})) == "Questo è il punto."
    assert commands_for("es", {}) == []
    total = sum(len(p) for lang in DEFAULT_PHRASES.values() for p in lang.values())
    assert len(commands_for("auto", {})) == total


def test_every_language_covers_every_command():
    for lang in LANGUAGES:
        assert set(DEFAULT_PHRASES[lang]) == set(COMMANDS), lang


def test_french_hyphenated_and_apostrophe_phrases():
    fr = commands_for("fr", {})
    assert apply_voice_commands("Vraiment point d'interrogation", fr) == "Vraiment?"
    assert apply_voice_commands("Ordre du jour deux-points budget", fr) == "Ordre du jour: budget"


def test_custom_phrasing_replaces_default_for_that_command_only():
    cmds = commands_for("de", {"de": {"comma": ["Beistrich"]}})
    assert apply_voice_commands("Hallo Beistrich Welt Punkt", cmds) == "Hallo, Welt."
    assert apply_voice_commands("Hallo Komma Welt", cmds) == "Hallo Komma Welt"
    assert apply_voice_commands("Hallo Komma Welt", commands_for("de", {"de": {"comma": []}})) == "Hallo Komma Welt"
