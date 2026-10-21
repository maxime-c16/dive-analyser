"""D3b2 REAL-MP4 validation tier (REAL ffprobe + ffmpeg decode, no fakes).

Builds a synthetic 2 s portrait 720x1280@60 H.264 MP4 (testsrc2, libx264
High, yuv420p, BT.709 VUI via the h264_metadata bsf, +faststart) and runs
``validate_slot_artifact`` against the REAL bytes through the REAL
``_ffprobe_streams`` / ``_mp4_faststart_ok`` / ``_ffmpeg_decode_ok`` paths.
This proves the validator is wired to actual media — a mocked-JSON tier
cannot catch a disconnected probe, a lax decode flag (see the ``-xerror``
fix: a 75%-truncated faststart file probes clean but must not validate),
or tag/faststart regressions.

Runs wherever ffmpeg + ffprobe exist (one skip guard for both — NO
Linux/CI skip: the backend image ships ffmpeg, and this Mac has it via
Homebrew). No zscale, no tonemap, no HDR source: SDR testsrc2 needs
neither. If libx264 is missing the encode fails LOUD (no silent pass).

Explicit non-goal (no overclaim): the server proves container/format/
decode/dims-caps on slot bytes. Full source frame-count proof is the
upstream encoder's job (mac ``package_encoder`` validates plan dims and
frame completeness locally before upload); this tier asserts duration +
frame-rate sanity on the synthetic source but never claims the server
re-proves frame counts — the server MUST NOT trust client frame claims.
"""

import hashlib
import shutil
import subprocess

import pytest

from app.services import web_packages as wp

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg + ffprobe required (backend image and dev Macs ship them)",
)

# Portrait 720p @ 60 fps, 2 s = 120 frames. Short side 720 fits BOTH caps
# (hq 1080, light 720), so the same synthetic file validates as hq AND as
# light with probed dims (720, 1280).
SRC_W, SRC_H, FPS, DURATION = 720, 1280, 60, 2


def _sha_size(path):
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _encode_mp4(path, *, faststart=True, bt709=True, profile="high"):
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi",
        "-i", f"testsrc2=size={SRC_W}x{SRC_H}:rate={FPS}:duration={DURATION}",
        "-pix_fmt", "yuv420p", "-c:v", "libx264",
        "-profile:v", profile, "-preset", "veryfast", "-crf", "28",
    ]
    if bt709:
        # VUI 1/1/1 = BT.709 primaries/transfer/matrix (no zscale needed).
        cmd += ["-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True, timeout=180)


def _extract_poster(src_mp4, poster_jpg, w=SRC_W, h=SRC_H):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(src_mp4), "-frames:v", "1",
         "-vf", f"scale={w}:{h}", "-q:v", "3", str(poster_jpg)],
        check=True, timeout=120,
    )


def test_real_synthetic_probes_expected_format(tmp_path):
    src = tmp_path / "src.mp4"
    _encode_mp4(src)
    data = wp._ffprobe_streams(src)
    video = next(s for s in data["streams"] if s.get("codec_type") == "video")
    assert video["codec_name"] == "h264"
    assert str(video["profile"]).lower() == "high"
    assert video["pix_fmt"] == "yuv420p"
    assert (video["width"], video["height"]) == (SRC_W, SRC_H)
    for key in ("color_transfer", "color_primaries", "color_space"):
        assert str(video.get(key) or "").lower() == "bt709", key
    assert "mp4" in str(data["format"].get("format_name") or "").lower()
    assert video.get("avg_frame_rate") == f"{FPS}/1"
    # Duration sanity on the synthetic source (server does NOT re-prove
    # frame counts — see module docstring).
    assert abs(float(data["format"]["duration"]) - DURATION) < 0.2
    assert wp._mp4_faststart_ok(src) is True
    assert wp._ffmpeg_decode_ok(src) is True


def test_real_hq_and_light_validate(tmp_path):
    src = tmp_path / "src.mp4"
    _encode_mp4(src)
    digest, size = _sha_size(src)
    for slot in ("hq", "light"):
        probed = wp.validate_slot_artifact(
            path=src, slot=slot, expected_sha256=digest, expected_size=size)
        assert (probed["width"], probed["height"]) == (SRC_W, SRC_H)
        assert probed["codec"] == "h264"


def test_real_poster_validates(tmp_path):
    src = tmp_path / "src.mp4"
    _encode_mp4(src)
    poster = tmp_path / "poster.jpg"
    _extract_poster(src, poster)
    assert poster.read_bytes()[:2] == b"\xff\xd8"
    digest, size = _sha_size(poster)
    probed = wp.validate_slot_artifact(
        path=poster, slot="poster", expected_sha256=digest, expected_size=size)
    assert (probed["width"], probed["height"]) == (SRC_W, SRC_H)


def test_real_truncated_rejected(tmp_path):
    src = tmp_path / "src.mp4"
    _encode_mp4(src)
    raw = src.read_bytes()
    trunc = tmp_path / "trunc.mp4"
    trunc.write_bytes(raw[: len(raw) * 3 // 4])
    digest, size = _sha_size(trunc)
    # SHA/size match the truncated bytes on purpose: only a REAL decode
    # probe can reject this (faststart moov + ffprobe streams still parse).
    with pytest.raises(ValueError, match="decode"):
        wp.validate_slot_artifact(
            path=trunc, slot="hq", expected_sha256=digest, expected_size=size)


def test_real_missing_bt709_tags_rejected(tmp_path):
    src = tmp_path / "notag.mp4"
    _encode_mp4(src, bt709=False)
    digest, size = _sha_size(src)
    with pytest.raises(ValueError, match="BT.709"):
        wp.validate_slot_artifact(
            path=src, slot="hq", expected_sha256=digest, expected_size=size)


def test_real_no_faststart_rejected(tmp_path):
    src = tmp_path / "nofs.mp4"
    _encode_mp4(src, faststart=False)
    assert wp._mp4_faststart_ok(src) is not True
    digest, size = _sha_size(src)
    with pytest.raises(ValueError, match="faststart"):
        wp.validate_slot_artifact(
            path=src, slot="hq", expected_sha256=digest, expected_size=size)


def test_real_non_mp4_rejected(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not-a-video-at-all" * 256)
    digest, size = _sha_size(bad)
    with pytest.raises(ValueError):
        wp.validate_slot_artifact(
            path=bad, slot="hq", expected_sha256=digest, expected_size=size)


def test_real_baseline_profile_rejected(tmp_path):
    src = tmp_path / "baseline.mp4"
    _encode_mp4(src, profile="baseline")
    digest, size = _sha_size(src)
    with pytest.raises(ValueError, match="High"):
        wp.validate_slot_artifact(
            path=src, slot="hq", expected_sha256=digest, expected_size=size)
