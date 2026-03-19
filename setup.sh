#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Full Setup: Pip Install + Models     ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# ==========================================
# STEP 1: Install Python dependencies
# ==========================================
echo -e "${YELLOW}[Step 1/2] Installing Python dependencies...${NC}"
echo ""

pip install -r "$SCRIPT_DIR/requirements.txt"

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}Warning: pip install had errors. Continuing with model downloads...${NC}"
fi

echo ""
echo -e "${GREEN}Pip install complete.${NC}"
echo ""

# ==========================================
# STEP 2: Download models
# ==========================================
echo -e "${YELLOW}[Step 2/2] Downloading models...${NC}"
echo ""

MODELS_DIR="$SCRIPT_DIR/ComfyUI/models"

# Function to handle downloading
download_file() {
    local url=$1
    local folder=$2
    local name=$(basename "$url")
    local target="$MODELS_DIR/$folder"

    echo -e "${GREEN}Processing: $name ...${NC}"

    # Create folder if it doesn't exist
    if [ ! -d "$target" ]; then
        echo "Creating directory: $target"
        mkdir -p "$target"
    fi

    # Skip if file already exists
    if [ -f "$target/$name" ]; then
        echo "Already exists, skipping: $target/$name"
        echo "--------------------------------------"
        return
    fi

    # Download with wget (-c allows resuming interrupted downloads)
    wget -c "$url" -P "$target"

    echo "Saved to: $target/$name"
    echo "--------------------------------------"
}

# 1. Diffusion Models
download_file "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_nvfp4.safetensors" "diffusion_models"

# 2. Text Encoders
download_file "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b_fp4_mixed.safetensors" "text_encoders"

# 3. VAE
download_file "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors" "vae"

# 4. Checkpoints
download_file "https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO/resolve/main/v23/Qwen-Rapid-AIO-NSFW-v23.safetensors" "checkpoints"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Setup complete!                      ${NC}"
echo -e "${GREEN}========================================${NC}"
