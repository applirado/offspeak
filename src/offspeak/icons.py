import functools
from pathlib import Path

from PIL import Image, ImageDraw

# ready is the amber of the app icon; transcribing is blue, because orange would barely differ from it
STATE_COLORS = {"ready": "#fdb404", "recording": "#e5484d", "processing": "#3e63dd", "done": "#30a46c",
                "error": "#e5484d"}
BIRD_FILE = Path(__file__).with_name("icon-bird.png")  # the cockatoo of assets/offspeak.svg without its tile


@functools.lru_cache(maxsize=32)
def icon_image(state: str, size: int = 64) -> Image.Image:
    """The OffSpeak app icon; its tile takes the state's colour, so it reads even at the 16 px tray size."""
    bird = Image.open(BIRD_FILE).convert("RGBA")
    s = bird.width
    tile = Image.new("RGBA", (2 * s, 2 * s), (0, 0, 0, 0))  # drawn twice as large for smooth corners
    ImageDraw.Draw(tile).rounded_rectangle((0, 0, 2 * s - 1, 2 * s - 1), radius=2 * s * 112 // 512,
                                           fill=STATE_COLORS.get(state, STATE_COLORS["error"]))
    img = tile.resize((s, s), Image.LANCZOS)
    img.alpha_composite(bird)
    return img.resize((size, size), Image.LANCZOS)


def tray_image(state: str) -> Image.Image:
    # high resolution, so Windows downsamples to the 16-32 px tray size itself instead of upscaling
    return icon_image(state, 256)
