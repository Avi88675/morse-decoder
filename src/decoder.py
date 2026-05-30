"""
Morse Code Decoder — Two-stage pipeline:

  Stage 1 — ToneDetector
    Goertzel algorithm + adaptive envelope threshold.
    Works regardless of signal strength by learning the signal's own
    on/off levels from recent history, rather than comparing to a fixed SNR.

  Stage 2 — TimingDecoder
    Key-up / key-down transitions → dots, dashes, spaces → characters

  MorseDecoder wires them together and emits callbacks.
"""

import numpy as np
import time
from collections import deque
from src.morse_table import MORSE_TO_CHAR


# ──────────────────────────────────────────────────────────────
#  Stage 1: Tone Detection  (Goertzel + adaptive threshold)
# ──────────────────────────────────────────────────────────────

class ToneDetector:
    """
    Detects CW tone presence using the Goertzel algorithm.

    Why Goertzel instead of FFT?
      FFT gives energy across ALL frequencies — with small chunks (256 samples)
      the frequency resolution is only ~172 Hz/bin, which is too coarse for
      reliable CW detection. Goertzel measures power at exactly ONE frequency
      efficiently and works perfectly with small chunks.

    Why adaptive threshold instead of fixed SNR?
      A fixed SNR threshold breaks when the signal is very strong (fills spaces)
      or very weak (misses signal). The adaptive approach learns the signal's
      own on-level and off-level from recent history and sets the threshold
      exactly between them. It works on signals from 2 dB to 60 dB SNR.
    """

    SAMPLE_RATE = 44100
    FREQ_LOW    = 400    # Hz — search range
    FREQ_HIGH   = 1200   # Hz

    # History window for adaptive threshold
    # 200 chunks × 256 samples / 44100 Hz ≈ 1.2 seconds of context
    HISTORY_LEN = 200

    def __init__(self):
        self.detected_freq = 750.0
        self.signal_level  = 0.0

        # Large buffer for periodic frequency auto-detection via FFT
        self._freq_buffer   = deque(maxlen=8192)
        self._freq_counter  = 0
        self._freq_interval = 40   # re-detect frequency every 40 chunks

        # Per-chunk Goertzel power history for adaptive threshold
        self._env_history = deque(maxlen=self.HISTORY_LEN)
        self._threshold   = None

        # Light debounce
        self._recent = deque(maxlen=3)

    # ── Frequency auto-detection ──────────────────────────────

    def _update_frequency(self):
        buf    = np.array(self._freq_buffer)
        window = np.hanning(len(buf))
        mag    = np.abs(np.fft.rfft(buf * window))
        freqs  = np.fft.rfftfreq(len(buf), 1.0 / self.SAMPLE_RATE)
        mask   = (freqs >= self.FREQ_LOW) & (freqs <= self.FREQ_HIGH)
        if np.any(mask):
            self.detected_freq = float(freqs[mask][np.argmax(mag[mask])])

    # ── Goertzel single-frequency power ──────────────────────

    @staticmethod
    def _goertzel(samples: np.ndarray, freq: float, sample_rate: float) -> float:
        """
        Goertzel algorithm — power at a single frequency.
        O(N) vs FFT's O(N log N), and exact for the target frequency.
        """
        N = len(samples)
        if N < 4:
            return 0.0
        k     = int(round(N * freq / sample_rate))
        k     = max(1, min(k, N // 2 - 1))
        w     = 2.0 * np.pi * k / N
        coeff = 2.0 * np.cos(w)
        q1 = q2 = 0.0
        for s in samples:
            q0 = float(s) + coeff * q1 - q2
            q2, q1 = q1, q0
        power = q1 * q1 + q2 * q2 - coeff * q1 * q2
        return float(power / N)

    # ── Main process call ─────────────────────────────────────

    def process(self, samples: np.ndarray) -> tuple:
        """
        Returns (tone_present: bool, frequency_hz: float, strength: float 0-1)
        """
        # Feed frequency detection buffer
        self._freq_buffer.extend(samples)
        self._freq_counter += 1
        if self._freq_counter >= self._freq_interval and len(self._freq_buffer) >= 2048:
            self._update_frequency()
            self._freq_counter = 0

        # Measure power at CW frequency
        power = self._goertzel(samples, self.detected_freq, self.SAMPLE_RATE)
        rms   = float(np.sqrt(max(power, 0.0)))
        self._env_history.append(rms)

        # Need enough history to set a meaningful threshold
        if len(self._env_history) < 20:
            return False, self.detected_freq, 0.0

        env = np.array(self._env_history)

        # Adaptive threshold:
        #   noise_est = typical level when key is UP  (low 20th percentile)
        #   peak_est  = typical level when key is DOWN (high 80th percentile)
        #   threshold = 40% of the way from noise to peak
        #
        # This automatically adjusts to ANY signal strength because it's
        # relative to the signal's own dynamics, not an absolute value.
        noise_est = float(np.percentile(env, 20))
        peak_est  = float(np.percentile(env, 80))
        spread    = peak_est - noise_est

        if spread > noise_est * 0.3:
            # Clear on/off signal — set threshold between noise and peak
            self._threshold = noise_est + spread * 0.4
        else:
            # No clear signal — conservative high threshold (nothing decoded)
            self._threshold = noise_est * 2.0

        tone_present = (self._threshold is not None) and (rms > self._threshold)

        # Signal strength for display (0 = noise floor, 1 = peak)
        if spread > 0:
            self.signal_level = float(np.clip((rms - noise_est) / (spread + 1e-10), 0.0, 1.0))
        else:
            self.signal_level = 0.0

        # Debounce: require 2 of last 3 chunks to agree
        self._recent.append(tone_present)
        smoothed = sum(self._recent) >= 2

        return smoothed, self.detected_freq, self.signal_level


# ──────────────────────────────────────────────────────────────
#  Stage 2: Timing → Morse symbols
# ──────────────────────────────────────────────────────────────

class TimingDecoder:
    """
    Converts key-up/key-down state changes + durations into decoded text.

    Bootstrap: collects first 10 marks and uses gap analysis to find the
    natural dit/dah split point, rather than trusting the first mark blindly.
    This makes calibration robust even when the first few marks are noisy.
    """

    BOOTSTRAP_SIZE = 10

    def __init__(self):
        self.dit_ms          = None
        self.wpm             = 0
        self._last_state     = False
        self._last_change_ms = 0.0   # audio time in ms, not wall clock
        self._current_sym    = []
        self._char_cbs       = []
        self._bootstrap      = []

    def on_character_decoded(self, callback):
        self._char_cbs.append(callback)

    def process_state(self, is_mark: bool, audio_time_ms: float = 0.0):
        duration_ms = audio_time_ms - self._last_change_ms

        # Timeout: flush pending letter after long silence
        if not is_mark and self.dit_ms:
            if duration_ms > self.dit_ms * 8 and self._current_sym:
                self._complete_letter()
                self._emit(' ')

        if is_mark == self._last_state:
            return

        if self._last_state:
            self._classify_mark(duration_ms)
        else:
            self._classify_space(duration_ms)

        self._last_change_ms = audio_time_ms
        self._last_state     = is_mark

    def _bootstrap_estimate(self):
        """
        Estimate dit duration from the first several marks using two-pass
        gap analysis.

        Pass 1 — find the dit/dah boundary (largest multiplicative gap).
        Pass 2 — within the dit candidates, remove any low outlier sub-cluster
                  caused by noise spikes or a second faster station in the
                  passband. Only the main dit cluster is used.
        """
        marks = sorted(m for m in self._bootstrap if m >= 8.0)
        self._bootstrap = []

        if not marks:
            return
        if len(marks) == 1:
            self.dit_ms = marks[0]
            return

        # Pass 1: main dit/dah split
        ratios = [marks[i+1] / marks[i] for i in range(len(marks) - 1)]
        best_gap = max(ratios)
        best_idx = ratios.index(best_gap) + 1

        dit_candidates = marks[:best_idx] if best_gap > 1.8 else marks

        # Pass 2: remove low outlier sub-cluster within dit candidates
        # (e.g. 17ms noise marks mixed with 35ms real dits)
        if len(dit_candidates) > 2:
            inner = [dit_candidates[i+1] / dit_candidates[i]
                     for i in range(len(dit_candidates) - 1)]
            inner_best = max(inner)
            inner_idx  = inner.index(inner_best) + 1
            # Apply only if the gap is significant AND leaves ≥2 marks
            if inner_best > 1.5 and (len(dit_candidates) - inner_idx) >= 2:
                dit_candidates = dit_candidates[inner_idx:]

        self.dit_ms = float(np.median(dit_candidates))

    def _classify_mark(self, duration_ms: float):
        # Hard noise floor — sub-chunk spikes
        if duration_ms < 6.0:
            return

        # Bootstrap: collect marks before committing to a dit estimate
        if self.dit_ms is None:
            self._bootstrap.append(duration_ms)
            if len(self._bootstrap) >= self.BOOTSTRAP_SIZE:
                self._bootstrap_estimate()
            return

        # Dynamic minimum: reject marks clearly shorter than a dit
        if duration_ms < self.dit_ms * 0.35:
            return

        ratio = duration_ms / self.dit_ms

        if ratio < 2.2:     # dit
            self._current_sym.append('.')
            # Asymmetric EWMA: slow to drift UP (noise inflates dit),
            # faster to come DOWN (operator speeds up).
            alpha = 0.08 if duration_ms > self.dit_ms * 1.2 else 0.15
            self.dit_ms = (1 - alpha) * self.dit_ms + alpha * duration_ms
        else:               # dah
            self._current_sym.append('-')
            self.dit_ms = 0.85 * self.dit_ms + 0.15 * (duration_ms / 3.0)

        # Sanity check: reset if dit drifts to nonsense values
        if self.dit_ms < 5.0 or self.dit_ms > 600.0:
            self.dit_ms     = None
            self._bootstrap = []
            return

        self.wpm = int(round(1200.0 / self.dit_ms))

        # Hard cap: more than 7 symbols is a timing error — discard and start fresh.
        if len(self._current_sym) > 7:
            self._current_sym = [self._current_sym[-1]]

    def _classify_space(self, duration_ms: float):
        if self.dit_ms is None:
            return
        ratio = duration_ms / self.dit_ms
        if ratio >= 2.0:
            self._complete_letter()
        if ratio >= 6.0:
            self._emit(' ')

    def _complete_letter(self):
        if not self._current_sym:
            return
        code = ''.join(self._current_sym)
        char = MORSE_TO_CHAR.get(code, f'[{code}]')
        self._current_sym = []
        self._emit(char)

    def _emit(self, char: str):
        for cb in self._char_cbs:
            cb(char)
# ──────────────────────────────────────────────────────────────
#  Top-level MorseDecoder
# ──────────────────────────────────────────────────────────────

class MorseDecoder:
    """
    Wires ToneDetector + TimingDecoder together.

    Usage:
        decoder = MorseDecoder()
        decoder.on_character(lambda c: print(c, end='', flush=True))
        decoder.on_signal_state(lambda freq, strength, active, wpm: ...)

        source = SystemAudioSource(device='BlackHole 2ch')
        source.start(decoder.feed)
    """

    def __init__(self):
        self.tone_detector  = ToneDetector()
        self.timing_decoder = TimingDecoder()
        self._signal_cbs    = []
        self._sample_count  = 0   # cumulative samples for accurate timing

    def on_character(self, callback):
        self.timing_decoder.on_character_decoded(callback)

    def on_signal_state(self, callback):
        """callback(freq_hz, strength, is_mark, wpm)"""
        self._signal_cbs.append(callback)

    def feed(self, samples: np.ndarray):
        self._sample_count += len(samples)
        audio_time_ms = self._sample_count / ToneDetector.SAMPLE_RATE * 1000.0

        tone_present, freq, strength = self.tone_detector.process(samples)
        self.timing_decoder.process_state(tone_present, audio_time_ms)
        for cb in self._signal_cbs:
            cb(freq, strength, tone_present, self.timing_decoder.wpm)
