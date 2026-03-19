#!/bin/bash
SESSION="loli"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run setup (pip install + model downloads)
echo "Running setup..."
bash "$SCRIPT_DIR/setup.sh"
echo ""

# Kill existing session if it exists
tmux kill-session -t "$SESSION" 2>/dev/null

# Create new tmux session with first pane for ComfyUI
tmux new-session -d -s "$SESSION" -n "main"
tmux send-keys -t "$SESSION:main" "conda activate comfy && cd $SCRIPT_DIR/ComfyUI && python main.py --listen 0.0.0.0 --port 8188 2>&1 | tee $SCRIPT_DIR/comfyui.log" Enter

# Split the window horizontally (side by side)
tmux split-window -h -t "$SESSION:main"
tmux send-keys -t "$SESSION:main.1" "conda activate comfy && cd $SCRIPT_DIR/loli_api && python main.py" Enter

# Attach to the session
tmux attach -t "$SESSION"
