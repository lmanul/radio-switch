import tkinter as tk

class Radio:
    def __init__(self, name, url):
        self.name = name
        self.url = url

RADIOS = [
    Radio("CNN", "https://tunein.cdnstream1.com/2868_96.aac/playlist.m3u8"),
    Radio("MSNow", "https://tunein.cdnstream1.com/3511_96.aac/playlist.m3u8"),
    Radio("BBC", "http://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_low/ak/bbc_world_service.m3u8"),
]

def on_click(value):
    picked_radio = RADIOS[value]
    label.config(text=f"Playing {picked_radio.name}")

def init():
    pass

root = tk.Tk()
root.title("Radio Switch")
root.geometry("300x150")

label = tk.Label(root, text="Hello, Tkinter!")
label.pack(pady=20)

button_frame = tk.Frame(root)
button_frame.pack()

for value in range(len(RADIOS)):
    tk.Button(button_frame, text=RADIOS[value].name, command=lambda v=value: on_click(v)).pack(side=tk.LEFT, padx=5)

root.mainloop()