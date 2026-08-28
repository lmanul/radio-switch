import ctypes
import enum
import random
import threading
import tkinter as tk
from pathlib import Path

import numpy as np
import vlc

import fingerprint


class SourceType(enum.Enum):
    RADIO = "radio"
    MUSIC = "music"


class AudioSource:
    def __init__(self, name, source_type, url=None, timeout_seconds=0, dodges=None):
        self.name = name
        self.source_type = source_type
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.dodges = dodges if dodges is not None else []

# Shared across all radio streams.
COMMON_DODGES = [
    "tune_in_s_how_to_all_your_stations.mp3",
    "tune_in_s_how_to_intro.mp3",
    "tune_in_s_how_to_local_radio_stations.mp3",
    "tune_in_s_how_to_podcasts.mp3",
    "tune_in_s_how_to_sports.mp3",
]

SOURCES = [
    AudioSource("CNN", SourceType.RADIO, "https://tunein.cdnstream1.com/2868_96.aac/playlist.m3u8",
                dodges=COMMON_DODGES + ["cnn_tune_in_fill_music.mp3"]),
    AudioSource("MSNow", SourceType.RADIO, "https://tunein.cdnstream1.com/3511_96.aac/playlist.m3u8",
                dodges=COMMON_DODGES + ["msnow_tune_in_fill_music.mp3"]),
    AudioSource("BBC", SourceType.RADIO, "https://a.files.bbci.co.uk/ms6/live/3441A116-B12E-4D2F-ACA8-C1984642FA4B/audio/simulcast/hls/nonuk/audio_syndication_low_sbr_v1/cfs/bbc_world_service.m3u8",
                timeout_seconds=120),
    # AudioSource("Local Music", SourceType.MUSIC),
]

MUSIC_DIR = Path.home() / "sync" / "music" / "instru"
DODGES_DIR = Path(__file__).resolve().parent / "dodges"

DODGE_CHECK_INTERVAL_MS = 3000
DODGE_BUFFER_SECONDS = 8
DODGE_MIN_MATCH_VOTES = 10

root = None
current_stream_index = 0
timeout_timer = None
vlc_instance = vlc.Instance()
players = []
buttons = []
button_frame_bg = None
next_music_track = None
dodge_fingerprint_cache = {}  # filename -> fingerprint, since sources can share dodge clips
dodge_analysis_players = {}  # source index -> silent shadow MediaPlayer used only for matching
dodge_audio_buffers = {}  # source index -> {"chunks": [...], "lock": Lock()}
dodge_audio_callbacks = {}  # source index -> live ctypes callback (must be kept alive)

def update_volumes():
    for i, player in enumerate(players):
        player.audio_set_volume(100 if i == current_stream_index else 0)

def update_button_highlights():
    for i, button in enumerate(buttons):
        if i == current_stream_index:
            button.config(highlightthickness=4, highlightbackground="green", highlightcolor="green")
        else:
            button.config(highlightthickness=4, highlightbackground=button_frame_bg, highlightcolor=button_frame_bg)

def on_click(value):
    global current_stream_index
    global timeout_timer
    current_stream_index = value
    update_volumes()
    update_button_highlights()
    source = SOURCES[current_stream_index]

    if timeout_timer is not None:
        root.after_cancel(timeout_timer)
    if source.timeout_seconds > 0:
        print(f"Scheduling time out in {source.timeout_seconds} seconds")
        timeout_timer = root.after(source.timeout_seconds * 1000, on_space, None)
    else:
        print("Clearing time out")
        timeout_timer = None

def on_space(event):
    on_click((current_stream_index + 1) % len(SOURCES))

def on_close(root):
    for player in players:
        player.audio_set_volume(100)
        player.stop()
    # The shadow players use ctypes audio callbacks; if their decode threads are
    # still running when the interpreter starts shutting down, they can call back
    # into now-torn-down Python state and crash the process. Stop them explicitly.
    for player in dodge_analysis_players.values():
        player.stop()
    root.destroy()

def pick_random_music_track():
    return random.choice(list(MUSIC_DIR.glob("**/*.mp3")))

def play_next_music_track(player):
    global next_music_track
    track = next_music_track
    next_music_track = pick_random_music_track()
    player.set_media(vlc_instance.media_new(str(track)))
    player.play()
    # play() resets the audio output volume, so reassert whether this player
    # should actually be audible right now.
    update_volumes()

def on_music_track_end(event, player):
    # libvlc forbids calling back into the player from this event thread, so hand
    # the transition off to a plain thread instead of doing it here directly.
    threading.Thread(target=play_next_music_track, args=(player,), daemon=True).start()

def get_dodge_fingerprint(filename):
    if filename not in dodge_fingerprint_cache:
        dodge_fingerprint_cache[filename] = fingerprint.fingerprint(DODGES_DIR / filename)
    return dodge_fingerprint_cache[filename]

def load_dodge_fingerprints():
    for source in SOURCES:
        source.dodge_fingerprints = [get_dodge_fingerprint(name) for name in source.dodges]

def make_dodge_audio_callback(buffer_state):
    max_samples = DODGE_BUFFER_SECONDS * fingerprint.SAMPLE_RATE

    def play(opaque, samples, count, pts):
        chunk = np.frombuffer(ctypes.string_at(samples, count * 2), dtype=np.int16)
        with buffer_state["lock"]:
            chunks = buffer_state["chunks"]
            chunks.append(chunk)
            total = sum(len(c) for c in chunks)
            while total > max_samples and len(chunks) > 1:
                total -= len(chunks.pop(0))

    return vlc.cb.AudioPlayCb(play)

def create_dodge_analysis_player(source, source_index):
    # A second, independent player for the same stream, decoding in parallel to
    # the audible one. Its audio callbacks replace normal output entirely (so it
    # never makes sound), and just feed a rolling buffer used for dodge matching.
    # This doubles bandwidth for this stream, but libvlc has no way to tap an
    # existing player's audio without taking over its output, so keeping the
    # audible player untouched is simplest.
    player = vlc_instance.media_player_new(source.url)
    buffer_state = {"chunks": [], "lock": threading.Lock()}
    dodge_audio_buffers[source_index] = buffer_state
    callback = make_dodge_audio_callback(buffer_state)
    dodge_audio_callbacks[source_index] = callback
    player.audio_set_callbacks(callback, None, None, None, None, None)
    player.audio_set_format("S16N", fingerprint.SAMPLE_RATE, 1)
    player.play()
    dodge_analysis_players[source_index] = player

def get_recent_dodge_audio(source_index):
    buffer_state = dodge_audio_buffers.get(source_index)
    if buffer_state is None:
        return None
    with buffer_state["lock"]:
        if not buffer_state["chunks"]:
            return None
        samples = np.concatenate(buffer_state["chunks"])
    return samples.astype(np.float32) / 32768.0

def check_for_dodge(root):
    source = SOURCES[current_stream_index]
    if source.dodge_fingerprints:
        samples = get_recent_dodge_audio(current_stream_index)
        if samples is not None and len(samples) >= fingerprint.WINDOW_SIZE:
            snippet_hashes = fingerprint.hash_peaks(fingerprint.spectrogram_peaks(samples))
            for reference_hashes in source.dodge_fingerprints:
                if fingerprint.matches(snippet_hashes, reference_hashes, DODGE_MIN_MATCH_VOTES):
                    on_click((current_stream_index + 1) % len(SOURCES))
                    break
    root.after(DODGE_CHECK_INTERVAL_MS, lambda: check_for_dodge(root))

def init():
    global next_music_track
    load_dodge_fingerprints()
    for index, source in enumerate(SOURCES):
        if source.source_type == SourceType.MUSIC:
            player = vlc_instance.media_player_new()
            player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, on_music_track_end, player)
            next_music_track = pick_random_music_track()
            play_next_music_track(player)
        else:
            player = vlc_instance.media_player_new(source.url)
            player.play()
            if source.dodges:
                create_dodge_analysis_player(source, index)
        players.append(player)
    update_volumes()
    update_button_highlights()

def main():
    global button_frame_bg
    global root

    root = tk.Tk()
    root.title("Radio Switch")
    root.geometry("300x150")

    button_frame = tk.Frame(root)
    button_frame.pack(fill=tk.X, padx=10, pady=20)
    button_frame_bg = button_frame.cget("bg")

    for value in range(len(SOURCES)):
        button = tk.Button(button_frame, text=SOURCES[value].name, command=lambda v=value: on_click(v), takefocus=0)
        button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, ipady=10)
        buttons.append(button)

    root.bind("<space>", on_space)
    root.focus_set()
    root.protocol("WM_DELETE_WINDOW", lambda: on_close(root))

    init()
    root.after(DODGE_CHECK_INTERVAL_MS, lambda: check_for_dodge(root))

    root.mainloop()

if __name__ == "__main__":
    main()
