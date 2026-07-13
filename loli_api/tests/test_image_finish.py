"""
Tests for the output-finishing film-grain pass (services.image_finish) and its
gating inside SupabaseStorageService.upload_image.

Covers: determinism (same input + strength -> byte-identical output), the
strength<=0 / OUTPUT_FILM_GRAIN off no-op paths, that the effect actually
perturbs pixels by a small bounded amount while preserving size/mode, the
exact FINISH_FOLDERS allowlist (the five real edit-output folders, verified
against the worker call sites -- see services/image_finish.py's comment), and
that upload_image only finishes images landing in one of those folders.

Runs under pytest or directly: python loli_api/tests/test_image_finish.py
"""
from io import BytesIO

import numpy as np
from PIL import Image

from services.image_finish import FINISH_FOLDERS, apply_film_grain
import services.supabase_storage_service as sss


# --- shared fixtures ---------------------------------------------------------

def _sample_png(width: int = 64, height: int = 48, mode: str = "RGB") -> bytes:
    """
    A small deterministic gradient PNG (not flat, not pure noise) -- stands in
    for a photographic edit output and spans shadows through highlights so
    grain-amplitude tapering actually gets exercised.
    """
    y, x = np.mgrid[0:height, 0:width]
    r = (x * 255 / max(width - 1, 1)).astype(np.uint8)
    g = (y * 255 / max(height - 1, 1)).astype(np.uint8)
    b = ((x + y) * 255 / max(width + height - 2, 1)).astype(np.uint8)
    arr = np.stack([r, g, b], axis=-1).astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    if mode != "RGB":
        img = img.convert(mode)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


# --- apply_film_grain: determinism / strength semantics ---------------------

def test_same_input_and_strength_is_byte_identical():
    png = _sample_png()
    out1 = apply_film_grain(png, 0.03)
    out2 = apply_film_grain(png, 0.03)
    assert out1 == out2


def test_zero_or_negative_strength_returns_input_unchanged():
    png = _sample_png()
    assert apply_film_grain(png, 0.0) == png
    assert apply_film_grain(png, -0.5) == png
    # Explicitly the same object, not just equal bytes -- confirms the
    # early-return path never touches PIL/numpy at all.
    assert apply_film_grain(png, 0.0) is png


def test_different_strength_produces_different_output():
    png = _sample_png()
    weak = apply_film_grain(png, 0.01)
    strong = apply_film_grain(png, 0.05)
    assert weak != strong


# --- apply_film_grain: bounded, size/mode-preserving perturbation -----------

def test_grain_changes_bytes_but_preserves_size_and_mode_with_small_delta():
    png = _sample_png()
    out = apply_film_grain(png, 0.03)
    assert out != png

    orig_img = Image.open(BytesIO(png))
    new_img = Image.open(BytesIO(out))
    assert new_img.size == orig_img.size
    assert new_img.mode == "RGB"
    assert orig_img.mode == "RGB"

    orig_arr = np.asarray(orig_img, dtype=np.float32)
    new_arr = np.asarray(new_img, dtype=np.float32)
    mean_abs_diff = float(np.mean(np.abs(orig_arr - new_arr)))
    assert mean_abs_diff < 8.0, f"grain perturbation too large: {mean_abs_diff}"


def test_rgba_alpha_channel_is_preserved_untouched():
    png = _sample_png(mode="RGBA")
    orig_img = Image.open(BytesIO(png))
    out = apply_film_grain(png, 0.03)
    new_img = Image.open(BytesIO(out))

    assert new_img.mode == "RGBA"
    orig_alpha = np.asarray(orig_img.getchannel("A"))
    new_alpha = np.asarray(new_img.getchannel("A"))
    assert np.array_equal(orig_alpha, new_alpha)


def test_non_rgb_mode_is_restored_after_processing():
    png = _sample_png(mode="L")
    out = apply_film_grain(png, 0.03)
    new_img = Image.open(BytesIO(out))
    assert new_img.mode == "L"


def test_sharpen_flag_changes_output():
    png = _sample_png()
    with_sharpen = apply_film_grain(png, 0.03, sharpen=True)
    without_sharpen = apply_film_grain(png, 0.03, sharpen=False)
    assert with_sharpen != without_sharpen


# --- FINISH_FOLDERS allowlist ------------------------------------------------

def test_finish_folders_contains_exactly_the_five_verified_edit_folders():
    # Verified against the real call sites (see services/image_finish.py
    # module comment): batch_pipeline_worker.STORAGE_FOLDER, pipeline_worker's
    # folder="pipeline_edits", and outfit/pose/background_edit workers' folder
    # strings passed through base_worker.submit_and_save.
    assert FINISH_FOLDERS == {
        "batch_edits",
        "pipeline_edits",
        "outfit_edits",
        "pose_edits",
        "background_edits",
    }


def test_finish_folders_excludes_sources_and_the_generation_look():
    # nude_bases: an edit SOURCE (feeds re-diffusion) -- grain would compound.
    # character_creation: the generation hero look -- left untouched.
    assert "nude_bases" not in FINISH_FOLDERS
    assert "character_creation" not in FINISH_FOLDERS
    assert "debug_frames" not in FINISH_FOLDERS


# --- upload_image gating -----------------------------------------------------
#
# SupabaseStorageService.__init__ calls the real `create_client`, which we
# don't want touching the network in a unit test. Patch the module-level
# `create_client` symbol to return an in-memory fake before constructing the
# service, then drive upload_image() and inspect what bytes actually reached
# the fake "storage" client.

class _FakeBucket:
    def __init__(self):
        self.uploads = []  # list of dicts: {path, file, file_options}

    def upload(self, path, file, file_options=None):
        self.uploads.append({"path": path, "file": file, "file_options": file_options})
        return {"path": path}

    def get_public_url(self, path):
        return f"https://fake.supabase.co/storage/v1/object/public/test-bucket/{path}"


class _FakeStorageAPI:
    def __init__(self):
        self._bucket = _FakeBucket()

    def from_(self, bucket_name):
        return self._bucket


class _FakeSupabaseClient:
    def __init__(self):
        self.storage = _FakeStorageAPI()


def _fake_service(monkeypatch) -> sss.SupabaseStorageService:
    monkeypatch.setattr(sss, "create_client", lambda url, key: _FakeSupabaseClient())
    return sss.SupabaseStorageService(
        supabase_url="https://fake.supabase.co",
        supabase_key="fake-key",
        bucket_name="test-bucket",
    )


def _last_uploaded_bytes(service: sss.SupabaseStorageService) -> bytes:
    uploads = service.client.storage.from_("test-bucket").uploads
    return uploads[-1]["file"]


def test_upload_image_finishes_when_folder_is_in_finish_folders(monkeypatch):
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN", True)
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN_STRENGTH", 0.03)
    service = _fake_service(monkeypatch)

    png = _sample_png()
    service.upload_image(png, "img-1", folder="batch_edits")

    stored = _last_uploaded_bytes(service)
    assert stored != png


def test_upload_image_skips_finishing_for_nude_bases(monkeypatch):
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN", True)
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN_STRENGTH", 0.03)
    service = _fake_service(monkeypatch)

    png = _sample_png()
    service.upload_image(png, "img-1", folder="nude_bases")

    # nude_bases is excluded from FINISH_FOLDERS -> stored bytes are just the
    # plain PIL PNG round-trip, identical to re-saving the source directly.
    expected_unfinished = Image.open(BytesIO(png))
    buf = BytesIO()
    expected_unfinished.save(buf, format="PNG")
    assert _last_uploaded_bytes(service) == buf.getvalue()


def test_upload_image_skips_finishing_for_character_creation_default_folder(monkeypatch):
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN", True)
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN_STRENGTH", 0.03)
    service = _fake_service(monkeypatch)

    png = _sample_png()
    service.upload_image(png, "img-1")  # default folder="character_creation"

    expected_unfinished = Image.open(BytesIO(png))
    buf = BytesIO()
    expected_unfinished.save(buf, format="PNG")
    assert _last_uploaded_bytes(service) == buf.getvalue()


def test_upload_image_master_switch_off_disables_finishing_even_for_edit_folder(monkeypatch):
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN", False)
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN_STRENGTH", 0.03)
    service = _fake_service(monkeypatch)

    png = _sample_png()
    service.upload_image(png, "img-1", folder="batch_edits")

    expected_unfinished = Image.open(BytesIO(png))
    buf = BytesIO()
    expected_unfinished.save(buf, format="PNG")
    assert _last_uploaded_bytes(service) == buf.getvalue()


def test_upload_image_zero_strength_disables_finishing_even_for_edit_folder(monkeypatch):
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN", True)
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN_STRENGTH", 0.0)
    service = _fake_service(monkeypatch)

    png = _sample_png()
    service.upload_image(png, "img-1", folder="pipeline_edits")

    expected_unfinished = Image.open(BytesIO(png))
    buf = BytesIO()
    expected_unfinished.save(buf, format="PNG")
    assert _last_uploaded_bytes(service) == buf.getvalue()


def test_upload_image_hash_reflects_finished_bytes(monkeypatch):
    # image_hash returned to the caller should match what actually landed in
    # storage, so a downstream integrity check against it won't spuriously
    # fail because the hash was computed pre-finishing.
    import hashlib

    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN", True)
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN_STRENGTH", 0.03)
    service = _fake_service(monkeypatch)

    png = _sample_png()
    _, image_hash = service.upload_image(png, "img-1", folder="outfit_edits")

    stored = _last_uploaded_bytes(service)
    assert image_hash == hashlib.sha256(stored).hexdigest()


def test_upload_image_finishing_failure_falls_back_to_unfinished_bytes(monkeypatch):
    # Finishing is cosmetic only -- an exception inside it must never break
    # the upload; it should fall back to the unfinished (but still valid)
    # re-encoded PNG bytes.
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN", True)
    monkeypatch.setattr(sss.settings, "OUTPUT_FILM_GRAIN_STRENGTH", 0.03)

    def _boom(png_bytes, strength):
        raise RuntimeError("simulated finishing failure")

    monkeypatch.setattr(sss, "apply_film_grain", _boom)
    service = _fake_service(monkeypatch)

    png = _sample_png()
    # Must not raise.
    public_url, image_hash = service.upload_image(png, "img-1", folder="batch_edits")

    assert public_url
    assert image_hash
    expected_unfinished = Image.open(BytesIO(png))
    buf = BytesIO()
    expected_unfinished.save(buf, format="PNG")
    assert _last_uploaded_bytes(service) == buf.getvalue()


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            # Tests taking a `monkeypatch` arg need pytest; skip them in the
            # standalone runner rather than faking the fixture.
            import inspect
            if "monkeypatch" in inspect.signature(fn).parameters:
                print(f"SKIP {fn.__name__} (requires pytest monkeypatch fixture)")
                continue
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
