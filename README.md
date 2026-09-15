# wechat-longshot

把 macOS 微信 4.x 的聊天窗口自动滚动截屏，拼接成一张长图并输出 PDF。
Scroll-capture a WeChat (macOS 4.x) conversation into one tall screenshot and a PDF.

---

## 中文

### 这是什么

微信 4.x 在 macOS 上是自绘界面：消息列表**没有任何可访问性（Accessibility）节点**，本地数据库也是加密的。
所以 `wechat-longshot` 走的是"人肉截图"的路子——它驱动真实界面：找到微信窗口 → 自动识别消息区域 →
（可选）向上翻到指定时间 → 一边滚动一边截图 → 用模板匹配精确对齐拼成长图 → 导出 PDF。

结果是一张完整的聊天长截图，和一份可以直接存档、打印、发给别人的 PDF。

### 运行要求

- macOS 13 (Ventura) 或更高
- 微信 macOS 版 4.x，并且要导出的会话已经打开
- Python 3.12+，推荐用 [`uv`](https://docs.astral.sh/uv/) 管理
- **权限**：需要给你的终端（Terminal / iTerm / VS Code 等）授予两项权限，
  在 **系统设置 → 隐私与安全性** 里打开：
  - **屏幕录制 (Screen Recording)** —— 用于截取窗口画面
  - **辅助功能 (Accessibility)** —— 用于发送滚轮事件

  授予后需要**完全退出并重新打开终端**才会生效。

### 图形界面（推荐）

双击仓库里的 **`启动微信长截图.command`**（首次运行会自动安装 uv 和依赖），或者在终端里执行：

```bash
uv run wechat-longshot-gui
```

在窗口里选"从当前画面开始"或填一个起始时间，点"开始截图"，完成后 PDF 会自动打开。

### 安装（命令行）

```bash
# 安装成全局命令
uv tool install .

# 或者不安装，直接在仓库里跑
uv run wechat-longshot --help
```

### 用法

```bash
# 从当前屏幕上看到的位置开始，一直截到最新消息
wechat-longshot --from-current -o chat.pdf

# 先向上翻到 2026-09-01 10:00，再从那里开始截，输出 A4 分页
wechat-longshot --from "2026-09-01 10:00" -o chat.pdf --page-mode a4

# 手动指定消息区域（图像像素坐标），并放慢滚动步长
wechat-longshot --region 420,90,1200,860 --step 0.4 -o chat.pdf

# 排查问题：保留长图 PNG，并把每一帧都存下来
wechat-longshot --keep-png --debug-dir ./debug -o chat.pdf
```

| 选项 | 说明 |
| --- | --- |
| `--from DATETIME` | 向上翻页直到这个时间，再开始截图（`2026-09-01 10:00` 或 ISO 格式） |
| `--from-current` | 从当前画面开始（不指定 `--from` 时的默认行为） |
| `-o, --out PATH` | 输出 PDF 路径，默认 `./wechat-longshot-<时间戳>.pdf` |
| `--page-mode long\|a4` | 一整页长图，或切成 A4 分页 |
| `--region X,Y,W,H` | 手动指定消息区域，自动识别失败时使用 |
| `--step FLOAT` | 每次滚动的幅度（消息区高度的比例），默认 `0.6` |
| `--max-pages N` | 最多滚动多少屏，防止跑飞，默认 `500` |
| `--keep-png` | 同时保留拼好的长图 PNG |
| `--debug-dir DIR` | 把每一帧截图写到这个目录 |

### 工作原理（简版）

1. `CGWindowListCopyWindowInfo` 找到微信主窗口，ScreenCaptureKit 截取 Retina 原分辨率画面。
2. 轻轻滚一下、对比前后两帧，变化像素的外接矩形就是消息区；再向四周扩展到纯色边界。
3. 滚动用 `CGEventCreateScrollWheelEvent`，然后等到连续两帧完全一致（"稳定"）才截图，避免拍到滚动动画中间态。
4. `--from` 模式下用 Apple Vision 做 OCR（zh-Hans + en-US），解析"昨天 14:38""星期五 14:38""9/3 22:13"等时间分隔符，找到起点。
5. 每帧从上一帧取一条高信息量的横条，用 `cv2.matchTemplate` 归一化匹配定位，算出精确位移，只追加新增的那几行。
6. 导出 PDF；A4 模式下切页位置会挪到附近最"干净"（像素方差最小）的一行，避免把气泡从中间切断。

完整说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

### 已知限制

- 只能导出**当前打开的那个会话**，不会自动切换聊天。
- 图片、表情、视频封面都是以**像素**形式截下来的，不是原图；引用/撤回等结构信息也不保留。
- 截图过程中**请不要动鼠标、不要切换窗口**，否则滚动事件会落到别的地方，长图会错位。
- 微信需要保持在前台；截图期间窗口会被激活。
- 极长的聊天记录会产生很大的图片和 PDF，建议配合 `--from` 缩小范围。

### 路线图

- [ ] 批量导出多个会话
- [ ] 按时间区间截取（`--to`）
- [ ] 导出带文字层的 PDF（把 OCR 结果作为隐藏文本，可搜索）
- [ ] 侧边栏聊天列表识别与自动切换
- [ ] Windows / Linux 微信支持（目前完全是 macOS 专属）

### 许可证

MIT，见 [LICENSE](LICENSE)。

---

## English

### What it does

WeChat 4.x on macOS draws its own UI: the message list exposes **no accessibility tree**
at all, and the local database is encrypted. So `wechat-longshot` takes the screenshot
route — it drives the real UI: find the WeChat window → detect the message area →
optionally scroll up to a given timestamp → capture while scrolling down → align the
frames with template matching into one tall image → export a PDF.

You get a complete long screenshot of the conversation, plus a PDF you can archive,
print, or hand to someone else.

### Requirements

- macOS 13 (Ventura) or newer
- WeChat for macOS 4.x, with the conversation you want already open
- Python 3.12+, [`uv`](https://docs.astral.sh/uv/) recommended
- **Permissions** — grant your terminal app (Terminal / iTerm / VS Code …) both of these
  under **System Settings → Privacy & Security**:
  - **Screen Recording** — to capture the window
  - **Accessibility** — to post scroll-wheel events

  You must fully quit and reopen the terminal after granting them.

### GUI (recommended)

Double-click **`启动微信长截图.command`** in the repo (first run installs uv and the dependencies), or run:

```bash
uv run wechat-longshot-gui
```

Pick "from current view" or type a start time, press Start, and the PDF opens when done.

### Install (CLI)

```bash
# install as a global command
uv tool install .

# or run it straight from the repo
uv run wechat-longshot --help
```

### Usage

```bash
# capture from whatever is on screen down to the newest message
wechat-longshot --from-current -o chat.pdf

# scroll up to 2026-09-01 10:00 first, then capture; paginate as A4
wechat-longshot --from "2026-09-01 10:00" -o chat.pdf --page-mode a4

# pin the message area manually (image pixels) and scroll more gently
wechat-longshot --region 420,90,1200,860 --step 0.4 -o chat.pdf

# troubleshooting: keep the stitched PNG and dump every frame
wechat-longshot --keep-png --debug-dir ./debug -o chat.pdf
```

| Option | Meaning |
| --- | --- |
| `--from DATETIME` | Scroll up to this time first (`2026-09-01 10:00` or ISO 8601) |
| `--from-current` | Start from the current view (the default when `--from` is absent) |
| `-o, --out PATH` | Output PDF, defaults to `./wechat-longshot-<timestamp>.pdf` |
| `--page-mode long\|a4` | One tall page, or A4 pages |
| `--region X,Y,W,H` | Override the message area when auto-detection misfires |
| `--step FLOAT` | Scroll step as a fraction of the region height (default `0.6`) |
| `--max-pages N` | Safety limit on scroll steps (default `500`) |
| `--keep-png` | Also keep the stitched PNG |
| `--debug-dir DIR` | Write every captured frame here |

### How it works (short version)

1. `CGWindowListCopyWindowInfo` locates the main WeChat window; ScreenCaptureKit grabs it at native Retina resolution.
2. A small scroll plus a frame diff gives the bounding box of changed pixels — that is the message list; it is then expanded out to the surrounding uniform-colour borders.
3. Scrolling posts `CGEventCreateScrollWheelEvent` and waits until two consecutive captures are identical ("settled"), so smooth-scroll animation never lands in a frame.
4. With `--from`, Apple Vision OCRs each frame (zh-Hans + en-US) and the time separators ("昨天 14:38", "Friday 14:38", "9/3 22:13") are parsed to find the starting point.
5. For each new frame, a high-entropy strip from the previous frame is located with `cv2.matchTemplate` (`TM_CCOEFF_NORMED`); the match gives the exact pixel shift and only the new rows are appended.
6. The PDF is written; in A4 mode each cut row is nudged to the quietest (lowest pixel variance) nearby row so bubbles are never sliced.

Full details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Limitations

- Only the **currently open conversation** is captured; chats are never switched for you.
- Images, stickers and video thumbnails are captured as **pixels**, not as original files; quote/recall structure is not preserved.
- **Do not touch the mouse or switch windows during capture** — scroll events would land elsewhere and the stitch would break.
- WeChat is brought to the front and must stay there for the duration.
- Very long histories produce very large images and PDFs; pair it with `--from` to bound the range.

### Roadmap

- [ ] Batch export of several conversations
- [ ] Bounded ranges (`--to`)
- [ ] Searchable PDFs with the OCR result as an invisible text layer
- [ ] Sidebar chat-list detection and automatic switching
- [ ] WeChat on Windows / Linux (today this is macOS-only)

### License

MIT — see [LICENSE](LICENSE).
