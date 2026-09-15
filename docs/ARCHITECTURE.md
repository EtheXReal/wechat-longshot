# Architecture

`wechat-longshot` turns a WeChat (macOS, 4.x) chat window into one tall screenshot
and a PDF. It drives the real UI (scroll wheel events + window capture) because
WeChat 4.x is custom-rendered and exposes **no accessibility tree** for the
message list, and the on-disk database is encrypted.

## Pipeline

```
find window ─► detect message region ─► navigate to start ─► capture-down loop ─► stitch ─► PDF
 (window.py)     (region.py)              (navigator.py)      (scroller.py)     (stitcher.py)  (pdf.py)
                                          uses ocr.py +
                                          timeparse.py
```

1. **window.py** – locate the main WeChat window via `CGWindowListCopyWindowInfo`
   (owner `WeChat`, layer 0, largest area), capture it with
   `CGWindowListCreateImage` (needs *Screen Recording* permission), return a BGR
   numpy `Frame` plus a `WindowInfo` (bounds in points, Retina `scale`).
2. **region.py** – find the scrollable message area *without* any UI metadata:
   scroll a little, diff the two frames, take the bounding box of changed pixels,
   then expand it to the surrounding uniform-colour band (header above, input box
   below, chat list on the left). Falls back to a user-supplied `--region`.
3. **scroller.py** – post `CGEventCreateScrollWheelEvent` (pixel units) at the
   region centre, then wait until two consecutive captures are identical
   ("settled"), so smooth-scroll animation never corrupts a frame.
4. **navigator.py** – decide where the long shot starts:
   * `--from-current`: start at whatever is on screen now.
   * `--from "2026-09-01 10:00"`: scroll **up** page by page, OCR each frame with
     Apple Vision (zh-Hans + en), parse WeChat time separators (`timeparse.py`)
     and stop at the first separator `<= target` (or at the very top). Scrolling up
     triggers WeChat's lazy history loading, which is fine here because we only
     *capture* on the way down.
5. **capture-down loop + stitcher.py** – scroll down by ~60 % of the region
   height per step. For each new frame, pick a high-entropy horizontal strip from
   the previous frame and locate it in the new frame with normalised template
   matching (`cv2.matchTemplate`, `TM_CCOEFF_NORMED`) restricted to the expected
   offset window. The match gives the exact pixel shift; append the non-overlapping
   rows to the canvas. Stop when a scroll produces an identical frame (bottom
   reached). Low-confidence matches are retried with a smaller scroll step.
6. **pdf.py** – write the tall image as a PDF, either one long page
   (`--page-mode long`, split only when PDF's 14400 pt page limit is hit) or A4
   pages (`--page-mode a4`) whose cut points are nudged to the nearest uniform
   background row so bubbles are never sliced.

## Coordinates

All `Rect`s are in *image pixels* of a captured `Frame`. `WindowInfo.scale` maps
pixels to screen points for posting events (`WindowInfo.to_screen_point`).

## Module interfaces (contract for parallel implementation)

```python
# window.py
def find_wechat_window() -> WindowInfo            # raises WindowNotFound
def capture_window(win: WindowInfo) -> Frame      # BGR uint8, raises CaptureFailed (no permission)
def activate_window(win: WindowInfo) -> None      # bring WeChat to front (NSRunningApplication)

# region.py  (Fable)
def detect_message_region(capture: CaptureFn, scroll: ScrollFn, frame_hint: Frame | None = None) -> Rect

# scroller.py  (Fable)
class Scroller:
    def __init__(self, win: WindowInfo, region: Rect, capture: CaptureFn, settle_timeout: float = 2.0): ...
    def scroll(self, dy_px: int) -> Frame        # positive = view newer (content moves up); returns settled frame
    def page_up(self, fraction: float = 0.6) -> Frame
    def page_down(self, fraction: float = 0.6) -> Frame

# stitcher.py  (Fable)
class Stitcher:
    def __init__(self, region: Rect): ...
    def add(self, frame: Frame, expected_shift: int | None = None) -> int   # returns actual shift (0 => no new content)
    def image(self) -> Frame                       # the tall canvas so far

# ocr.py  (Fable)
def recognize_text(frame: Frame, languages=("zh-Hans", "en-US")) -> list[TextBox]

# timeparse.py  (Opus)
def parse_time_label(text: str, now: datetime) -> datetime | None
    # Handles WeChat separator formats in zh-CN and en-US, e.g.
    # "14:38", "昨天 14:38", "Yesterday 14:38", "星期五 14:38", "Friday 14:38",
    # "9/3 22:13", "2025/9/3 22:13", "2025年9月3日 22:13", "上午 9:05", "下午 3:20",
    # "9月3日 22:13". Returns None for non-time text. Weekday/"yesterday" are
    # resolved relative to `now` (most recent past occurrence).

# navigator.py  (Fable)
def navigate_to_start(scroller: Scroller, start: datetime | None, now: datetime) -> Frame

# pdf.py  (Opus)
def image_to_pdf(image: Frame, out: Path, page_mode: Literal["long", "a4"] = "long", dpi: int = 144) -> None

# pipeline.py  (Fable)
@dataclass
class Options:
    start: datetime | None        # None => from current view
    out: Path
    page_mode: Literal["long", "a4"] = "long"
    region: Rect | None = None    # manual override
    step_fraction: float = 0.6
    max_pages: int = 500
    keep_png: bool = False
    debug_dir: Path | None = None
def run(opts: Options) -> Path

# cli.py  (Opus)  -> console script `wechat-longshot`
#   wechat-longshot --from-current -o chat.pdf
#   wechat-longshot --from "2026-09-01 10:00" -o chat.pdf --page-mode a4
#   options: --region X,Y,W,H  --step 0.6  --max-pages N  --keep-png  --debug-dir DIR
```
