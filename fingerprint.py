"""Landmark-based (Shazam-style) audio fingerprinting.

Each fingerprint is a dict mapping a local (freq1, freq2, delta_time) hash,
derived from a pair of nearby spectrogram peaks, to the list of times that
pairing occurs at. Because a hash only encodes a relationship between two
peaks close together in time, matching doesn't require the clip being
searched for to start at its own beginning or run to its own end -- a
handful of locally-matching hashes is enough, which is what makes this
approach tolerant of a clip being truncated or cut short.
"""

import subprocess

import numpy as np
from scipy import ndimage, signal

SAMPLE_RATE = 11025
WINDOW_SIZE = 4096
OVERLAP_RATIO = 0.5
HOP_SIZE = int(WINDOW_SIZE * (1 - OVERLAP_RATIO))

PEAK_NEIGHBORHOOD_SIZE = 20
PEAK_MARGIN_DB = 30  # peaks must be within this many dB of the loudest point
                      # in the same spectrogram -- relative, not absolute, so
                      # it doesn't depend on how the source audio was normalized

FAN_VALUE = 5  # how many following peaks each anchor peak pairs up with
MIN_TIME_DELTA_FRAMES = 1
MAX_TIME_DELTA_FRAMES = 200


def decode_to_mono_pcm(path):
    """Decode an audio file to mono float32 PCM at SAMPLE_RATE via ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def spectrogram_peaks(samples):
    """Return a time-sorted list of (time_frame, freq_bin) local peaks."""
    _, _, stft = signal.stft(samples, nperseg=WINDOW_SIZE, noverlap=WINDOW_SIZE - HOP_SIZE)
    log_magnitude = 20 * np.log10(np.abs(stft) + 1e-10)

    local_max = ndimage.maximum_filter(log_magnitude, size=PEAK_NEIGHBORHOOD_SIZE) == log_magnitude
    is_peak = local_max & (log_magnitude > log_magnitude.max() - PEAK_MARGIN_DB)

    freq_bins, time_frames = np.nonzero(is_peak)
    return sorted(zip(time_frames.tolist(), freq_bins.tolist()))


def hash_peaks(peaks):
    """Turn sorted (time_frame, freq_bin) peaks into landmark hashes."""
    hashes = {}
    for i, (t1, f1) in enumerate(peaks):
        for t2, f2 in peaks[i + 1:i + 1 + FAN_VALUE]:
            delta = t2 - t1
            if MIN_TIME_DELTA_FRAMES <= delta <= MAX_TIME_DELTA_FRAMES:
                hashes.setdefault((f1, f2, delta), []).append(t1)
    return hashes


def fingerprint(path):
    """Compute the landmark fingerprint for a local audio file."""
    samples = decode_to_mono_pcm(path)
    peaks = spectrogram_peaks(samples)
    return hash_peaks(peaks)


def frames_to_seconds(frames):
    return frames * HOP_SIZE / SAMPLE_RATE
