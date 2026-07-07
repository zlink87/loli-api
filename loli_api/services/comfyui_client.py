"""
ComfyUI WebSocket client for workflow execution.
Based on ImageClient pattern from existing app.py lines 677-731.
"""
import json
import uuid
import copy
import urllib.request
import urllib.parse
import websocket
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging
import requests

from services import output_presets
from services import prompt_constants as pc

logger = logging.getLogger(__name__)

class ComfyUIClient:
    """
    Client for ComfyUI API communication via WebSocket.
    Handles workflow submission, execution monitoring, and result retrieval.
    """

    def __init__(
        self,
        server_address: str,
        client_id: Optional[str] = None
    ):
        """
        Initialize ComfyUI client.

        Args:
            server_address: ComfyUI server address (e.g., "127.0.0.1:8188")
            client_id: Optional client identifier for WebSocket
        """
        self.server_address = server_address
        self.client_id = client_id or str(uuid.uuid4())
        self._ws: Optional[websocket.WebSocket] = None

    def connect(self) -> None:
        """Establish WebSocket connection."""
        ws_url = f"ws://{self.server_address}/ws?clientId={self.client_id}"
        logger.info(f"Connecting to ComfyUI WebSocket: {ws_url}")
        self._ws = websocket.WebSocket()
        self._ws.connect(ws_url)
        logger.info("WebSocket connected")

    def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._ws:
            try:
                self._ws.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            finally:
                self._ws = None
            logger.info("WebSocket disconnected")

    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and self._ws.connected

    def queue_prompt(self, prompt: dict) -> dict:
        """
        Submit a prompt to the ComfyUI queue.

        Args:
            prompt: The workflow dictionary

        Returns:
            Response with prompt_id
        """
        payload = {"prompt": prompt, "client_id": self.client_id}
        data = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(
            f"http://{self.server_address}/prompt",
            data=data,
            headers={"Content-Type": "application/json"}
        )

        response = urllib.request.urlopen(req)
        result = json.loads(response.read())
        logger.info(f"Queued prompt: {result.get('prompt_id', 'unknown')}")
        return result

    def get_history(self, prompt_id: str) -> dict:
        """
        Fetch execution history for a prompt.

        Args:
            prompt_id: The prompt identifier

        Returns:
            History data dictionary
        """
        url = f"http://{self.server_address}/history/{prompt_id}"
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read())

    def get_image(
        self,
        filename: str,
        subfolder: str,
        folder_type: str
    ) -> bytes:
        """
        Download an image from ComfyUI output.

        Args:
            filename: Image filename
            subfolder: Subfolder path
            folder_type: Folder type (output/input/temp)

        Returns:
            Image bytes
        """
        data = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type
        }
        url_values = urllib.parse.urlencode(data)
        url = f"http://{self.server_address}/view?{url_values}"

        with urllib.request.urlopen(url) as response:
            return response.read()

    def upload_image_bytes(self, filename: str, image_bytes: bytes, content_type: str = "image/png") -> str:
        """
        Upload an image to ComfyUI and return the stored filename.

        Args:
            filename: Original filename
            image_bytes: Raw image bytes
            content_type: MIME type (e.g. image/png)

        Returns:
            ComfyUI image name, possibly with subfolder prefix
        """
        url = f"http://{self.server_address}/upload/image"
        logger.info(f"Uploading image to ComfyUI: filename={filename}, size={len(image_bytes)} bytes, content_type={content_type}")

        files = {"image": (filename, image_bytes, content_type)}
        data = {"overwrite": "true", "type": "input"}
        response = requests.post(url, files=files, data=data, timeout=30)
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"ComfyUI upload response: {response_data}")

        name = response_data.get("name")
        subfolder = response_data.get("subfolder", "")
        if not name:
            raise RuntimeError(f"Upload response missing name: {response_data}")

        result = f"{subfolder}/{name}" if subfolder else name
        logger.info(f"ComfyUI image stored as: {result}")
        return result

    def execute_workflow(
        self,
        workflow: dict,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, List[bytes]]:
        """
        Execute a workflow and wait for completion.

        Args:
            workflow: The prepared workflow dictionary
            progress_callback: Optional callback(node_id, progress) for updates

        Returns:
            Dict mapping node_id to list of image bytes

        Raises:
            RuntimeError: If WebSocket not connected or execution fails
        """
        if not self._ws:
            raise RuntimeError("WebSocket not connected. Call connect() first.")

        # Queue the prompt
        response = self.queue_prompt(workflow)
        prompt_id = response.get('prompt_id')

        if not prompt_id:
            raise RuntimeError(f"Failed to queue prompt: {response}")

        logger.info(f"Executing workflow with prompt_id: {prompt_id}")
        output_images = {}

        # Listen for completion
        while True:
            try:
                out = self._ws.recv()

                if isinstance(out, str):
                    message = json.loads(out)
                    msg_type = message.get('type')
                    data = message.get('data', {})

                    if msg_type == 'progress':
                        # Report progress
                        if progress_callback:
                            node = data.get('node')
                            value = data.get('value', 0)
                            max_val = data.get('max', 100)
                            progress = value / max_val if max_val > 0 else 0
                            progress_callback(node, progress)

                    elif msg_type == 'executing':
                        node = data.get('node')
                        current_prompt_id = data.get('prompt_id')

                        if node is None and current_prompt_id == prompt_id:
                            # Execution complete
                            logger.info(f"Workflow execution complete: {prompt_id}")
                            break

                    elif msg_type == 'execution_error':
                        error_msg = data.get('exception_message', 'Unknown error')
                        raise RuntimeError(f"ComfyUI execution error: {error_msg}")

                # Binary data (preview images) - skip

            except websocket.WebSocketException as e:
                raise RuntimeError(f"WebSocket error during execution: {e}")

        # Fetch output images from history
        history = self.get_history(prompt_id)

        if prompt_id not in history:
            raise RuntimeError(f"No history found for prompt: {prompt_id}")

        prompt_history = history[prompt_id]
        outputs = prompt_history.get('outputs', {})

        for node_id, node_output in outputs.items():
            if 'images' in node_output:
                images_output = []
                for image_info in node_output['images']:
                    try:
                        image_data = self.get_image(
                            image_info['filename'],
                            image_info.get('subfolder', ''),
                            image_info.get('type', 'output')
                        )
                        images_output.append(image_data)
                        logger.debug(f"Retrieved image from node {node_id}: {image_info['filename']}")
                    except Exception as e:
                        logger.error(f"Failed to retrieve image: {e}")

                if images_output:
                    output_images[node_id] = images_output

        logger.info(f"Retrieved {sum(len(v) for v in output_images.values())} images from {len(output_images)} nodes")
        return output_images

    @staticmethod
    def prepare_character_workflow(
        workflow_template: dict,
        character_prompt: str,
        seed: Optional[int] = None,
        filename_prefix: str = "CHAR",
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        batch_size: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        photo_style: Optional[str] = None,
        hires: bool = False,
        time_of_day: Optional[str] = None,
    ) -> dict:
        """
        Prepare the character creation workflow with injected parameters.

        Based on amazing-z-photo_API(Create CHAR).json analysis:
        - Node 110: Character prompt (PrimitiveStringMultiline) - MAIN INPUT
        - Node 125: Photo-style wrapper template (rewritten per photo_style)
        - Node 67: Seed value (optional, uses workflow default if not provided)
        - Node 207: Output switch — single-pass (284) vs detail-refine (300)
        - Node 9: Output filename prefix

        Args:
            workflow_template: Base workflow dictionary
            character_prompt: Generated character description prompt
            seed: Optional random seed for generation (None = use workflow default)
            filename_prefix: Output filename prefix
            resolution: Optional whitelisted resolution override (e.g., "1088x1600")
            aspect_ratio: Optional aspect ratio preset (e.g., "2:3")
            batch_size: Optional batch size override (1-4)
            photo_style: PhotoStyleType value; rewrites the node 125 wrapper.
                None/unknown = keep the workflow's baked-in template.
            hires: When True, route the output through the detail-refine branch
                (upscale-model round trip + refine steps; same output resolution).
            time_of_day: TimeOfDayType value; swaps the polished wrapper's
                lighting sentence for a time-matched grade (night stays polished
                low-key instead of fighting the daylight grade). None = default.

        Returns:
            Modified workflow dictionary ready for execution
        """
        workflow = copy.deepcopy(workflow_template)

        # Node 110: Inject character prompt into PrimitiveStringMultiline
        # This is the ONLY required parameter from API
        if "110" in workflow:
            workflow["110"]["inputs"]["value"] = character_prompt
            logger.debug(f"Set character prompt in node 110 ({len(character_prompt)} chars)")

        # Node 125: Photo-style wrapper. The workflow substitutes the API prompt
        # into this template AFTER Grok polish (inside ComfyUI), so the finish
        # here is immune to the polisher. Unknown/None -> baked-in text stands.
        if photo_style and "125" in workflow:
            template_text = pc.photo_style_template(photo_style, time_of_day)
            if template_text:
                workflow["125"]["inputs"]["value"] = template_text
                logger.debug(
                    f"Set photo style wrapper in node 125: {photo_style}"
                    + (f" @ {time_of_day}" if time_of_day else "")
                )

        # Node 207: output switch. Default input is node 284 (single-pass decode).
        # hires re-points it at node 300 (VAEDecode of the refine sampler 181),
        # activating the dormant upscale-model + refine branch.
        if hires and "207" in workflow and "300" in workflow:
            workflow["207"]["inputs"]["any_01"] = ["300", 0]
            if seed is not None and "181" in workflow:
                workflow["181"]["inputs"]["noise_seed"] = seed
            logger.debug("Enabled detail-refine output branch (node 207 -> 300)")

        # Node 7: Inject negative prompt if the workflow has a negative text node.
        # The input field name varies by node type, so set whichever string field exists.
        if negative_prompt and "7" in workflow:
            node7_inputs = workflow["7"].get("inputs", {})
            for key in ("text", "value", "prompt", "string"):
                if key in node7_inputs:
                    node7_inputs[key] = negative_prompt
                    logger.debug(f"Set negative prompt in node 7 (field '{key}')")
                    break

        # Node 67: Set seed in SamplerCustom (optional)
        if seed is not None:
            if "67" in workflow:
                workflow["67"]["inputs"]["noise_seed"] = seed
                logger.debug(f"Set seed in node 67: {seed}")

            # Also set seed in node 50 (KSamplerAdvanced) if present
            if "50" in workflow:
                workflow["50"]["inputs"]["noise_seed"] = seed

        # Dims come from the whitelist (services/output_presets.py) — explicit
        # resolution wins over the aspect-ratio preset; both are validated at the
        # API edge, so unknown values simply fall back to the template defaults.
        width = None
        height = None
        if resolution or aspect_ratio:
            width, height = output_presets.dims_for(
                aspect_ratio=aspect_ratio, resolution=resolution
            )

        if width and height:
            if "243" in workflow:
                workflow["243"]["inputs"]["value"] = width
            if "248" in workflow:
                workflow["248"]["inputs"]["value"] = height
            if "56" in workflow:
                workflow["56"]["inputs"]["width"] = width
                workflow["56"]["inputs"]["height"] = height
            if "244" in workflow:
                if isinstance(workflow["244"]["inputs"].get("width"), int):
                    workflow["244"]["inputs"]["width"] = width
                if isinstance(workflow["244"]["inputs"].get("height"), int):
                    workflow["244"]["inputs"]["height"] = height
            logger.debug(f"Set resolution to {width}x{height}")

        if batch_size:
            if "244" in workflow:
                workflow["244"]["inputs"]["batch_size"] = batch_size
            if "56" in workflow:
                workflow["56"]["inputs"]["batch_size"] = batch_size
            logger.debug(f"Set batch size to {batch_size}")

        # Node 9: Set output filename prefix
        if "9" in workflow:
            date_str = datetime.now().strftime("%Y_%m_%d")
            workflow["9"]["inputs"]["filename_prefix"] = f"ZImage/{date_str}/{filename_prefix}"
            logger.debug(f"Set filename prefix in node 9")

        return workflow

    @staticmethod
    def prepare_edit_workflow(
        workflow_template: dict,
        input_image_name: str,
        seed: Optional[int] = None,
        prompt: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> dict:
        """
        Prepare an image edit workflow with injected parameters.

        Args:
            workflow_template: Base workflow dictionary
            input_image_name: Uploaded ComfyUI image name
            seed: Optional seed override
            prompt: Optional prompt override
            negative_prompt: Optional negative prompt override

        Returns:
            Modified workflow dictionary ready for execution
        """
        workflow = copy.deepcopy(workflow_template)

        logger.info(f"Preparing edit workflow with input_image_name={input_image_name}")

        if "8" in workflow:
            workflow["8"]["inputs"]["image"] = input_image_name
            logger.info(f"Set node 8 image input to: {input_image_name}")
        else:
            logger.warning("Node 8 (LoadImage) not found in workflow template!")

        if seed is not None and "2" in workflow:
            workflow["2"]["inputs"]["seed"] = seed
            logger.info(f"Set node 2 seed to: {seed}")

        if prompt and "3" in workflow:
            workflow["3"]["inputs"]["prompt"] = prompt
            logger.info(f"Set node 3 prompt")

        if negative_prompt and "4" in workflow:
            workflow["4"]["inputs"]["prompt"] = negative_prompt
            logger.info(f"Set node 4 negative prompt")

        if width and height and "9" in workflow:
            workflow["9"]["inputs"]["width"] = width
            workflow["9"]["inputs"]["height"] = height
            logger.info(f"Set node 9 dimensions to: {width}x{height}")

        return workflow

    def check_server_status(self) -> dict:
        """
        Check ComfyUI server status.

        Returns:
            Server status dictionary
        """
        try:
            url = f"http://{self.server_address}/system_stats"
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read())
        except Exception as e:
            logger.warning(f"Failed to get server status: {e}")
            return {"error": str(e)}

    def interrupt_execution(self) -> bool:
        """
        Interrupt current execution.

        Returns:
            True if interrupt request sent successfully
        """
        try:
            req = urllib.request.Request(
                f"http://{self.server_address}/interrupt",
                method="POST"
            )
            urllib.request.urlopen(req)
            logger.info("Sent interrupt request to ComfyUI")
            return True
        except Exception as e:
            logger.error(f"Failed to interrupt: {e}")
            return False
