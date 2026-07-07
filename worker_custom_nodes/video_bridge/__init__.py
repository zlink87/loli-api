"""
VideoImagesBridge — a minimal ComfyUI custom node that encodes a batch of frames
to an mp4 and reports it under the node's ``images`` UI output key.

WHY THIS EXISTS
---------------
RunPod's worker-comfyui (5.8.6) output collector only harvests a node's
``images`` output key (handler.py: ``if "images" in node_output``). Its S3 upload
is otherwise format-agnostic — it takes the real extension off the filename,
uploads the bytes, and returns ``{"type":"s3_url","data":<url>,"filename":...}``.
``VHS_VideoCombine`` reports its mp4 under the ``gifs`` key instead, so the worker
logs it as an "unhandled output key" and drops it — the job returns
``success_no_images`` and the reel is lost.

This node writes the mp4 itself and lists it under ``images``, so worker-comfyui
uploads it to Supabase like any image and returns a ``.mp4`` s3_url. The loli-api
side already classifies a ``.mp4`` filename as video (runpod_client.parse_output).

Self-contained: depends only on numpy + imageio(+imageio-ffmpeg), which the worker
image already has (VHS pulls them in; the Dockerfile also installs them explicitly).
"""
import os
import numpy as np

import folder_paths


class VideoImagesBridge:
    """Encode IMAGE frames to mp4 and expose it under the collectable ``images`` key."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "frame_rate": ("INT", {"default": 16, "min": 1, "max": 60}),
                "filename_prefix": ("STRING", {"default": "video/reel"}),
            }
        }

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "video"

    def save(self, images, frame_rate=16, filename_prefix="video/reel"):
        import imageio

        # ComfyUI IMAGE is a torch tensor [N,H,W,C], float 0..1. Be defensive about type.
        arr = images
        if hasattr(arr, "detach"):
            arr = arr.detach().cpu().numpy()
        arr = np.asarray(arr)
        if arr.ndim == 3:  # single frame -> add batch dim
            arr = arr[None, ...]
        frames = np.clip(arr * 255.0, 0, 255).astype(np.uint8)  # [N,H,W,C]

        n, h, w = frames.shape[0], frames.shape[1], frames.shape[2]

        # Resolve an output path the same way SaveImage does (handles a subfolder
        # embedded in the prefix, e.g. "video/reel" -> subfolder "video").
        full_output_folder, filename, counter, subfolder, _ = (
            folder_paths.get_save_image_path(filename_prefix, folder_paths.get_output_directory(), w, h)
        )
        out_name = f"{filename}_{counter:05}.mp4"
        out_path = os.path.join(full_output_folder, out_name)

        # libx264 + yuv420p + even dims = broadly browser-compatible mp4.
        # macro_block_size=1 disables imageio's auto-resize-to-multiple-of-16.
        writer = imageio.get_writer(
            out_path,
            format="FFMPEG",
            fps=int(frame_rate),
            codec="libx264",
            pixelformat="yuv420p",
            macro_block_size=1,
            ffmpeg_log_level="error",
        )
        try:
            for i in range(n):
                writer.append_data(frames[i])
        finally:
            writer.close()

        print(f"VideoImagesBridge - wrote {n} frames -> {out_path}")

        # Report under "images" so worker-comfyui collects + uploads it.
        return {
            "ui": {
                "images": [
                    {"filename": out_name, "subfolder": subfolder, "type": "output"}
                ]
            }
        }


NODE_CLASS_MAPPINGS = {"VideoImagesBridge": VideoImagesBridge}
NODE_DISPLAY_NAME_MAPPINGS = {"VideoImagesBridge": "Video → Images Bridge (mp4)"}
