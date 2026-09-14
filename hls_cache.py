"""Caches a live HLS audio stream's segments on disk (typically a RAM disk),
so several players can read the same cached copy instead of each fetching the
stream over the network independently.
"""

import collections
import re
import shutil
import threading
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

POLL_INTERVAL_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 10
MIN_BUFFERED_SEGMENTS = 3  # segments to have on disk before playback can start
RETENTION_WINDOWS = 3  # how many fetched playlist windows' worth of segments to
                        # keep on disk before evicting, so a lagging reader never
                        # hits a file that's already been removed


def slugify(name):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name.lower())


class HlsCacheProxy:
    """Polls a live HLS stream and mirrors its segments into a local directory,
    rewriting the playlist to point at the local copies. `local_playlist_path`
    can then be handed to any number of players in place of the remote URL.
    """

    def __init__(self, name, master_url, cache_root):
        self.name = name
        self.master_url = master_url
        self.cache_dir = cache_root / slugify(name)
        self.local_playlist_path = self.cache_dir / "stream.m3u8"
        self.ready = threading.Event()

        self._stop_event = threading.Event()
        self._thread = None
        self._session = requests.Session()
        self._downloaded_names = set()
        self._recent_windows = collections.deque()

    def start(self):
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        self.cache_dir.mkdir(parents=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _resolve_media_playlist_url(self):
        # These master playlists have a single #EXT-X-STREAM-INF entry pointing at
        # the real live media playlist, whose URL carries a session ID that keeps
        # the same live window going across repeated fetches. Resolve it once and
        # keep polling that URL rather than the master.
        response = self._session.get(self.master_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        for line in response.text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return urljoin(self.master_url, line)
        return self.master_url  # already a media playlist, not a master

    def _download_segment(self, uri):
        filename = Path(urlparse(uri).path).name
        if filename not in self._downloaded_names:
            response = self._session.get(uri, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            dest = self.cache_dir / filename
            tmp_path = dest.with_name(dest.name + ".part")
            tmp_path.write_bytes(response.content)
            tmp_path.rename(dest)  # atomic, so the local playlist never points at a partial file
            self._downloaded_names.add(filename)
        return filename

    def _write_local_playlist(self, header_lines, segment_lines):
        tmp_path = self.local_playlist_path.with_name(self.local_playlist_path.name + ".part")
        tmp_path.write_text("\n".join(header_lines + segment_lines) + "\n")
        tmp_path.rename(self.local_playlist_path)

    def _evict_stale_segments(self):
        keep = set()
        for window in self._recent_windows:
            keep |= window
        for path in self.cache_dir.iterdir():
            if path.suffix == ".part" or path == self.local_playlist_path:
                continue
            if path.name not in keep:
                path.unlink(missing_ok=True)

    def _process_playlist(self, playlist_text, base_url):
        header_lines = []
        segments = []  # (extinf_line_or_None, absolute_uri)
        pending_extinf = None
        for line in playlist_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF"):
                pending_extinf = line
            elif line.startswith("#"):
                if pending_extinf is None:
                    header_lines.append(line)
            else:
                segments.append((pending_extinf, urljoin(base_url, line)))
                pending_extinf = None

        segment_lines = []
        window_filenames = set()
        for extinf_line, uri in segments:
            filename = self._download_segment(uri)
            window_filenames.add(filename)
            if extinf_line is not None:
                segment_lines.append(extinf_line)
            segment_lines.append(filename)

        self._recent_windows.append(window_filenames)
        while len(self._recent_windows) > RETENTION_WINDOWS:
            self._recent_windows.popleft()
        self._evict_stale_segments()

        self._write_local_playlist(header_lines, segment_lines)

        if len(window_filenames) >= MIN_BUFFERED_SEGMENTS:
            self.ready.set()

    def _run(self):
        media_playlist_url = None
        while not self._stop_event.is_set():
            try:
                if media_playlist_url is None:
                    media_playlist_url = self._resolve_media_playlist_url()
                response = self._session.get(media_playlist_url, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                self._process_playlist(response.text, media_playlist_url)
            except requests.RequestException as error:
                print(f"[{self.name}] HLS cache fetch failed, will retry: {error}")
                media_playlist_url = None  # the session id may have expired; re-resolve next time
            self._stop_event.wait(POLL_INTERVAL_SECONDS)
