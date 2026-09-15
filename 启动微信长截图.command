#!/bin/zsh
# Double-click to launch the GUI. Installs uv on first run if it is missing.
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo "正在安装 uv ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv run wechat-longshot-gui
