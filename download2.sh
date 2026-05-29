#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}--- ComfyUI Model Downloader ---${NC}"
echo "Current directory: $(pwd)"
echo "Make sure this script is located in your 'ComfyUI/models' folder."
echo ""

# Function to handle downloading
download_file() {
    local url=$1
    local folder=$2
    local name=$(basename "$url")

    echo -e "${GREEN}Processing: $name ...${NC}"

    # Create folder if it doesn't exist
    if [ ! -d "$folder" ]; then
        echo "Creating directory: $folder"
        mkdir -p "$folder"
    fi

    # Download with wget
    # -c allows resuming interrupted downloads
    # -P sets the directory prefix
    wget -c "$url" -P "$folder"
    
    echo "Saved to: $folder/$name"
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

# 5. IP-Adapter FaceID Models — DISABLED.
# These are SD1.5 adapters and are architecturally INCOMPATIBLE with the Qwen-Image-Edit /
# Z-Image (DiT) models this project actually uses. They cannot be loaded into the Qwen/Z-Image
# workflows, so downloading them only wastes ~2.5 GB. Identity preservation is handled via
# SAM3 mask-lock + FaceWarp (comfyui_faceanalysis) + seed locking instead — see
# docs/RUNPOD_SETUP.md §6. If you later procure a Qwen-native identity adapter
# (PuLID/InstantID-equivalent), add it here.
#
# download_file "https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sd15.bin" "ipadapter"
# download_file "https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-portrait_sd15.bin" "ipadapter"
# download_file "https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sd15_lora.safetensors" "loras"
#
# # 6. CLIP Vision Model (for the SD1.5 IP-Adapter above) — also disabled.
# download_clip_vision() {
#     local folder="clip_vision"
#     local name="CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
#     mkdir -p "$folder"
#     wget -c "https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors" -O "$folder/$name"
# }
# download_clip_vision

echo -e "${GREEN}All downloads finished!${NC}"