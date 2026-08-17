import tkinter as tk

import vlc


class Radio:
    def __init__(self, name, url):
        self.name = name
        self.url = url

RADIOS = [
    Radio("CNN", "https://tunein.cdnstream1.com/2868_96.aac/playlist.m3u8"),
    Radio("MSNow", "https://tunein.cdnstream1.com/3511_96.aac/playlist.m3u8"),
    Radio("BBC", "https://a.files.bbci.co.uk/ms6/live/3441A116-B12E-4D2F-ACA8-C1984642FA4B/audio/simulcast/hls/nonuk/audio_syndication_low_sbr_v1/cfs/bbc_world_service.m3u8"),
]

current_stream_index = 0
vlc_instance = vlc.Instance()
players = []
buttons = []

def update_volumes():
    for i, player in enumerate(players):
        player.audio_set_volume(100 if i == current_stream_index else 0)

def update_button_highlights():
    for i, button in enumerate(buttons):
        if i == current_stream_index:
            button.config(highlightthickness=4, highlightbackground="green", highlightcolor="green")
        else:
            button.config(highlightthickness=0)

def on_click(value):
    global current_stream_index
    current_stream_index = value
    update_volumes()
    update_button_highlights()

def on_space(event):
    on_click((current_stream_index + 1) % len(RADIOS))

def init():
    for radio in RADIOS:
        player = vlc_instance.media_player_new(radio.url)
        players.append(player)
        player.play()
    update_volumes()
    update_button_highlights()

root = tk.Tk()
root.title("Radio Switch")
root.geometry("300x150")

button_frame = tk.Frame(root)
button_frame.pack(fill=tk.X, padx=10, pady=20)

for value in range(len(RADIOS)):
    button = tk.Button(button_frame, text=RADIOS[value].name, command=lambda v=value: on_click(v), takefocus=0)
    button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, ipady=10)
    buttons.append(button)

root.bind("<space>", on_space)
root.focus_set()

init()

root.mainloop()