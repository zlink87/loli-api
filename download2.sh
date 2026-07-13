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

# 8f. DARK ASSET (07-14, ships OFF) — GPEN-BFR-512, a sharper/less-waxy face-restore
# model than CodeFormer for the pose ReActor pass (node 200 / node 215 ReActorFaceBoost).
# Same dataset repo + folder as codeformer above (8e) so it needs no new symlink.
# Inert until POSE_REACTOR_FACE_RESTORE_MODEL=GPEN-BFR-512.onnx is set AND/OR
# COMFYUI_POSE_WORKFLOW_PATH_2511 points at workflows/pose_2511_faceboost_API.json —
# see docs/RUNPOD_SETUP.md "Dark quality assets".
download_file "https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/facerestore_models/GPEN-BFR-512.onnx" "facerestore_models"

# 9. STAGE-2 MASK UPGRADE — ComfyUI-RMBG (garment-class masks + SAM3). Staged
# for a future workflow variant; no live workflow references these yet (see
# Dockerfile.worker). Folder names MUST match the Dockerfile.worker symlinks
# (sam3, RMBG) and were verified against ComfyUI-RMBG's own path resolution:
#   AILab_SAM3Segment.py  -> falls back to <models_dir>/sam3/sam3.pt
#   AILab_ClothSegment.py -> hardcodes <models_dir>/RMBG/segformer_clothes/
download_file "https://huggingface.co/1038lab/sam3/resolve/main/sam3.pt" "sam3"
download_file "https://huggingface.co/1038lab/segformer_clothes/resolve/main/config.json" "RMBG/segformer_clothes"
download_file "https://huggingface.co/1038lab/segformer_clothes/resolve/main/model.safetensors" "RMBG/segformer_clothes"
download_file "https://huggingface.co/1038lab/segformer_clothes/resolve/main/preprocessor_config.json" "RMBG/segformer_clothes"

# 10. TIER A — FULL (non-distilled) Qwen-Image-Edit-2511 quality path.
# ONLY needed when COMFYUI_OUTFIT_WORKFLOW_PATH_2511 is enabled (workflow
# workflows/outfit_cropstitch_2511full_API.json). This is the full 2511 model loaded
# natively (UNet + CLIP + VAE) at >20 steps / cfg 2.5 instead of the 4-8 step distilled
# Rapid AIO, plus a realism LoRA and an NSFW LoRA. Adds ~30 GB to the worker image.
# IMPORTANT: the filenames below MUST match the workflow's loader nodes
# (301 UNETLoader, 302 CLIPLoader, 303 VAELoader, 304/305 LoraLoaderModelOnly). VERIFY
# each URL against the current Comfy-Org / author repos before building — repo paths
# change over time and these were NOT download-tested. If a path 404s, find the current
# one on the Comfy-Org HF repos (mind repo casing).
#
# 10a. Diffusion model — Comfy-Org fp8mixed (~20 GB). (bf16 = qwen_image_edit_2511_bf16.safetensors ~41 GB.)
download_file "https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors" "diffusion_models"
# 10b. Qwen2.5-VL text encoder (fp8 ~8 GB) — shared with base Qwen-Image-Edit.
download_file "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" "text_encoders"
# 10c. Qwen-Image VAE.
download_file "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors" "vae"
# 10d. Realism LoRA (node 304): anti-plastic, identity-preserving. Apache-2.0. The repo
# ships epoch checkpoints URP_5/10/15/20 — 20 = most trained (drop to 15 if it overcooks).
download_file "https://huggingface.co/prithivMLmods/Qwen-Image-Edit-2511-Ultra-Realistic-Portrait/resolve/main/URP_20.safetensors" "loras"
# 10e. NSFW LoRA (node 305) — REQUIRED for HIGH-tier editing (base 2511 is only mildly
# NSFW). HF-hosted (wget-able) starting point for the Qwen-Image-Edit-Plus line:
download_file "https://huggingface.co/aiunivers/qwen-image-edit-plus-nsfw-lora/resolve/main/qwen-image-edit-plus-nsfw-lora.safetensors" "loras"
# A/B alternatives (mostly Civitai, need an API token): Meta4, Snofs, "Sex-tacular",
# qwen_MCNL. Swap node 305's lora_name + strength (0.8-1.0) to try them.

# 10f. DARK ASSET (07-14, ships OFF) — skin realism LoRA (node 306 on the *_skinlora
# variant graphs only: pose_2511_skinlora_API.json / outfit_cropstitch_2511full_skinlora_API.json).
# Stacks on top of the realism (304) + NSFW (305, dialed to 0.65 on these variants) LoRAs
# to fight the plastic-skin look. Inert until COMFYUI_POSE_WORKFLOW_PATH_2511 /
# COMFYUI_OUTFIT_WORKFLOW_PATH_2511 (or COMFYUI_BATCH_OUTFIT_WORKFLOW_PATH) point at one
# of those files — see docs/RUNPOD_SETUP.md "Dark quality assets".
download_file "https://huggingface.co/tlennon-ie/qwen-edit-skin/resolve/main/qwen-edit-skin.safetensors" "loras"

echo -e "${GREEN}All downloads finished!${NC}"