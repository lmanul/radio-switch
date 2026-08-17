import enum
import random
import threading
import tkinter as tk
from pathlib import Path

import vlc


class SourceType(enum.Enum):
    RADIO = "radio"
    MUSIC = "music"


class AudioSource:
    def __init__(self, name, source_type, url=None):
        self.name = name
        self.source_type = source_type
        self.url = url

SOURCES = [
    AudioSource("CNN", SourceType.RADIO, "https://tunein.cdnstream1.com/2868_96.aac/playlist.m3u8"),
    AudioSource("MSNow", SourceType.RADIO, "https://tunein.cdnstream1.com/3511_96.aac/playlist.m3u8"),
    AudioSource("BBC", SourceType.RADIO, "https://a.files.bbci.co.uk/ms6/live/3441A116-B12E-4D2F-ACA8-C1984642FA4B/audio/simulcast/hls/nonuk/audio_syndication_low_sbr_v1/cfs/bbc_world_service.m3u8"),
    AudioSource("Local Music", SourceType.MUSIC),
]

MUSIC_DIR = Path.home() / "sync" / "music" / "instru"

current_stream_index = 0
vlc_instance = vlc.Instance()
players = []
buttons = []
button_frame_bg = None
next_music_track = None

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
    current_stream_index = value
    update_volumes()
    update_button_highlights()

def on_space(event):
    on_click((current_stream_index + 1) % len(SOURCES))

def on_close(root):
    for player in players:
        player.audio_set_volume(100)
    root.destroy()

def pick_random_music_track():
    return random.choice(list(MUSIC_DIR.glob("**/*.mp3")))

def play_next_music_track(player):
    global next_music_track
    track = next_music_track
    next_music_track = pick_random_music_track()
    player.set_media(vlc_instance.media_new(str(track)))
    player.play()

def on_music_track_end(event, player):
    # libvlc forbids calling back into the player from this event thread, so hand
    # the transition off to a plain thread instead of doing it here directly.
    threading.Thread(target=play_next_music_track, args=(player,), daemon=True).start()

def init():
    global next_music_track
    for source in SOURCES:
        if source.source_type == SourceType.MUSIC:
            player = vlc_instance.media_player_new()
            player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, on_music_track_end, player)
            next_music_track = pick_random_music_track()
            play_next_music_track(player)
        else:
            player = vlc_instance.media_player_new(source.url)
            player.play()
        players.append(player)
    update_volumes()
    update_button_highlights()

def main():
    global button_frame_bg

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

    root.mainloop()

if __name__ == "__main__":
    main()