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
# The production workflow (amazing-z-photo_API_Create_CHAR.json node 291) loads the
# bf16 variant. The nvfp4 variant is kept as the smaller (~half size) alternative —
# only needed if the workflow is switched back to nvfp4.
download_file "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors" "diffusion_models"
download_file "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_nvfp4.safetensors" "diffusion_models"

# 2. Text Encoders (workflow node 288 loads qwen_3_4b.safetensors; fp4_mixed is the
# smaller alternative for the nvfp4 workflow variant)
download_file "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors" "text_encoders"
download_file "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b_fp4_mixed.safetensors" "text_encoders"

# 3. VAE
download_file "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors" "vae"

# 4. Checkpoints
download_file "https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO/resolve/main/v23/Qwen-Rapid-AIO-NSFW-v23.safetensors" "checkpoints"

# 5. Upscale models — REQUIRED for the hero-shot detail-refine pass
# (GENERATION_HIRES_DEFAULT / output.hires). Node 175 loads Nickelback for the
# photo refine branch; Remacri (node 211) is the dormant illustration branch.
# Note: only .pth builds are publicly downloadable; the workflow references the
# .pth filenames accordingly.
download_file "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x_Nickelback_70000G.pth" "upscale_models"
download_file "https://huggingface.co/FacehugmanIII/4x_foolhardy_Remacri/resolve/main/4x_foolhardy_Remacri.pth" "upscale_models"

# 6. IP-Adapter FaceID Models — DISABLED.
# These are SD1.5 adapters and are architecturally INCOMPATIBLE with the Qwen-Image-Edit /
# Z-Image (DiT) models this project actually uses. They cannot be loaded into the Qwen/Z-Image
# workflows, so downloading them only wastes ~2.5 GB. Identity preservation is handled via
# the composite-back inpaint chain (outfit/background never re-diffuse the face)
# plus a ReActor/inswapper face-swap on the pose step — see section 8 below and
# docs/RUNPOD_SETUP.md. PuLID/InstantID remain architecturally incompatible with
# Qwen-Image-Edit, so they are not an option here.
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

# 7. WAN 2.2 Image-to-Video (i2v) 14B — reels/video generation (~35.6 GB total).
# Dual-expert MoE: the high-noise expert denoises the first steps, the low-noise
# expert finishes; ComfyUI loads them sequentially so peak VRAM ~= one expert.
# fp8_scaled fits the 48 GB worker at vertical reel resolution. Consumed by
# workflows/wan_i2v.json (see docs). Note the 14B i2v uses the WAN 2.1 VAE +
# umt5 text encoder (NOT wan2.2_vae, which is the 5B TI2V model), and needs NO
# clip-vision model (unlike WAN 2.1 i2v). Paths verified against the Comfy-Org
# repackaged repos (mind the casing: 2.2 = _Repackaged, 2.1 = _repackaged).
download_file "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors" "diffusion_models"
download_file "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors" "diffusion_models"
download_file "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" "text_encoders"
download_file "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" "vae"

# 8. IDENTITY-LOCK stack (masked outfit/background edits + pose face-swap).
# These back the identity-preserving batch pipeline:
#   - GroundingDINO + SAM  -> text-prompted mask (outfit=clothing, background=person)
#                             feeding the composite-back InpaintModelConditioning chain.
#   - ReActor / inswapper  -> locks the hero's face onto the reposed body.
# Folder names below MUST match the Dockerfile.worker symlinks
# (sams, grounding-dino, bert-base-uncased, insightface, facerestore_models, facexlib).

# Helper: download an archive to /tmp and unzip into a target folder.
download_zip() {
    local url=$1
    local folder=$2
    local name=$(basename "$url")
    echo -e "${GREEN}Processing archive: $name ...${NC}"
    mkdir -p "$folder"
    wget -c "$url" -O "/tmp/$name"
    unzip -o "/tmp/$name" -d "$folder"
    rm -f "/tmp/$name"
    echo "Extracted to: $folder"
    echo "--------------------------------------"
}

# 8a. SAM checkpoint (vit_h = best mask quality). Dropdown key "sam_vit_h (2.56GB)".
download_file "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth" "sams"

# 8b. GroundingDINO SwinT config + weights. Dropdown key "GroundingDINO_SwinT_OGC (694MB)".
download_file "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/GroundingDINO_SwinT_OGC.cfg.py" "grounding-dino"
download_file "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/groundingdino_swint_ogc.pth" "grounding-dino"

# 8c. BERT text backbone that GroundingDINO loads. MUST be pre-staged or the node
# tries to fetch it from HuggingFace at runtime and hangs on the headless worker
# (the image sets HF_HUB_OFFLINE=1). Stage the minimal file set.
download_file "https://huggingface.co/google-bert/bert-base-uncased/resolve/main/config.json" "bert-base-uncased"
download_file "https://huggingface.co/google-bert/bert-base-uncased/resolve/main/tokenizer_config.json" "bert-base-uncased"
download_file "https://huggingface.co/google-bert/bert-base-uncased/resolve/main/tokenizer.json" "bert-base-uncased"
download_file "https://huggingface.co/google-bert/bert-base-uncased/resolve/main/vocab.txt" "bert-base-uncased"
download_file "https://huggingface.co/google-bert/bert-base-uncased/resolve/main/model.safetensors" "bert-base-uncased"

# 8d. ReActor face-swap: inswapper + insightface detector pack (buffalo_l).
download_file "https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/inswapper_128.onnx" "insightface"
# buffalo_l.zip unzips to 5 .onnx files; they must sit directly in
# insightface/models/buffalo_l/ (insightface app_root = models/insightface).
download_zip "https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/buffalo_l.zip" "insightface/models/buffalo_l"

# 8e. Face-restore model (cleans the swap seam) + facexlib helpers it needs.
download_file "https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/facerestore_models/codeformer-v0.1.0.pth" "facerestore_models"
download_file "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth" "facexlib"
download_file "https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth" "facexlib"

echo -e "${GREEN}All downloads finished!${NC}"