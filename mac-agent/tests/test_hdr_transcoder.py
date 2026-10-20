"""Real generated media: no private clips or remote storage required."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from src.transcoder import Transcoder


@pytest.mark.parametrize('transfer', [None, 'smpte2084', 'arib-std-b67'])
@pytest.mark.parametrize('rendition,height', [('proxy_360p', 360), ('proxy_720p', 720)])
def test_proxy_converts_hdr_and_preserves_source(tmp_path, transfer, rendition, height):
    ffmpeg = os.environ.get('TEST_FFMPEG', shutil.which('ffmpeg'))
    if not ffmpeg:
        pytest.skip('ffmpeg required')
    ffprobe = str(Path(ffmpeg).with_name('ffprobe'))
    if transfer and 'zscale' not in subprocess.check_output([ffmpeg, '-hide_banner', '-filters'], stderr=subprocess.DEVNULL).decode():
        pytest.skip('HDR conversion requires an ffmpeg build with zscale')
    source = tmp_path / 'source.mov'
    colors = ['-color_primaries', 'bt2020', '-color_trc', transfer, '-colorspace', 'bt2020nc'] if transfer else []
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=gray:s=64x64:r=25:d=0.2',
                    '-vf', 'format=yuv420p10le', '-c:v', 'libx265', '-threads', '1',
                    '-x265-params', 'pools=1:frame-threads=1:log-level=error', '-tag:v', 'hvc1',
                    *colors, str(source)], check=True, capture_output=True, timeout=30)
    before = hashlib.sha256(source.read_bytes()).digest()
    transcoder = Transcoder(str(tmp_path), ffmpeg)
    artifact = asyncio.run(transcoder.build(source, 'synthetic', rendition))
    streams = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(artifact.path)]))['streams']
    video = next(s for s in streams if s['codec_type'] == 'video')
    assert video['codec_name'] == 'h264'
    assert video['profile'] == 'Main'
    assert video['pix_fmt'] == 'yuv420p'
    assert video['height'] == height
    if transfer:
        assert video['color_transfer'] == video['color_primaries'] == video['color_space'] == 'bt709'
    data = artifact.path.read_bytes()
    assert data.index(b'moov') < data.index(b'mdat')
    # Decode actual pixels. Relabeling the HDR source alone must differ from
    # the tone-mapped output, even when both carry the same SDR output tags.
    if transfer:
        def luma(path, filters):
            raw = subprocess.check_output([ffmpeg, '-v', 'error', '-i', str(path), '-vf', filters,
                                           '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
            return sum(raw) / len(raw)
        mapped = luma(artifact.path, 'scale=16:16')
        relabeled = luma(source, 'scale=16:16,format=yuv420p')
        assert abs(mapped - relabeled) > 5
    assert hashlib.sha256(source.read_bytes()).digest() == before
    artifact.cleanup()


@pytest.mark.parametrize('stdout', ['not json', '{}', '{"streams": [{"codec_type": "audio"}]}'])
def test_unknown_video_metadata_fails_before_encoding(tmp_path, monkeypatch, stdout):
    from types import SimpleNamespace
    from src.transcoder import TranscodeError
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=stdout))
    transcoder = Transcoder(str(tmp_path))
    with pytest.raises(TranscodeError, match='metadata'):
        asyncio.run(transcoder.build(tmp_path / 'source.mov', 'synthetic', 'proxy_720p'))
