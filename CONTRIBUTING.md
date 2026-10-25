# Contributing to OffSpeak

Thank you for helping. Bug reports, recognition problems and ideas are welcome as
[issues](https://github.com/applirado/offspeak/issues/new/choose); questions and shared modes or
vocabularies fit best in [Discussions](https://github.com/applirado/offspeak/discussions).

## Pull requests

For anything bigger than a small fix, please open an issue first, so we can agree on the approach
before you put time into it.

Set up a development environment with [uv](https://docs.astral.sh/uv/):

```powershell
git clone https://github.com/applirado/offspeak.git
cd offspeak
uv sync
uv run offspeak download-model parakeet-tdt-0.6b-v3
uv run offspeak            # start the tray app with a console window
uv run pytest
```

A few things that matter for OffSpeak:

- **Nothing may go online.** After setup, OffSpeak makes no network connections; `netguard.py`
  enforces that. New features must work offline.
- **Keep the text pipeline free of UI code.** `commands.py`, `textproc.py` and `pipeline.py` are
  rule-based and covered by tests; please add a test for each new rule or voice command.
- **Windows only.** OffSpeak uses Windows APIs directly; there is no need to keep other platforms in
  mind.

By contributing, you agree that your contribution is released under the [MIT License](LICENSE).
