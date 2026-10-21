"""D3b2 display-dims review fix (PR143 comment): real rotated+anamorphic artifacts.

Proves the server's exact-dims check against the ENCODER's display geometry
using actual ffmpeg/ffprobe bytes (no format mocks here):

- canonical ``MediaBlob.width/height`` are CODED dims (raw ffprobe stream
  dims: pre-rotation, pre-SAR) — asserted on the synthetic sources;
- the encoder's ``probe_source`` yields DISPLAY dims (SAR-adjusted,
  rotation-swapped) and ``short_side_target_dims`` plans every slot from
  them — both imported from the real ``mac-agent/src/package_encoder.py``;
- rotated-90 (SAR == 1) honest output is ACCEPTED by the real
  ``validate_slot_artifact`` + ``check_small_source_alias`` chain
  (rotation-aware candidates ``{E, transpose(E)}``);
- wrong dims (upscaled but within caps) are still REJECTED where the server
  has trustworthy dims, and the worker display claim is ignored either way;
- anamorphic (SAR != 1) honest output FAILS CLOSED with a documented error
  (the server cannot derive display width from coded dims alone; narrow
  plan in ``check_small_source_alias``) — pinned so the residual can only
  be lifted by real display-dims provenance, never by guesswork.

Requires ffmpeg+ffprobe binaries (skipped otherwise, same as the encoder
suite). Small-source alias rotation-invariance is covered through the light
slot here; fencing/lease/publish-timeout/flag behaviour is untouched and
covered by ``test_web_package_fenced_slots_d3b2.py``.
"""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.config import get_settings
from app.models.media import MediaJob
from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
from app.models.photos_asset import PhotosAsset

REPO_ROOT = Path(__file__).resolve().parents[2]
_ENCODER_SRC = REPO_ROOT / "mac-agent" / "src"


def _encoder_module():
    """Import the REAL mac-agent encoder (stdlib-only imports, noMac deps)."""
    if "ppa_pkg.package_encoder" in sys.modules:
        return sys.modules["ppa_pkg.package_encoder"]
    pkg = types.ModuleType("ppa_pkg")
    pkg.__path__ = [str(_ENCODER_SRC)]
    sys.modules["ppa_pkg"] = pkg
    for name in ("transcoder", "package_encoder"):
        spec = importlib.util.spec_from_file_location(
            f"ppa_pkg.{name}", _ENCODER_SRC / f"{name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"ppa_pkg.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["ppa_pkg.package_encoder"]


def _need_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg+ffprobe required")


def _ffprobe_video(path: Path) -> dict:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", str(path)],
        timeout=60,
    ).decode()
    streams = json.loads(out).get("streams", [])
    return next(s for s in streams if s.get("codec_type") == "video")


def _gen_source(path: Path, w: int, h: int, rotate: int | None = None,
                sar: str | None = None) -> None:
    """Synthetic camera source: testsrc H.264, optional SEI rotation / SAR."""
    _need_ffmpeg()
    vf = "format=yuv420p"
    if sar:
        vf = f"setsar=sar={sar}," + vf
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=s={w}x{h}:r=15:d=0.6",
         "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
         "-color_range", "tv", "-colorspace", "bt709",
         "-color_primaries", "bt709", "-color_trc", "bt709", str(path)],
        check=True, capture_output=True, timeout=120,
    )
    if rotate:
        # Same mechanism as the encoder suite: rotation travels as H.264
        # display-orientation SEI (mp4 muxer cannot write displaymatrix),
        # detected by the encoder's first-frame fallback — the path real
        # rotated phone sources take.
        rotated = path.with_name(path.stem + "_rot.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-c", "copy",
             "-bsf:v", f"h264_metadata=display_orientation=insert:rotate={rotate}",
             str(rotated)],
            check=True, capture_output=True, timeout=60,
        )
        rotated.replace(path)


def _gen_slot(path: Path, w: int, h: int) -> None:
    """Real slot bytes at exact dims: H.264 High / yuv420p / BT.709 faststart."""
    _need_ffmpeg()
    assert w % 2 == 0 and h % 2 == 0
    # veryfast (not ultrafast) so x264 honors High profile; BT.709 VUI is
    # forced via bitstream metadata because lavfi testsrc carries no color
    # tags for the -color_* output options to propagate.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=s={w}x{h}:r=15:d=0.6",
         "-vf", f"scale={w}:{h},setsar=1,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-profile:v", "high", "-color_range", "tv", "-colorspace", "bt709",
         "-color_primaries", "bt709", "-color_trc", "bt709",
         "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1"
                    ":matrix_coefficients=1:video_full_range_flag=0",
         "-movflags", "+faststart", str(path)],
        check=True, capture_output=True, timeout=120,
    )


def _gen_poster(path: Path, src: Path) -> None:
    _need_ffmpeg()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1", str(path)],
        check=True, capture_output=True, timeout=60,
    )


def _seed_coded_source(db, video_uuid, raw: bytes, width: int, height: int) -> str:
    """Canonical blob stores CODED dims, like verified ingest (raw stream w/h)."""
    settings = get_settings()
    sha = hashlib.sha256(raw).hexdigest()
    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                     width=width, height=height))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=sha,
                         rendition_semantics="photos_edited_rendition"))
    db.commit()
    return sha


def _pinned_job(db, asset, sha, transform_version="ffmpeg-h264-web-v1"):
    from datetime import datetime, timedelta

    from app.services.web_packages import set_finalized_state as _sfs

    job = MediaJob(photos_asset_id=asset.id, media_key="d" + "0" * 63,
                   rendition="web_package", status="claimed",
                   claimed_by="mac-media-01", lease_token="t" * 32, attempts=1)
    job.claimed_until = datetime.utcnow() + timedelta(minutes=5)
    db.add(job)
    db.flush()
    blob = db.get(MediaBlob, sha)
    _sfs(job, {"source_sha256": sha, "source_revision_id": 1,
               "source_width": blob.width, "source_height": blob.height,
               "transform_version": transform_version,
               "hq_aliased_to": None, "slots": {}})
    db.flush()
    return job


def _asset(db, uuid):
    asset = PhotosAsset(video_uuid=uuid, media_type="video", width=640, height=480)
    db.add(asset)
    db.flush()
    return asset


def test_server_mirror_matches_encoder_rule_and_swap_symmetry():
    """The server mirror == encoder rule on display dims; swap(E) == E(swapped).

    This is the load-bearing identity behind rotation-aware candidates: the
    encoder plans from display dims, the server mirrors the same function on
    coded dims, and a 90/270-degree rotation provably maps one to the other.
    """
    enc = _encoder_module()
    from app.services.web_packages import _expected_short_side_dims

    assert enc.HQ_SHORT_SIDE == 1080 and enc.LIGHT_SHORT_SIDE == 720
    for dims in [(1920, 1080), (1080, 1920), (640, 480), (480, 640),
                 (1280, 720), (720, 1280), (320, 240), (1440, 1080),
                 (1081, 1921), (721, 1281), (640, 640), (100, 4000)]:
        for cap in (1080, 720):
            assert _expected_short_side_dims(*dims, cap) == \
                enc.short_side_target_dims(*dims, cap) == \
                tuple(enc.short_side_target_dims(*dims, cap))
            w, h = dims
            assert enc.short_side_target_dims(h, w, cap) == \
                enc.short_side_target_dims(w, h, cap)[::-1]


def test_rotated_source_honest_slots_accepted(test_db, tmp_path):
    """640x480 rot90: encoder display 480x640; server accepts hq/light/poster."""
    import app.services.web_packages as wp

    enc = _encoder_module()
    src = tmp_path / "src-rot90.mp4"
    _gen_source(src, 640, 480, rotate=90)
    coded = _ffprobe_video(src)
    # Canonical truth is coded: raw stream dims, no rotation applied.
    assert (int(coded["width"]), int(coded["height"])) == (640, 480)
    info = enc.probe_source(src, "ffprobe")
    # Encoder truth is display: rotation-swapped (same path as artists' phones).
    assert (info.coded_w, info.coded_h) == (640, 480)
    assert (info.display_w, info.display_h) == (480, 640)
    assert info.rotation == 90

    uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
    asset = _asset(test_db, uuid)
    sha = _seed_coded_source(test_db, uuid, src.read_bytes(), 640, 480)
    job = _pinned_job(test_db, asset, sha)

    # Encoder-planned dims from DISPLAY dims (short 480 < 720: no upscale).
    light_dims = enc.short_side_target_dims(info.display_w, info.display_h, 720)
    assert light_dims == (480, 640)
    light_path = tmp_path / "light.mp4"
    _gen_slot(light_path, *light_dims)
    probed = wp.validate_slot_artifact(
        path=light_path, slot="light",
        expected_sha256=hashlib.sha256(light_path.read_bytes()).hexdigest(),
        expected_size=light_path.stat().st_size)
    assert (probed["width"], probed["height"]) == (480, 640)
    # Pre-fix this raised 400 (expected 640x480 from coded dims). Now accepted.
    applicable = wp.check_small_source_alias(
        db=test_db, job=job, slot="light", hq_aliased_to=None,
        claimed_w=480, claimed_h=640,
        probed_w=probed["width"], probed_h=probed["height"],
        source_sha256=sha)
    assert applicable == ["hq", "light", "poster"]
    # Small-source alias path admits on the rotation-invariant short side.
    applicable_alias = wp.check_small_source_alias(
        db=test_db, job=job, slot="light", hq_aliased_to="light",
        claimed_w=480, claimed_h=640,
        probed_w=probed["width"], probed_h=probed["height"],
        source_sha256=sha)
    assert applicable_alias == ["light", "poster"]
    # Poster rides the light branch: real JPEG at display dims validates too.
    poster_path = tmp_path / "poster.jpg"
    _gen_poster(poster_path, light_path)
    pprobed = wp.validate_slot_artifact(
        path=poster_path, slot="poster",
        expected_sha256=hashlib.sha256(poster_path.read_bytes()).hexdigest(),
        expected_size=poster_path.stat().st_size)
    assert (pprobed["width"], pprobed["height"]) == (480, 640)
    assert wp.check_small_source_alias(
        db=test_db, job=job, slot="poster", hq_aliased_to=None,
        claimed_w=480, claimed_h=640,
        probed_w=pprobed["width"], probed_h=pprobed["height"],
        source_sha256=sha) == ["hq", "light", "poster"]


def test_rotated_source_transpose_candidate_accepted(test_db, tmp_path):
    """Both orientations admitted: the server cannot tell which the source had.

    Pins the documented orientation tolerance: for a coded 640x480 source,
    probed (640, 480) AND (480, 640) both pass. Scale/caps/no-upscale proof
    is identical either way (same short side, pixel count, caps); the only
    admitted ambiguity is pure transposition.
    """
    import app.services.web_packages as wp

    uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"
    asset = _asset(test_db, uuid)
    sha = _seed_coded_source(test_db, uuid, b"rotated-bytes", 640, 480)
    job = _pinned_job(test_db, asset, sha)
    for probed in ((640, 480), (480, 640)):
        assert wp.check_small_source_alias(
            db=test_db, job=job, slot="light", hq_aliased_to=None,
            claimed_w=None, claimed_h=None,
            probed_w=probed[0], probed_h=probed[1],
            source_sha256=sha) == ["hq", "light", "poster"]


def test_rotated_source_wrong_dims_still_rejected(test_db, tmp_path):
    """Upscaled-but-within-caps output is rejected: exactness retained."""
    import app.services.web_packages as wp

    uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3"
    asset = _asset(test_db, uuid)
    sha = _seed_coded_source(test_db, uuid, b"rotated-bytes-3", 640, 480)
    job = _pinned_job(test_db, asset, sha)
    # 960x720 is within the light cap and perfectly valid H.264 — but it is
    # NOT what the encoder rule yields for this source (no upscale allowed).
    wrong_path = tmp_path / "wrong.mp4"
    _gen_slot(wrong_path, 960, 720)
    probed = wp.validate_slot_artifact(
        path=wrong_path, slot="light",
        expected_sha256=hashlib.sha256(wrong_path.read_bytes()).hexdigest(),
        expected_size=wrong_path.stat().st_size)
    assert (probed["width"], probed["height"]) == (960, 720)
    with pytest.raises(ValueError, match="light dims 960x720"):
        wp.check_small_source_alias(
            db=test_db, job=job, slot="light", hq_aliased_to=None,
            claimed_w=480, claimed_h=640,
            probed_w=probed["width"], probed_h=probed["height"],
            source_sha256=sha)


def test_worker_display_claim_never_trusted(test_db):
    """Bogus claims change nothing; honest claims smuggle nothing."""
    import app.services.web_packages as wp

    uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4"
    asset = _asset(test_db, uuid)
    sha = _seed_coded_source(test_db, uuid, b"claim-bytes", 640, 480)
    job = _pinned_job(test_db, asset, sha)
    honest = dict(db=test_db, job=job, slot="light", hq_aliased_to=None,
                  probed_w=480, probed_h=640, source_sha256=sha)
    # Wildly wrong claim + honest artifact: accepted (claim ignored).
    assert wp.check_small_source_alias(**honest, claimed_w=9999, claimed_h=9999) == \
        ["hq", "light", "poster"]
    # Honest claim + wrong artifact: rejected (claim cannot smuggle dims).
    bad = dict(honest, claimed_w=480, claimed_h=640, probed_w=960, probed_h=720)
    with pytest.raises(ValueError, match="light dims 960x720"):
        wp.check_small_source_alias(**bad)


def test_anamorphic_honest_output_fails_closed(test_db, tmp_path):
    """320x240 SAR 2:1: encoder display 640x240; server refuses (documented).

    The server holds coded dims only and cannot derive ``round(320 * 2)``.
    Failing closed here is the conservative choice: admitting the mismatch
    would also admit any same-caps upscale for square-pixel sources. Pinned
    so the residual is lifted only by real display-dims provenance (narrow
    plan in ``check_small_source_alias``), never by guesswork. Fencing is
    untouched: the refusal is dims-only, same SHA/lease path as every slot.
    """
    import app.services.web_packages as wp

    enc = _encoder_module()
    src = tmp_path / "src-sar.mp4"
    _gen_source(src, 320, 240, sar="2/1")
    coded = _ffprobe_video(src)
    assert (int(coded["width"]), int(coded["height"])) == (320, 240)
    assert str(coded.get("sample_aspect_ratio")) == "2:1"
    info = enc.probe_source(src, "ffprobe")
    assert (info.display_w, info.display_h) == (640, 240)

    uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa5"
    asset = _asset(test_db, uuid)
    sha = _seed_coded_source(test_db, uuid, src.read_bytes(), 320, 240)
    job = _pinned_job(test_db, asset, sha)

    honest_light = enc.short_side_target_dims(info.display_w, info.display_h, 720)
    assert honest_light == (640, 240)
    light_path = tmp_path / "sar-light.mp4"
    _gen_slot(light_path, *honest_light)
    probed = wp.validate_slot_artifact(
        path=light_path, slot="light",
        expected_sha256=hashlib.sha256(light_path.read_bytes()).hexdigest(),
        expected_size=light_path.stat().st_size)
    assert (probed["width"], probed["height"]) == (640, 240)
    with pytest.raises(ValueError, match="failing closed"):
        wp.check_small_source_alias(
            db=test_db, job=job, slot="light", hq_aliased_to=None,
            claimed_w=640, claimed_h=240,
            probed_w=probed["width"], probed_h=probed["height"],
            source_sha256=sha)
    # Alias path stays fail-closed too: no arbitrary alias on unprovable dims.
    with pytest.raises(ValueError, match="hq_aliased_to rejected"):
        wp.check_small_source_alias(
            db=test_db, job=job, slot="light", hq_aliased_to="light",
            claimed_w=640, claimed_h=240,
            probed_w=probed["width"], probed_h=probed["height"],
            source_sha256=sha)
