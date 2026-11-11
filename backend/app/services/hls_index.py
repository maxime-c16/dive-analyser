"""Byte-range HLS over durable fragmented-MP4 packages (v4).

A v4 Light/HQ file is ``ftyp``, ``moov`` (the init segment), one global
``sidx`` per track, then ~1 s ``moof``/``mdat`` fragments. Its first few KB
describe every fragment, so a VOD media playlist can address the stored file
by byte range: no extra objects, no re-packaging, and the same file still
plays progressively.

This module only parses and renders. It never decides access: the playlist
routes authorize, resolve the current proof and sign before calling it.
Parsed indexes are keyed by the blob's SHA-256 (content addressed, so an
entry can never go stale) and kept in a bounded process-local cache.
"""

from __future__ import annotations

import math
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional

#: Bytes read from the start of a package on the first fetch. The init plus
#: both indexes of a 12 s clip take about 1.7 KB; long clips grow by 12 B
#: per fragment per track.
HEAD_FETCH_BYTES = 64 * 1024
#: Hard ceiling for the header region (a 2-hour 1 s-fragment file needs ~170 KB).
MAX_HEAD_BYTES = 1024 * 1024

_CACHE_MAX_ENTRIES = 4096
#: Retained-memory budget: segments across all cached indexes (~100 B each,
#: so ~25 MB). A 15 s clip has 15; a long one can have thousands.
_CACHE_MAX_SEGMENTS = 250_000
_cache: "OrderedDict[str, Optional[FragmentIndex]]" = OrderedDict()
_cached_segments = 0
# Per-blob [gate, callers] for first loads (single-flight); removed when the
# last caller leaves.
_inflight: dict = {}
_cache_lock = threading.Lock()


class IndexUnavailable(Exception):
    """The package header could not be read (provider failure)."""


@dataclass(frozen=True)
class Segment:
    offset: int
    length: int
    duration: float


@dataclass(frozen=True)
class FragmentIndex:
    init_length: int
    segments: tuple[Segment, ...]
    codecs: str
    width: Optional[int]
    height: Optional[int]

    @property
    def duration(self) -> float:
        return sum(segment.duration for segment in self.segments)

    @property
    def peak_bandwidth(self) -> int:
        """BANDWIDTH: the highest segment bitrate, as HLS requires."""
        return max(
            math.ceil(segment.length * 8 / segment.duration)
            for segment in self.segments
        )

    @property
    def average_bandwidth(self) -> int:
        return math.ceil(sum(s.length for s in self.segments) * 8 / self.duration)


# ---------------------------------------------------------------------------
# ISO BMFF parsing (pure)
# ---------------------------------------------------------------------------


class _NeedMore(Exception):
    def __init__(self, needed: int) -> None:
        super().__init__(needed)
        self.needed = needed


def _boxes(data: bytes, start: int, end: int):
    """Yield (type, payload_start, box_end) for the boxes in data[start:end]."""
    offset = start
    while offset + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            if offset + 16 > end:
                return
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = end - offset
        if size < header:
            raise ValueError("corrupt box size")
        yield kind, offset + header, offset + size
        offset += size


def _child(data: bytes, start: int, end: int, kind: bytes):
    for child_kind, payload, box_end in _boxes(data, start, min(end, len(data))):
        if child_kind == kind:
            return payload, box_end
    return None


def _path(data: bytes, start: int, end: int, *kinds: bytes):
    for kind in kinds:
        found = _child(data, start, end, kind)
        if found is None:
            return None
        start, end = found
    return start, end


def _avc_codec(data: bytes, entry_payload: int, entry_end: int) -> Optional[str]:
    # VisualSampleEntry: 78 bytes of fixed fields before child boxes.
    avcc = _child(data, entry_payload + 78, entry_end, b"avcC")
    if avcc is None or avcc[1] - avcc[0] < 4:
        return None
    profile, compat, level = data[avcc[0] + 1], data[avcc[0] + 2], data[avcc[0] + 3]
    return f"avc1.{profile:02X}{compat:02X}{level:02X}"


def _descriptor(data: bytes, offset: int, end: int):
    """(tag, payload_start, payload_end) of one MPEG-4 descriptor."""
    if offset + 2 > end:
        return None
    tag = data[offset]
    offset += 1
    length = 0
    for _ in range(4):
        byte = data[offset]
        offset += 1
        length = (length << 7) | (byte & 0x7F)
        if not byte & 0x80:
            break
    return tag, offset, min(offset + length, end)


def _aac_codec(data: bytes, entry_payload: int, entry_end: int) -> str:
    # AudioSampleEntry: 28 bytes of fixed fields before child boxes.
    esds = _child(data, entry_payload + 28, entry_end, b"esds")
    if esds is not None:
        try:
            es = _descriptor(data, esds[0] + 4, esds[1])
            if es and es[0] == 0x03:
                flags = data[es[1] + 2]
                cursor = es[1] + 3
                cursor += 2 if flags & 0x80 else 0
                cursor += 1 + data[cursor] if flags & 0x40 else 0
                cursor += 2 if flags & 0x20 else 0
                dc = _descriptor(data, cursor, es[2])
                if dc and dc[0] == 0x04 and data[dc[1]] == 0x40:
                    dsi = _descriptor(data, dc[1] + 13, dc[2])
                    if dsi and dsi[0] == 0x05 and dsi[2] > dsi[1]:
                        object_type = data[dsi[1]] >> 3
                        if object_type:
                            return f"mp4a.40.{object_type}"
        except IndexError:
            pass
    return "mp4a.40.2"


def _tracks(data: bytes, moov: tuple[int, int]):
    """Per track: (track_id, handler, codec, width, height)."""
    tracks = []
    for kind, payload, end in _boxes(data, moov[0], moov[1]):
        if kind != b"trak":
            continue
        tkhd = _child(data, payload, end, b"tkhd")
        hdlr = _path(data, payload, end, b"mdia", b"hdlr")
        stsd = _path(data, payload, end, b"mdia", b"minf", b"stbl", b"stsd")
        if tkhd is None or hdlr is None or stsd is None:
            continue
        version = data[tkhd[0]]
        track_id = struct.unpack_from(">I", data, tkhd[0] + (20 if version == 1 else 12))[0]
        dims_at = tkhd[1] - 8
        width = struct.unpack_from(">I", data, dims_at)[0] >> 16
        height = struct.unpack_from(">I", data, dims_at + 4)[0] >> 16
        handler = bytes(data[hdlr[0] + 8:hdlr[0] + 12])
        codec = None
        # stsd is a full box: version/flags + entry count, then entries.
        for entry_kind, entry_payload, entry_end in _boxes(data, stsd[0] + 8, stsd[1]):
            if entry_kind in (b"avc1", b"avc3"):
                codec = _avc_codec(data, entry_payload, entry_end)
            elif entry_kind == b"mp4a":
                codec = _aac_codec(data, entry_payload, entry_end)
            break
        tracks.append((track_id, handler, codec, width, height))
    return tracks


def _sidx(data: bytes, payload: int, box_end: int):
    version = data[payload]
    reference_id, timescale = struct.unpack_from(">II", data, payload + 4)
    cursor = payload + 12
    if version == 0:
        _earliest, first_offset = struct.unpack_from(">II", data, cursor)
        cursor += 8
    else:
        _earliest, first_offset = struct.unpack_from(">QQ", data, cursor)
        cursor += 16
    count = struct.unpack_from(">H", data, cursor + 2)[0]
    cursor += 4
    if cursor + 12 * count > box_end:
        raise ValueError("truncated sidx")
    references = []
    for _ in range(count):
        word, duration, _sap = struct.unpack_from(">III", data, cursor)
        cursor += 12
        if word >> 31:
            return None  # hierarchical index: not produced by the v4 recipe
        references.append((word & 0x7FFFFFFF, duration))
    return reference_id, timescale, box_end + first_offset, references


def parse_fragment_index(data: bytes, total_size: Optional[int] = None) -> Optional[FragmentIndex]:
    """Parse a package header. None when the file is not a usable fMP4.

    Raises _NeedMore when ``data`` stops before the header region ends.
    """
    moov = None
    sidx_boxes = []
    offset = 0
    while True:
        if offset + 16 > len(data):
            raise _NeedMore(offset + 64 * 1024)
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        if size < header:
            return None
        if kind in (b"moof", b"mdat"):
            break
        if offset + size > len(data):
            raise _NeedMore(offset + size + 64)
        if kind == b"moov":
            moov = (offset + header, offset + size)
        elif kind == b"sidx":
            sidx_boxes.append((offset + header, offset + size))
        offset += size
    if moov is None or not sidx_boxes or _child(data, moov[0], moov[1], b"mvex") is None:
        return None
    tracks = _tracks(data, moov)
    video = next((track for track in tracks if track[1] == b"vide" and track[2]), None)
    if video is None:
        return None
    indexes = [_sidx(data, payload, end) for payload, end in sidx_boxes]
    if any(index is None for index in indexes):
        return None
    chosen = next((index for index in indexes if index[0] == video[0]), indexes[0])
    _reference_id, timescale, first, references = chosen
    if not timescale or not references:
        return None
    segments = []
    position = first
    for length, duration in references:
        if length <= 0 or duration <= 0:
            return None
        segments.append(Segment(offset=position, length=length, duration=duration / timescale))
        position += length
    if total_size is not None and position > total_size:
        return None
    codecs = [video[2]] + [track[2] for track in tracks if track[1] == b"soun" and track[2]][:1]
    return FragmentIndex(
        init_length=moov[1],
        segments=tuple(segments),
        codecs=",".join(codecs),
        width=video[3] or None,
        height=video[4] or None,
    )


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------

RangeReader = Callable[[int], tuple[bytes, Optional[int]]]


def load_index(read_head: RangeReader) -> Optional[FragmentIndex]:
    """Read as much of the head as the boxes need (bounded) and parse it.

    ``read_head(n)`` returns the first n bytes and the object's total size.
    """
    want = HEAD_FETCH_BYTES
    while True:
        data, total = read_head(want)
        try:
            return parse_fragment_index(data, total)
        except _NeedMore as more:
            if total is not None and len(data) >= total:
                return None
            if more.needed > MAX_HEAD_BYTES or len(data) < want:
                return None
            want = max(more.needed, want * 2)
        except (ValueError, struct.error, IndexError):
            return None


def cached_index(blob_sha256: str, read_head: RangeReader) -> Optional[FragmentIndex]:
    """Index for one immutable blob; non-fragmented results are cached too.

    Single-flight per blob: concurrent first requests share one B2 read.
    Provider failures raise IndexUnavailable and are never cached.
    """
    global _cached_segments
    with _cache_lock:
        if blob_sha256 in _cache:
            _cache.move_to_end(blob_sha256)
            return _cache[blob_sha256]
        # [gate, callers]: the record lives until its last caller leaves, so a
        # failed load is retried by the queued callers one at a time, never
        # beside a fresh gate.
        entry = _inflight.setdefault(blob_sha256, [threading.Lock(), 0])
        entry[1] += 1
        gate = entry[0]
    try:
        with gate:
            with _cache_lock:
                if blob_sha256 in _cache:
                    _cache.move_to_end(blob_sha256)
                    return _cache[blob_sha256]
            index = load_index(read_head)
            size = len(index.segments) if index else 0
            if size > _CACHE_MAX_SEGMENTS:
                return index  # served, never retained
            with _cache_lock:
                previous = _cache.pop(blob_sha256, None)
                _cached_segments -= len(previous.segments) if previous else 0
                _cache[blob_sha256] = index
                _cached_segments += size
                while len(_cache) > _CACHE_MAX_ENTRIES or _cached_segments > _CACHE_MAX_SEGMENTS:
                    _key, evicted = _cache.popitem(last=False)
                    _cached_segments -= len(evicted.segments) if evicted else 0
            return index
    finally:
        with _cache_lock:
            entry[1] -= 1
            if entry[1] == 0 and _inflight.get(blob_sha256) is entry:
                del _inflight[blob_sha256]


def reset_cache() -> None:
    global _cached_segments
    with _cache_lock:
        _cache.clear()
        _inflight.clear()
        _cached_segments = 0


# ---------------------------------------------------------------------------
# Playlists
# ---------------------------------------------------------------------------

PLAYLIST_CONTENT_TYPE = "application/vnd.apple.mpegurl"


def _extinf(seconds: float) -> str:
    return f"{seconds:.5f}".rstrip("0").rstrip(".")


def media_playlist(index: FragmentIndex, url: str) -> str:
    """VOD playlist addressing one file by byte range."""
    if any(ch in url for ch in '"\r\n'):
        raise ValueError("unsafe playlist URI")
    target = max(1, math.ceil(max(segment.duration for segment in index.segments) - 1e-3))
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{target}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        f'#EXT-X-MAP:URI="{url}",BYTERANGE="{index.init_length}@0"',
    ]
    for segment in index.segments:
        lines.append(f"#EXTINF:{_extinf(segment.duration)},")
        lines.append(f"#EXT-X-BYTERANGE:{segment.length}@{segment.offset}")
        lines.append(url)
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def master_playlist(variants: list[tuple[FragmentIndex, str]]) -> str:
    """Variants in the order given: players start on the first one."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for index, uri in variants:
        attributes = [
            f"BANDWIDTH={index.peak_bandwidth}",
            f"AVERAGE-BANDWIDTH={index.average_bandwidth}",
            f'CODECS="{index.codecs}"',
        ]
        if index.width and index.height:
            attributes.append(f"RESOLUTION={index.width}x{index.height}")
        lines.append("#EXT-X-STREAM-INF:" + ",".join(attributes))
        lines.append(uri)
    return "\n".join(lines) + "\n"
