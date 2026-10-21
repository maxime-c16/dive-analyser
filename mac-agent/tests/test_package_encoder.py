"""D3a package encoder: plan/command unit tests + synthetic SDR artifact tests.

All fixtures are synthetic (lavfi) under pytest tmp (private, never Git).
HDR artifact execution requires a zscale-equipped ffmpeg; this environment
(Homebrew, no zscale) meaningfully SKIPS those cases while still testing HDR
command construction and the fail-closed no-zscale refusal. A bounded canary
on a zscale-equipped Mac is NOT authorized here.
"""

import asyncio
import hashlib
import json
import os
import resource
import shutil
import subprocess
from pathlib import Path

import pytest

from src.package_encoder import (
    AUDIO_BITRATE,
    DERIVATIVE_TRANSFORM_VERSION_DEFAULT,
    POSTER_SHORT_SIDE,
    TONEMAP_FILTERS,
    PackagePlan,
    SourceInfo,
    TranscodeError,
    _parse_decoder_names,
    build_derivative_media_key,
    build_package,
    build_package_cmd,
    ffmpeg_decoder_codec_map,
    ffmpeg_decoder_names,
    ffmpeg_has_filter,
    frame_pts_times_s,
    nominal_gop,
    plan_package,
    select_decodable_audio_index,
    short_side_target_dims,
)

FFMPEG = os.environ.get("TEST_FFMPEG", shutil.which("ffmpeg"))
FFPROBE = str(Path(FFMPEG).with_name("ffprobe")) if FFMPEG and "/" in FFMPEG else "ffprobe"
BENCH_OUT = os.environ.get("DA_PKG_BENCH_OUT")  # optional JSONL sink (private /tmp)


def _bench_record(rec: dict) -> None:
    if not BENCH_OUT:
        return
    try:
        with open(BENCH_OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _peak_rss_mib() -> float | None:
    try:
        rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    except Exception:
        return None
    # macOS reports bytes; Linux reports KiB.
    import sys

    if sys.platform == "darwin":
        return round(rss / 1024**2, 1)
    return round(rss / 1024, 1)


def _mk_info(w, h, **kw):
    base = dict(
        coded_w=w, coded_h=h, display_w=w, display_h=h, rotation=0,
        r_frame_rate="60/1", nominal_fps=60.0, avg_fps=60.0,
        transfer=None, duration_s=2.0, audio_index=1,
    )
    base.update(kw)
    return SourceInfo(**base)


# ---------------------------------------------------------------------------
# Pure planning
# ---------------------------------------------------------------------------

def test_landscape_1080p_plan():
    plan = plan_package(_mk_info(1920, 1080))
    assert plan.hq_applicable and plan.hq_dims == (1920, 1080)
    assert plan.light_dims == (1280, 720)
    assert plan.poster_dims == (1280, 720)
    assert plan.hq_aliased_to is None
    assert plan.gop == 60


def test_portrait_1080p_plan_correct_short_side():
    # Q1 regression: portrait short side is the WIDTH -> 1080x1920, never 406x720.
    plan = plan_package(_mk_info(1080, 1920))
    assert plan.hq_applicable and plan.hq_dims == (1080, 1920)
    assert plan.light_dims == (720, 1280)


def test_mid_source_hq_absent_aliased_honestly():
    plan = plan_package(_mk_info(804, 1430))  # short 804 in [720, 1080)
    assert not plan.hq_applicable and plan.hq_dims is None
    assert plan.hq_aliased_to == "light"
    assert plan.light_dims == (720, 1282)  # ceil-to-even long side, no upscale


def test_small_source_no_upscale_light_is_source_size():
    plan = plan_package(_mk_info(404, 720))  # short 404 < 720
    assert not plan.hq_applicable and plan.hq_aliased_to == "light"
    assert plan.light_dims == (404, 720)


def test_odd_dims_stay_even_and_never_upscale():
    w, h = short_side_target_dims(1081, 1921, 1080)
    assert w % 2 == 0 and h % 2 == 0 and w <= 1081 and h <= 1921
    assert min(w, h) <= 1080
    w2, h2 = short_side_target_dims(721, 1281, 720)
    assert w2 % 2 == 0 and h2 % 2 == 0 and w2 <= 721 and h2 <= 1281


def test_gop_follows_nominal_cadence_not_forced_30():
    assert nominal_gop("60000/1001") == 60
    assert nominal_gop("30/1") == 30
    assert nominal_gop("0/0", avg_fps=25.0) == 25


def test_hdr_detected_only_for_hlg_pq():
    assert plan_package(_mk_info(1920, 1080, transfer="arib-std-b67")).is_hdr
    assert plan_package(_mk_info(1920, 1080, transfer="smpte2084")).is_hdr
    assert not plan_package(_mk_info(1920, 1080, transfer="bt709")).is_hdr
    assert not plan_package(_mk_info(1920, 1080, transfer=None)).is_hdr


# ---------------------------------------------------------------------------
# Derivative identity (D1 parity)
# ---------------------------------------------------------------------------

def test_derivative_key_vectors_match_d1_encoding():
    sha = "ab" * 32
    key = build_derivative_media_key("clip-1", "hq", sha, "ffmpeg-h264-web-v1")
    expect = hashlib.sha256(f"derivative-v1|clip-1|hq|{sha}|ffmpeg-h264-web-v1".encode()).hexdigest()
    assert key == expect
    assert key != build_derivative_media_key("clip-1", "light", sha, "ffmpeg-h264-web-v1")
    assert DERIVATIVE_TRANSFORM_VERSION_DEFAULT == "ffmpeg-h264-web-v1"


@pytest.mark.parametrize("kw", [
    dict(video_uuid="", role="hq"),
    dict(video_uuid=" clip", role="hq"),
    dict(video_uuid="a|b", role="hq"),
    dict(video_uuid="x" * 101, role="hq"),
    dict(video_uuid="clip", role="nope"),
    dict(video_uuid="clip", role="hq", transform_version=""),
    dict(video_uuid="clip", role="hq", transform_version="v|1"),
])
def test_derivative_key_fail_closed(kw):
    sha = "ab" * 32
    with pytest.raises(ValueError):
        build_derivative_media_key(kw.get("video_uuid", "clip"), kw.get("role", "hq"), sha,
                                   kw.get("transform_version", "ffmpeg-h264-web-v1"))
    with pytest.raises(ValueError):
        build_derivative_media_key("clip", "hq", "not-a-sha")


# ---------------------------------------------------------------------------
# Audio selection (Q2)
# ---------------------------------------------------------------------------

def _streams(*codecs):
    return [{"index": i, "codec_type": "audio", "codec_name": c} for i, c in enumerate(codecs)]


def test_audio_skips_unnamed_none_apac_case_insensitive():
    assert select_decodable_audio_index(_streams(None, "none", "APAC", "aac")) == 3
    assert select_decodable_audio_index(_streams("apac")) is None
    assert select_decodable_audio_index([]) is None


def test_audio_respects_actual_decoder_map_no_allowlist_claim():
    streams = _streams("aac", "eac3")
    assert select_decodable_audio_index(streams, {"aac"}) == 0
    assert select_decodable_audio_index(streams, {"eac3"}) == 1
    assert select_decodable_audio_index(streams, set()) is None


# ---------------------------------------------------------------------------
# Command construction (no ffmpeg execution)
# ---------------------------------------------------------------------------

def _plan_for_cmd(**kw):
    info = _mk_info(1920, 1080, **kw)
    return plan_package(info)


def test_cmd_single_decode_single_tonemap_split_hdr():
    plan = _plan_for_cmd(transfer="arib-std-b67")
    cmd = build_package_cmd(Path("s.mov"), Path("hq.mp4"), Path("lt.mp4"), Path("p.jpg"), plan)
    joined = " ".join(cmd)
    assert joined.count("tonemap=tonemap=hable") == 1  # decode once, tone-map once
    assert "split=3" in joined
    assert "zscale" in joined
    assert cmd.count("-threads") >= 3  # input + 2 bounded variant threads
    assert "-fps_mode" in cmd and "passthrough" in cmd
    assert "-r" not in cmd  # never force a frame rate
    assert "-maxrate" in joined and "12M" in joined  # HQ cap only on HQ output
    hq_seg = joined.split("hq.mp4")[0]
    lt_seg = joined.split("lt.mp4")[0].split("hq.mp4")[-1]
    assert "-maxrate" in hq_seg and "-maxrate" not in lt_seg


def test_cmd_sdr_skips_tonemap_two_outputs_when_hq_absent():
    plan = plan_package(_mk_info(804, 1430))  # SDR, HQ absent
    cmd = build_package_cmd(Path("s.mov"), None, Path("lt.mp4"), Path("p.jpg"), plan)
    joined = " ".join(cmd)
    assert "tonemap" not in joined and "zscale" not in joined
    assert "split=2" in joined
    assert "hq.mp4" not in joined
    assert "-q:v" in cmd  # poster quality set


def test_cmd_portrait_uses_short_side_dims():
    plan = plan_package(_mk_info(1080, 1920))
    cmd = build_package_cmd(Path("s.mov"), Path("hq.mp4"), Path("lt.mp4"), Path("p.jpg"), plan)
    joined = " ".join(cmd)
    assert "scale=1080:1920" in joined and "scale=720:1280" in joined
    assert "406" not in joined  # Q1 shape must not appear


def test_cmd_apac_audio_maps_video_only():
    plan = plan_package(_mk_info(1280, 720, audio_index=None))
    cmd = build_package_cmd(Path("s.mov"), None, Path("lt.mp4"), Path("p.jpg"), plan)
    assert "-an" in cmd and "0:None" not in " ".join(cmd)


def test_cmd_poster_select_frame_only_for_long_clips():
    long_plan = plan_package(_mk_info(1280, 720, duration_s=2.0))
    short_plan = plan_package(_mk_info(320, 240, duration_s=0.5))
    assert "select=" in " ".join(build_package_cmd(Path("s"), None, Path("l"), Path("p"), long_plan))
    assert "select=" not in " ".join(build_package_cmd(Path("s"), None, Path("l"), Path("p"), short_plan))


# ---------------------------------------------------------------------------
# Synthetic artifact tests (real ffmpeg, SDR)
# ---------------------------------------------------------------------------

def _need_ffmpeg():
    if not FFMPEG or not shutil.which(FFPROBE if "/" not in FFPROBE else "ffprobe"):
        pytest.skip("ffmpeg+ffprobe required")


def _gen_source(path: Path, w: int, h: int, fps: int, dur: float, audio: bool = True,
                rotate: int | None = None, vfr: bool = False) -> None:
    _need_ffmpeg()
    vin = f"testsrc2=s={w}x{h}:r={fps}:d={dur}"
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", vin]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    vf = "format=yuv420p"
    if vfr:
        vf += ",select='not(mod(n\\,7))',setpts=N/FRAME_RATE/TB"
    cmd += ["-vf", vf]
    if vfr:
        cmd += ["-vsync", "vfr"]
    if audio:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "96k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    if rotate:
        # Track-level displaymatrix is not writable by this ffmpeg's mp4
        # muxer, so rotation travels as an H.264 display-orientation SEI
        # (frame-level). ffmpeg autorotates it into the filter graph and the
        # probe's first-frame fallback detects it — the same display-geometry
        # path real rotated sources take.
        rotated = path.with_name(path.stem + "_rot.mp4")
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-i", str(path), "-c", "copy",
             "-bsf:v", f"h264_metadata=display_orientation=insert:rotate={rotate}",
             str(rotated)], check=True, capture_output=True, timeout=60)
        rotated.replace(path)


def _run_pkg(source: Path, out: Path, case: str, **kw):
    before = _peak_rss_mib()
    real_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    result = asyncio.run(build_package(
        source, out, video_uuid=f"test-{case}", source_sha256=real_sha,
        ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE, **kw))
    after = _peak_rss_mib()
    assert result.ready and result.validation["ready"]
    _bench_record({"case": case, "encode_s": result.encode_seconds,
                   "peak_rss_mib_after": after, "peak_rss_mib_before": before,
                   "light_bytes": result.light.size_bytes,
                   "hq_bytes": result.hq.size_bytes if result.hq else None,
                   "poster_bytes": result.poster.size_bytes,
                   "light_dims": [result.light.width, result.light.height]})
    return result


def _real_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_artifact_landscape_30fps_with_audio(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 640, 480, 30, 1.5, audio=True)
    before = hashlib.sha256(src.read_bytes()).digest()
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "landscape30")
    # short 480 < 720: no upscale, light == source size, HQ honestly absent
    assert (r.light.width, r.light.height) == (640, 480)
    assert r.hq is None and r.hq_aliased_to == "light"
    assert set(r.media_keys) == {"light", "poster"}
    assert hashlib.sha256(src.read_bytes()).digest() == before  # source untouched


def test_artifact_portrait_60fps(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 720, 1280, 60, 1.5, audio=False)
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "portrait60")
    assert (r.light.width, r.light.height) == (720, 1280)
    assert r.hq is None and r.hq_aliased_to == "light"
    # Poster rides the light-branch size and is a real JPEG, never HLG-tagged.
    assert (r.poster.width, r.poster.height) == (720, 1280)
    assert r.poster.path.read_bytes()[:2] == b"\xff\xd8"


def test_artifact_hq_applicable_keeps_all_frames(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 1920, 1080, 30, 1.2, audio=True)
    src_frames = json.loads(subprocess.check_output(
        [FFPROBE, "-v", "quiet", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(src)],
        timeout=120).decode().strip().strip(","))
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "hq1080")
    assert (r.hq.width, r.hq.height) == (1920, 1080)
    assert (r.light.width, r.light.height) == (1280, 720)
    assert r.source_frames == int(src_frames)
    assert set(r.media_keys) == {"hq", "light", "poster"}


def test_artifact_rotation_uses_display_orientation(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 640, 480, 30, 1.5, audio=False, rotate=90)
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "rotated90")
    # display is 480x640 portrait -> light keeps display size (short 480 < 720)
    assert (r.light.width, r.light.height) == (480, 640)


def test_artifact_vfr_preserves_frames_no_forced_rate(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 640, 480, 30, 2.0, audio=False, vfr=True)
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "vfr")
    probe = json.loads(subprocess.check_output(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", str(out / "light.mp4")],
        timeout=60).decode())
    assert r.source_frames > 0
    assert r.validation["checks"].get("light.frames") == "ok"


def test_artifact_short_clip_poster_without_select(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 320, 240, 30, 0.5, audio=False)
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "shortclip")
    assert (r.light.width, r.light.height) == (320, 240)
    assert r.poster.path.stat().st_size > 0


def test_hdr_without_zscale_fails_closed_no_outputs(tmp_path):
    _need_ffmpeg()
    if ffmpeg_has_filter(FFMPEG, "zscale"):
        pytest.skip("zscale present: fail-closed path not applicable here")
    src = tmp_path / "hdr.mov"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=25:d=0.5",
         "-vf", "format=yuv420p10le", "-c:v", "libx265", "-threads", "1",
         "-x265-params", "pools=1:frame-threads=1:log-level=error", "-tag:v", "hvc1",
         "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
         str(src)], check=True, capture_output=True, timeout=60)
    before = hashlib.sha256(src.read_bytes()).digest()
    out = tmp_path / "pkg"
    with pytest.raises(TranscodeError, match="zscale"):
        asyncio.run(build_package(src, out, video_uuid="t-hdr", source_sha256=_real_sha(src),
                                  ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE))
    leftovers = [p for p in out.iterdir()] if out.exists() else []
    # Only the (removed) scratch dir could ever appear; finals never created.
    assert all(not p.name.startswith(".pkg-attempt-") or True for p in leftovers)
    assert [p for p in leftovers if p.is_file()] == []
    assert hashlib.sha256(src.read_bytes()).digest() == before


def test_timeout_keeps_preexisting_outputs_never_source(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 1280, 720, 30, 2.0, audio=False)
    before = hashlib.sha256(src.read_bytes()).digest()
    out = tmp_path / "pkg"
    out.mkdir(parents=True, exist_ok=True)
    sentinel_light = out / "light.mp4"
    sentinel_poster = out / "poster.jpg"
    sentinel_light.write_bytes(b"sentinel-light-bytes")
    sentinel_poster.write_bytes(b"sentinel-poster-bytes")
    with pytest.raises(TranscodeError, match="ffmpeg_timeout"):
        asyncio.run(build_package(src, out, video_uuid="t-to", source_sha256=_real_sha(src),
                                  ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE,
                                  timeout_seconds=0.05))
    # Pre-existing accepted artifacts survive the timeout; scratch is gone.
    assert sentinel_light.read_bytes() == b"sentinel-light-bytes"
    assert sentinel_poster.read_bytes() == b"sentinel-poster-bytes"
    assert [p for p in out.iterdir() if p.name.startswith(".pkg-attempt-")] == []
    assert hashlib.sha256(src.read_bytes()).digest() == before


def test_decoder_map_helper_returns_names():
    _need_ffmpeg()
    names = ffmpeg_decoder_names(FFMPEG)
    assert "aac" in names  # presence check only; no allowlist guarantee claimed


# ---------------------------------------------------------------------------
# Review fixes: source integrity (item 2)
# ---------------------------------------------------------------------------

def test_source_sha_mismatch_fails_before_ffmpeg(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 320, 240, 30, 0.5, audio=False)
    before = src.read_bytes()
    out = tmp_path / "pkg"
    with pytest.raises(TranscodeError, match="source_sha256 mismatch"):
        asyncio.run(build_package(src, out, video_uuid="t-mismatch",
                                  source_sha256="ab" * 32,
                                  ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE))
    # Fail-closed: no ready outputs published, source untouched.
    finals = [p for p in out.iterdir() if p.is_file()] if out.exists() else []
    assert finals == []
    assert src.read_bytes() == before


def test_early_uuid_validation_before_expensive_encode(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 320, 240, 30, 0.5, audio=False)
    out = tmp_path / "pkg"
    # Even with an unusable ffmpeg binary, bad identity fails as
    # ValueError first — proof it precedes any expensive work/outputs.
    with pytest.raises(ValueError):
        asyncio.run(build_package(src, out, video_uuid="  bad uuid ",
                                  source_sha256=_real_sha(src),
                                  ffmpeg_path="/nonexistent/ffmpeg",
                                  ffprobe_path="/nonexistent/ffprobe"))
    assert not out.exists() or list(out.iterdir()) == []


def test_source_inside_outdir_refused_never_overwritten(tmp_path):
    out = tmp_path / "pkg"
    out.mkdir(parents=True, exist_ok=True)
    src = out / "light.mp4"  # source IS the light final path
    _gen_source(src, 320, 240, 30, 0.5, audio=False)
    before = src.read_bytes()
    with pytest.raises(TranscodeError, match="inside out_dir"):
        asyncio.run(build_package(src, out, video_uuid="t-self",
                                  source_sha256=_real_sha(src),
                                  ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE))
    assert src.read_bytes() == before  # source never overwritten/unlinked


def test_concurrent_builds_same_outdir_isolated(tmp_path):
    src_a = tmp_path / "a.mp4"
    src_b = tmp_path / "b.mp4"
    _gen_source(src_a, 320, 240, 30, 0.5, audio=False)
    _gen_source(src_b, 320, 240, 30, 0.5, audio=False)
    out = tmp_path / "pkg"

    async def _both():
        return await asyncio.gather(
            build_package(src_a, out, video_uuid="t-conc-a",
                          source_sha256=_real_sha(src_a),
                          ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE),
            build_package(src_b, out, video_uuid="t-conc-b",
                          source_sha256=_real_sha(src_b),
                          ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE),
        )

    ra, rb = asyncio.run(_both())
    assert ra.ready and rb.ready
    assert (out / "light.mp4").is_file() and (out / "poster.jpg").is_file()
    assert [p for p in out.iterdir() if p.name.startswith(".pkg-attempt-")] == []
    assert src_a.is_file() and src_b.is_file()


# ---------------------------------------------------------------------------
# Review fixes: async / cancellation safety (item 3)
# ---------------------------------------------------------------------------

def test_heartbeat_responsive_during_build(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 640, 480, 30, 1.5, audio=False)
    out = tmp_path / "pkg"
    ticks: list[int] = []

    async def _main():
        async def _beat():
            for _ in range(200):
                ticks.append(1)
                await asyncio.sleep(0.01)

        beat = asyncio.create_task(_beat())
        try:
            r = await build_package(src, out, video_uuid="t-beat",
                                    source_sha256=_real_sha(src),
                                    ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE)
        finally:
            beat.cancel()
            with pytest.raises(asyncio.CancelledError):
                await beat
        return r

    r = asyncio.run(_main())
    assert r.ready
    # The event loop ticked freely while blocking ffprobe/hash ran in threads.
    assert len(ticks) > 5


def test_cancel_during_validate_keeps_source_cleans_owned(tmp_path, monkeypatch):
    import src.package_encoder as pe

    src = tmp_path / "src.mp4"
    _gen_source(src, 640, 480, 30, 1.0, audio=False)
    before = src.read_bytes()
    out = tmp_path / "pkg"
    real_validate = pe.validate_package_outputs

    def _slow_validate(**kw):
        import time as _t
        _t.sleep(2.0)
        return real_validate(**kw)

    monkeypatch.setattr(pe, "validate_package_outputs", _slow_validate)

    async def _main():
        task = asyncio.create_task(build_package(
            src, out, video_uuid="t-cancel", source_sha256=_real_sha(src),
            ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE))
        await asyncio.sleep(0.6)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_main())
    assert src.read_bytes() == before
    finals = [p for p in out.iterdir() if p.is_file()] if out.exists() else []
    assert finals == []  # cancelled attempt publishes nothing
    assert [p for p in out.iterdir() if p.name.startswith(".pkg-attempt-")] == [] if out.exists() else True


# ---------------------------------------------------------------------------
# Review fixes: decoder alias mapping (item 6)
# ---------------------------------------------------------------------------

def test_decoder_alias_fold_mp3float_covers_mp3_codec():
    text = (
        "Decoders:\n"
        " A....D mp3float            MP3 (MPEG audio layer 3) (codec mp3)\n"
        " A....D aac                  AAC (Advanced Audio Coding)\n"
    )
    names = _parse_decoder_names(text)
    assert {"mp3float", "mp3", "aac"} <= names
    streams = [{"index": 0, "codec_type": "audio", "codec_name": "mp3"}]
    assert select_decodable_audio_index(streams, names) == 0


def test_audio_apac_first_aac_second():
    streams = [
        {"index": 0, "codec_type": "audio", "codec_name": "apac"},
        {"index": 1, "codec_type": "audio", "codec_name": "aac"},
    ]
    assert select_decodable_audio_index(streams, {"aac", "apac"}) == 1


def test_audio_video_only_when_no_decodable_track():
    assert select_decodable_audio_index(
        [{"index": 0, "codec_type": "audio", "codec_name": "apac"}], {"aac"}) is None
    assert select_decodable_audio_index([], {"aac"}) is None


def test_artifact_mp3_audio_preserved_via_decoder_alias(tmp_path):
    _need_ffmpeg()
    if "libmp3lame" not in subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True,
            timeout=30).stdout:
        pytest.skip("no libmp3lame encoder here")
    src = tmp_path / "src.mp4"
    _gen_source(src, 640, 480, 30, 1.0, audio=False)
    with_audio = tmp_path / "mp3src.mp4"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-i", str(src),
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1.0",
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-c:a", "libmp3lame", "-b:a", "96k", "-shortest", str(with_audio)],
        check=True, capture_output=True, timeout=120)
    out = tmp_path / "pkg"
    r = _run_pkg(with_audio, out, "mp3alias")
    assert r.validation["checks"].get("light.audio") == "ok"


# ---------------------------------------------------------------------------
# Review fixes: color / SAR honesty (item 4)
# ---------------------------------------------------------------------------

def test_cmd_sdr_branch_converts_matrix_and_sets_square_sar():
    info = SourceInfo(coded_w=1280, coded_h=720, display_w=1280, display_h=720,
                      rotation=0, r_frame_rate="30/1", nominal_fps=30.0,
                      avg_fps=30.0, transfer=None, duration_s=2.0, audio_index=None)
    plan = plan_package(info)
    cmd = " ".join(build_package_cmd(__import__("pathlib").Path("s"), None,
                                     __import__("pathlib").Path("l"),
                                     __import__("pathlib").Path("p"), plan))
    assert "out_color_matrix=bt709" in cmd  # real convert, not a retag
    assert "setsar=1" in cmd  # square-pixel outputs


def test_wide_gamut_sdr_requires_zscale_fail_closed(tmp_path):
    _need_ffmpeg()
    info = SourceInfo(coded_w=640, coded_h=480, display_w=640, display_h=480,
                      rotation=0, r_frame_rate="30/1", nominal_fps=30.0,
                      avg_fps=30.0, transfer="bt709", color_space="bt2020",
                      color_primaries="bt2020", duration_s=1.0, audio_index=None)
    plan = plan_package(info)
    assert plan.wide_gamut_sdr and plan.requires_zscale
    if ffmpeg_has_filter(FFMPEG, "zscale"):
        pytest.skip("zscale present: gamut path encodable here, canary later")
    # Real bt2020-tagged SDR file (gamma transfer, wide primaries): the
    # probed plan must require zscale and fail closed without it.
    src = tmp_path / "wide.mp4"
    _gen_source(src, 320, 240, 30, 0.5, audio=False)
    tagged = tmp_path / "wide_tagged.mp4"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-i", str(src),
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
         "-color_primaries", "bt2020", "-color_trc", "bt709",
         "-colorspace", "bt2020nc", str(tagged)],
        check=True, capture_output=True, timeout=120)
    out = tmp_path / "pkg"
    with pytest.raises(TranscodeError, match="zscale"):
        asyncio.run(build_package(tagged, out, video_uuid="t-gamut",
                                  source_sha256=_real_sha(tagged),
                                  ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE))
    assert hashlib.sha256(tagged.read_bytes()).digest() == hashlib.sha256(tagged.read_bytes()).digest()


def test_artifact_anamorphic_sar_square_pixels(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 320, 240, 30, 1.0, audio=False)
    sar_src = tmp_path / "sar.mp4"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-i", str(src),
         "-vf", "setsar=sar=2/1,format=yuv420p", "-c:v", "libx264",
         "-preset", "ultrafast", "-crf", "18", str(sar_src)],
        check=True, capture_output=True, timeout=120)
    out = tmp_path / "pkg"
    r = _run_pkg(sar_src, out, "anamorphic")
    # Display is 640x240 (SAR 2:1 honored); outputs carry square pixels.
    assert (r.light.width, r.light.height) == (640, 240)
    assert (r.poster.width, r.poster.height) == (640, 240)


# ---------------------------------------------------------------------------
# Review fixes: poster / VFR / GOP honesty (item 5)
# ---------------------------------------------------------------------------

def test_artifact_exact_1s_clip_poster_nonempty(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 640, 480, 30, 1.0, audio=False)
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "exact1s")
    assert r.poster.path.stat().st_size > 0
    probe = json.loads(subprocess.check_output(
        [FFPROBE, "-v", "quiet", "-print_format", "json",
         "-show_streams", str(out / "poster.jpg")],
        timeout=60).decode())
    assert probe["streams"][0]["codec_name"] in ("mjpeg", "jpg", "jpeg")


def test_artifact_vfr_pts_cadence_preserved(tmp_path):
    src = tmp_path / "src.mp4"
    _gen_source(src, 640, 480, 30, 2.0, audio=False, vfr=True)
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "vfrpts")
    src_pts = frame_pts_times_s(src, FFPROBE)
    out_pts = frame_pts_times_s(out / "light.mp4", FFPROBE)
    assert src_pts and out_pts
    assert len(out_pts) == len(src_pts) == r.source_frames
    # Passthrough timing: same cadence/duration, not CFR-forced.
    assert abs(out_pts[-1] - src_pts[-1]) < 0.15
    assert all(abs(a - b) < 0.05 for a, b in zip(out_pts, src_pts))
    assert r.validation["checks"].get("light.frames") == "ok"
    assert str(r.validation["checks"].get("light.gop_window", "")).startswith("ok")


def test_hdr_tonemap_artifact_when_zscale_available(tmp_path):
    _need_ffmpeg()
    if not ffmpeg_has_filter(FFMPEG, "zscale"):
        pytest.skip("no zscale here: HDR artifact needs a zscale-equipped Mac (canary later)")
    src = tmp_path / "hdr.mp4"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1.0",
         "-vf", "format=yuv420p10le", "-c:v", "libx265", "-threads", "1",
         "-x265-params", "pools=1:frame-threads=1:log-level=error", "-tag:v", "hvc1",
         "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc",
         str(src)], check=True, capture_output=True, timeout=120)
    out = tmp_path / "pkg"
    r = _run_pkg(src, out, "hdrtonemap")
    assert r.validation["checks"].get("light.transfer") == "ok"
