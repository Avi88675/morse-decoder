"""
Audio source abstraction layer.

This is the key architectural piece that lets us swap between:
  - System audio (mic or BlackHole virtual cable for WebSDR testing)
  - RTL-SDR hardware (when it arrives)
  - File playback (for testing with recorded audio)

The decoder never touches this directly — it just sees audio samples.
"""

import numpy as np
from abc import ABC, abstractmethod


class AudioSource(ABC):
    """Base class for all audio inputs."""

    SAMPLE_RATE = 44100   # Hz — standard audio sample rate
    CHUNK_SIZE  = 256    # Samples per callback (~46ms at 44100)

    @abstractmethod
    def start(self, callback):
        """
        Begin streaming audio.
        callback(samples: np.ndarray[float32]) is called for each chunk.
        """

    @abstractmethod
    def stop(self):
        """Stop streaming."""

    @abstractmethod
    def get_info(self) -> dict:
        """Return dict describing the source (for display/logging)."""


# ──────────────────────────────────────────────────────────────
#  System Audio (microphone, BlackHole, USB audio adapter, etc.)
# ──────────────────────────────────────────────────────────────

class SystemAudioSource(AudioSource):
    """
    Reads from any system audio input via sounddevice.

    For testing without SDR hardware:
      1. Install BlackHole: brew install --cask blackhole-2ch
      2. In Audio MIDI Setup, create a Multi-Output Device
         that includes both your speakers and BlackHole 2ch
      3. Open WebSDR in your browser, tune to a CW band
      4. Pass device='BlackHole 2ch' to this class
    """

    def __init__(self, device=None):
        """
        device: None = system default, or a device name/index.
        Run python main.py --list to see available devices.
        """
        self.device = device
        self._stream = None

    def start(self, callback):
        import sounddevice as sd

        def _sd_callback(indata, frames, time_info, status):
            # Convert stereo to mono if needed, ensure float32
            mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
            callback(mono.astype(np.float32))

        self._stream = sd.InputStream(
            device=self.device,
            samplerate=self.SAMPLE_RATE,
            blocksize=self.CHUNK_SIZE,
            channels=1,
            dtype='float32',
            callback=_sd_callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def get_info(self) -> dict:
        import sounddevice as sd
        try:
            if self.device is not None:
                info = sd.query_devices(self.device, 'input')
            else:
                info = sd.query_devices(sd.default.device[0])
            name = info['name']
        except Exception:
            name = str(self.device) if self.device else 'default'

        return {'type': 'system_audio', 'device': name, 'sample_rate': self.SAMPLE_RATE}

    @staticmethod
    def list_devices() -> list:
        """Return a list of available input devices."""
        import sounddevice as sd
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d['max_input_channels'] > 0:
                devices.append({'index': i, 'name': d['name']})
        return devices


# ──────────────────────────────────────────────────────────────
#  RTL-SDR  (for when hardware arrives)
# ──────────────────────────────────────────────────────────────

class SDRSource(AudioSource):
    """
    RTL-SDR V4 input using rtl_fm (installed by brew install librtlsdr).

    rtl_fm handles all the SDR → demodulated audio conversion for us.
    We just read its stdout as raw int16 PCM samples.

    Tip: good starting frequencies for CW
      7.050 MHz  — 40m, busy evenings
      14.025 MHz — 20m, busy daytimes
      10.116 MHz — 30m (CW only band)
    """

    SAMPLE_RATE = 12000   # rtl_fm outputs 12kHz for CW mode

    def __init__(self, frequency: float = 7.050e6, gain: str = 'auto'):
        self.frequency = frequency
        self.gain = gain
        self._process = None
        self._thread = None

    def start(self, callback):
        import subprocess
        import threading

        gain_arg = ['0'] if self.gain == 'auto' else [str(self.gain)]

        cmd = [
            'rtl_fm',
            '-f', str(int(self.frequency)),
            '-M', 'cw',         # CW demodulation mode
            '-s', '12000',      # 12kHz sample rate — lightweight
            '-g', *gain_arg,
            '-',
        ]

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        def _read_loop():
            BYTES_PER_CHUNK = self.CHUNK_SIZE * 2  # int16 = 2 bytes
            while self._process and self._process.poll() is None:
                raw = self._process.stdout.read(BYTES_PER_CHUNK)
                if raw:
                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                    samples /= 32768.0  # normalize to -1.0 … 1.0
                    callback(samples)

        self._thread = threading.Thread(target=_read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if self._process:
            self._process.terminate()
            self._process = None

    def get_info(self) -> dict:
        freq_mhz = self.frequency / 1e6
        return {
            'type': 'rtl_sdr',
            'frequency_mhz': round(freq_mhz, 4),
            'gain': self.gain,
            'sample_rate': self.SAMPLE_RATE,
        }


# ──────────────────────────────────────────────────────────────
#  File Source  (for running decoder against recorded audio)
# ──────────────────────────────────────────────────────────────

class FileAudioSource(AudioSource):
    """
    Replay a WAV file through the decoder.
    Great for regression testing — record a session, play it back.
    """

    def __init__(self, path: str):
        self.path = path
        self._thread = None
        self._running = False

    def start(self, callback):
        import threading
        import wave
        import time

        def _play():
            with wave.open(self.path, 'rb') as wf:
                sample_rate = wf.getframerate()
                while self._running:
                    raw = wf.readframes(self.CHUNK_SIZE)
                    if not raw:
                        break
                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                    samples /= 32768.0
                    callback(samples)
                    time.sleep(self.CHUNK_SIZE / sample_rate)

        self._running = True
        self._thread = threading.Thread(target=_play, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_info(self) -> dict:
        return {'type': 'file', 'path': self.path}
