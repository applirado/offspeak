# Offspeak

**Offspeak is voice dictation for Windows that runs entirely on your own machine.** Hold a hotkey, talk,
let go, and the text appears wherever your cursor is: in mail, chat, an editor or a browser. Speech
recognition, clean-up and all your settings stay on your computer. There is no account, no cloud
service and no upload.

Like the cockatoo in its logo, Offspeak repeats what it hears, only more neatly.

---

## Highlights

- **Fast on an ordinary laptop CPU.** With NVIDIA Parakeet, a typical sentence is transcribed in
  0.3 to 0.5 seconds. No GPU is needed.
- **Private by design.** A built-in network guard refuses every connection that does not stay on the
  local machine. Audio, transcripts and history never leave your PC.
- **Speaks your languages.** Parakeet recognises 25 European languages, including German, English,
  French and Italian, with punctuation and capitalisation.
- **Gets your jargon right.** Add terms like *Dataverse* or *Claude Code* to the vocabulary, and
  near-misses such as "Databurse" or "Cloud Code" are corrected automatically.
- **Voice commands.** Say "Komma", "neue Zeile" or "Anführungszeichen" (or "comma", "new line",
  "quote") to insert punctuation and line breaks. Offspeak tells the command "Punkt" apart from the
  noun in "ein guter Punkt".
- **Leaves your clipboard alone.** Images, rich text and files on the clipboard survive a dictation,
  and dictated text stays out of the Win+V clipboard history.
- **Optional AI clean-up.** A mode can pass the text through a local language model (any GGUF file
  via llama.cpp) to rewrite, format or translate it.

## Requirements

- Windows 10 or 11 (64-bit)
- About 1 GB of disk space for the Parakeet model

Everything else, including Python, is installed by the setup.

## Installation

Clone or download the repository and double-click **`setup.cmd`**. It installs, for the current user
and without admin rights:

1. [uv](https://docs.astral.sh/uv/), if it is missing, which in turn installs Python 3.12
2. Offspeak's packages, exactly as pinned in `uv.lock`
3. the Parakeet voice model, if it is not installed yet
4. a Start menu shortcut, and autostart when you sign in to Windows

Then it starts Offspeak. Run `setup.cmd` again at any time to update or repair the installation, for
example after a `git pull` or after moving the folder. Options: `-NoAutostart`, `-NoModel` and
`-NoLaunch`, for example `setup.cmd -NoAutostart`.

The setup is the only step that uses the internet. After that, Offspeak works offline.

<details>
<summary>Manual installation with uv</summary>

```powershell
git clone https://github.com/applirado/offspeak.git
cd offspeak
uv sync
uv run offspeak download-model parakeet-tdt-0.6b-v3
uv run offspeak autostart on    # optional
```

</details>

## Getting started

Start Offspeak from the Start menu, or from the command line:

```powershell
uv run offspeak        # with a console window
uv run offspeakw       # without a console window
```

Offspeak sits in the system tray as a cockatoo. The colour of its circle shows what it is doing:

| Colour | State |
|---|---|
| Blue | Ready |
| Red | Recording |
| Orange | Transcribing |
| Green | Done; the text was inserted |

### Default shortcuts

| Shortcut | Action |
|---|---|
| Hold **Ctrl+Space** | Push-to-talk: records while held, inserts the text when released |
| **Ctrl+Numpad0** | Start or stop a recording |
| **Esc** | Cancel the current recording |

You can change every shortcut in the settings.

## Settings

Left-click the tray icon to open the settings. Right-click it for the menu with modes, "Copy last
result", "Transcribe file..." and "Quit".

| Tab | What you set there |
|---|---|
| **Vocabulary** | Names and technical terms to spell correctly. Terms with 6 or more letters are also fixed when they come out slightly wrong. |
| **Replacements** | Words that are always replaced, for example "mfg" -> "Mit freundlichen Grüssen". |
| **Voice commands** | How you say each punctuation command, per language (Deutsch, English, Français, Italiano). |
| **Shortcuts** | Push-to-talk, start/stop, cancel, and one shortcut per mode. |
| **Sound** | Optional gentle sounds when a recording starts and stops. |
| **Startup** | Start Offspeak automatically when you sign in to Windows. |

At the bottom, **Test your rules** shows what your rules make of a sentence. Click **Speak** or hold
your push-to-talk shortcut, and Offspeak puts the raw transcript into the test field instead of
pasting it. **Ctrl+Plus**, **Ctrl+Minus** and **Ctrl+mouse wheel** zoom the window.

### Voice commands

The commands are fixed; you choose how to say them. A few of the defaults:

| Command | Deutsch | English |
|---|---|---|
| `.` | Punkt | period, full stop |
| `,` | Komma | comma |
| `?` | Fragezeichen | question mark |
| `"..."` | Anführungszeichen (opens, then closes) | quote ... unquote |
| `( )` | Klammer auf / Klammer zu | open / close parenthesis |
| new line | neue Zeile | new line |
| new paragraph | neuer Absatz | new paragraph |
| next word as text | wörtlich | literally |

"Ich bin einverstanden, Punkt." becomes *Ich bin einverstanden.*, while "Das ist ein guter Punkt."
stays as it is. To write a command word itself, say "wörtlich" before it.

## Modes

A mode bundles a voice model, a language, an optional language model with a prompt, and its own
shortcut. Modes are JSON files in `%LOCALAPPDATA%\Offspeak\modes\`:

```json
{
  "key": "mail",
  "name": "E-Mail",
  "voice_model": "parakeet-tdt-0.6b-v3",
  "language": "de",
  "language_model": "Qwen3-4B-Instruct-Q4_K_M",
  "prompt": "Turn the dictation into a short, friendly e-mail.",
  "context_from_selection": true,
  "context_from_clipboard": false,
  "activation_apps": ["outlook"],
  "shortcut": "Control+Numpad2"
}
```

- `language_model` is the file name of a `.gguf` file in the models folder, without the extension.
  Leave it empty for plain dictation, which is the fastest and most faithful option.
- `activation_apps` switches to the mode automatically when one of these programs is in front.
- The selected text and clipboard can be passed to the language model as context, so you can say
  things like "make this more formal".

After editing a mode, choose **Reload settings** in the tray menu.

## Models

Models live in `%LOCALAPPDATA%\Offspeak\models\`.

| Model | Type | Notes |
|---|---|---|
| `parakeet-tdt-0.6b-v3` | Voice (ONNX) | **Recommended.** Fast and accurate, 25 languages. |
| `small`, `large-v3-turbo`, ... | Voice (whisper.cpp) | Supports translation to English; noticeably slower on a CPU. |
| any `*.gguf` | Language model (llama.cpp) | Optional; used only in modes that set `language_model`. |

```powershell
uv run offspeak models                    # list installed models
uv run offspeak download-model small      # download a whisper.cpp model
```

## Command line

```powershell
uv run offspeak transcribe recording.wav    # transcribe a file (wav, flac, mp3, ogg)
uv run offspeak history "Dataverse"         # search past dictations
uv run offspeak import-superwhisper         # take over modes, vocabulary and shortcuts from Superwhisper
uv run offspeak autostart on                # start at sign-in (on / off; no argument shows the state)
```

## Where your data lives

Everything is stored under `%LOCALAPPDATA%\Offspeak` (or the folder in `OFFSPEAK_HOME`):

- `settings.json` and `modes\`: your configuration
- `history.sqlite`: past dictations, searchable
- `recordings\`: the audio of each dictation; audio older than 30 days is deleted automatically
- `models\`: voice and language models

## Development

```powershell
uv run pytest
```

The code is in `src/offspeak/`. The text pipeline is rule-based and has no UI dependencies:
`commands.py` handles voice commands, `textproc.py` handles vocabulary and replacements, and
`pipeline.py` ties speech recognition and post-processing together.

---

```
         ..............................................
     ......................................................
   ..........................................................
  .......................%%%..................................
 ........................%%%%%.................................
.........................%%%%%%%%...............................
..........................%%%%%%%%%.............................
................%%%.......%%%%%%%%%%%%..........................
................%%%%%%.....%%%%%%%%%%%%%........................
.................%%%%%%%%....%%%%%%%%%%%%%%.....................
.................%%%%%%%%%%%%%%%%%%%%%%%%%%%%...................
..................%%%%%%%%%%%%%%%%%%%%%%%%%%%%..................
..........@@@@@@@@@@%%%%%%%%%%%%%%%%%@@@@@@%%%%.................
..........@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@%%................
...........@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@................
.............@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@######............
................@@@@@@@@@@@@@@@@@@@@#####@@@@########...........
.......................@@@@@@@@@@@@@#####@@@###########.........
......................@@@@@@@@@@@@@@@@#@@@@############.........
.....................@@@@@@@@@@@@@@@@@@@@@@############.........
...................@@@@@@@@@@@@@@@@@@@@@@@@############.........
..................@@@@@@@@@@@@@@@@@@@@@@@@@############.........
................@@@@@@@@@@@@@@@@@@@@@@@@@@@#######..###.........
...............@@@@@@@@@@@@@@@@@@@@@@@@@@@@######....#..........
..............++++++++++@@@@@@@@@@@@@@@@@@@.##..................
...........+++++++++++++++++@@@@@@@@@@@@@@@.....................
.........+++++++++++++++++++++@@@@@@@@@@@@@.....................
 .......+++++++++++++++++++++++@@@@@@@@@@@.....................
  ....+++++++++++++++++++++++++++@@@@@@@@@....................
   ..+++++++++++++++++++++++++++++@@@@@@@@...................
     ++++++++++++++++++++++++++++++@@@@@@..................
         ++++++++++++++++++++++++++@@@@@@..............

           ___   __  __   ____                   _
          / _ \ / _|/ _| / ___| _ __   ___  __ _| | __
         | | | | |_| |_  \___ \| '_ \ / _ \/ _` | |/ /
         | |_| |  _|  _|  ___) | |_) |  __/ (_| |   <
          \___/|_| |_|   |____/| .__/ \___|\__,_|_|\_\
                               |_|

                    Dictate Fast, Stay Local
```
