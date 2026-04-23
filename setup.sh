#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not found."
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[gui]"

mkdir -p "${HOME}/bin"
REPOCLI_BIN="${HOME}/bin/repocli"
if [ ! -x "${REPOCLI_BIN}" ]; then
  echo "Installing repocli 0.9.5 into ${REPOCLI_BIN}"
  wget "https://github.com/Donders-Institute/dr-tools/releases/download/0.9.5/repocli.x86_64" -O "${REPOCLI_BIN}"
  chmod +x "${REPOCLI_BIN}"
fi

if ! grep -q 'export PATH="$HOME/bin:$PATH"' "${HOME}/.bashrc" 2>/dev/null; then
  echo 'export PATH="$HOME/bin:$PATH"' >> "${HOME}/.bashrc"
fi

ln -sf "${REPOCLI_BIN}" "${ROOT_DIR}/.venv/bin/repocli"

echo ""
echo "Setup complete."
echo "Step 2 (one-time): repocli config"
echo "  baseurl: https://webdav.data.ru.nl"
echo "  username/password: RDR Data Access Credentials"
echo ""
echo "Then run:"
echo "  source .venv/bin/activate"
echo "  streamlit run src/mous_pipeline/gui_streamlit.py"
echo "Or inside JupyterLab, open notebooks/mous_gui.ipynb"
echo "  (it starts Streamlit and links to /proxy/8501/)"
