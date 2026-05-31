"""
Callsign detector — scans decoded CW text for amateur radio callsigns,
looks up their country from the ITU prefix table, and emits events.

ITU callsign structure:
  [prefix: 1-2 alphanumeric, at least one letter] + [digit] + [suffix: 1-4 letters]

Examples: HG4A  9A1A  OK5D  TM1A  W4ABC  VE3XYZ  UX2HB  LY1M

Deduplication: same callsign isn't re-emitted within RESSPOT_SECS seconds,
but its contact count increments so the UI can show how active it is.
"""

import re
import time
from collections import deque


# ── ITU callsign regex ─────────────────────────────────────────
# Two forms:
#   [A-Z][A-Z0-9]?  + digit + [A-Z]{1,4}   (normal: G3, VE3, OK5, HG4, W4)
#   [0-9][A-Z]      + digit + [A-Z]{1,4}   (digit-first: 9A1, 4X4, 3B8)
CALLSIGN_RE = re.compile(
    r'(?<![A-Z0-9])'
    r'([A-Z][A-Z0-9]?[0-9][A-Z]{1,4}'
    r'|[0-9][A-Z][0-9][A-Z]{1,4})'
    r'(?![A-Z0-9])'
)

# Strings that match the regex but are NOT callsigns
_FALSE_POSITIVES = {
    'TEST', 'CONTEST', 'CQ', 'DE', 'TU', 'QSO', 'QRZ', 'QTH',
    'QRN', 'QRM', 'QSB', 'QRT', 'RST', 'NR', 'BK', 'SK', 'AR',
}

# Minimum callsign length to reduce false positives
_MIN_LEN = 3


# ── ITU Prefix → (country, flag emoji) ────────────────────────
# Longest prefix is tried first (2+ chars before 1 char).
# Covers the prefixes most commonly heard on 40m/20m CW.

_PREFIX_TABLE = {
    # ── Special / Numeric prefixes ─────────────────────────────
    '3A': ('Monaco', '🇲🇨'),
    '3B': ('Mauritius', '🇲🇺'),
    '3V': ('Tunisia', '🇹🇳'),
    '4J': ('Azerbaijan', '🇦🇿'), '4K': ('Azerbaijan', '🇦🇿'),
    '4L': ('Georgia', '🇬🇪'),
    '4O': ('Montenegro', '🇲🇪'),
    '4U': ('United Nations', '🇺🇳'),
    '4X': ('Israel', '🇮🇱'), '4Z': ('Israel', '🇮🇱'),
    '5B': ('Cyprus', '🇨🇾'),
    '5R': ('Madagascar', '🇲🇬'),
    '5Z': ('Kenya', '🇰🇪'),
    '6W': ('Senegal', '🇸🇳'),
    '6Y': ('Jamaica', '🇯🇲'),
    '7X': ('Algeria', '🇩🇿'),
    '8P': ('Barbados', '🇧🇧'),
    '9A': ('Croatia', '🇭🇷'),
    '9G': ('Ghana', '🇬🇭'),
    '9H': ('Malta', '🇲🇹'),
    '9J': ('Zambia', '🇿🇲'),
    '9K': ('Kuwait', '🇰🇼'),
    '9V': ('Singapore', '🇸🇬'),
    '9Y': ('Trinidad', '🇹🇹'),

    # ── Europe ─────────────────────────────────────────────────
    'CT': ('Portugal', '🇵🇹'),
    'CU': ('Azores', '🇵🇹'),
    'DK': ('Germany', '🇩🇪'), 'DL': ('Germany', '🇩🇪'),
    'DM': ('Germany', '🇩🇪'), 'DP': ('Germany', '🇩🇪'),
    'E7': ('Bosnia', '🇧🇦'),
    'EA': ('Spain', '🇪🇸'), 'EB': ('Spain', '🇪🇸'), 'EC': ('Spain', '🇪🇸'),
    'ED': ('Spain', '🇪🇸'), 'EE': ('Spain', '🇪🇸'), 'EF': ('Spain', '🇪🇸'),
    'EG': ('Spain', '🇪🇸'), 'EH': ('Spain', '🇪🇸'),
    'EI': ('Ireland', '🇮🇪'), 'EJ': ('Ireland', '🇮🇪'),
    'EK': ('Armenia', '🇦🇲'),
    'ER': ('Moldova', '🇲🇩'),
    'ES': ('Estonia', '🇪🇪'),
    'EU': ('Belarus', '🇧🇾'), 'EV': ('Belarus', '🇧🇾'), 'EW': ('Belarus', '🇧🇾'),
    'EX': ('Kyrgyzstan', '🇰🇬'),
    'EY': ('Tajikistan', '🇹🇯'),
    'EZ': ('Turkmenistan', '🇹🇲'),
    'F':  ('France', '🇫🇷'),
    'G':  ('England', '🏴󠁧󠁢󠁥󠁮󠁧󠁿'),
    'GD': ('Isle of Man', '🇮🇲'),
    'GI': ('N. Ireland', '🇬🇧'),
    'GJ': ('Jersey', '🇯🇪'),
    'GM': ('Scotland', '🏴󠁧󠁢󠁳󠁣󠁴󠁿'),
    'GU': ('Guernsey', '🇬🇬'),
    'GW': ('Wales', '🏴󠁧󠁢󠁷󠁬󠁳󠁿'),
    'HA': ('Hungary', '🇭🇺'), 'HG': ('Hungary', '🇭🇺'),
    'HB': ('Switzerland', '🇨🇭'),
    'HV': ('Vatican', '🇻🇦'),
    'I':  ('Italy', '🇮🇹'),
    'IK': ('Italy', '🇮🇹'), 'IU': ('Italy', '🇮🇹'),
    'IW': ('Italy', '🇮🇹'), 'IZ': ('Italy', '🇮🇹'),
    'IS': ('Sardinia', '🇮🇹'), 'IT': ('Sicily', '🇮🇹'),
    'LA': ('Norway', '🇳🇴'), 'LB': ('Norway', '🇳🇴'), 'LC': ('Norway', '🇳🇴'),
    'LD': ('Norway', '🇳🇴'), 'LE': ('Norway', '🇳🇴'), 'LF': ('Norway', '🇳🇴'),
    'LG': ('Norway', '🇳🇴'),
    'LY': ('Lithuania', '🇱🇹'),
    'LZ': ('Bulgaria', '🇧🇬'),
    'OA': ('Peru', '🇵🇪'),
    'OE': ('Austria', '🇦🇹'),
    'OF': ('Finland', '🇫🇮'), 'OG': ('Finland', '🇫🇮'), 'OH': ('Finland', '🇫🇮'),
    'OI': ('Finland', '🇫🇮'), 'OJ': ('Finland', '🇫🇮'),
    'OK': ('Czech Rep.', '🇨🇿'), 'OL': ('Czech Rep.', '🇨🇿'),
    'OM': ('Slovakia', '🇸🇰'),
    'ON': ('Belgium', '🇧🇪'), 'OO': ('Belgium', '🇧🇪'), 'OP': ('Belgium', '🇧🇪'),
    'OQ': ('Belgium', '🇧🇪'), 'OR': ('Belgium', '🇧🇪'), 'OS': ('Belgium', '🇧🇪'),
    'OT': ('Belgium', '🇧🇪'),
    'OX': ('Greenland', '🇬🇱'),
    'OY': ('Faroe Is.', '🇫🇴'),
    'OZ': ('Denmark', '🇩🇰'),
    'PA': ('Netherlands', '🇳🇱'), 'PB': ('Netherlands', '🇳🇱'),
    'PC': ('Netherlands', '🇳🇱'), 'PD': ('Netherlands', '🇳🇱'),
    'PE': ('Netherlands', '🇳🇱'), 'PF': ('Netherlands', '🇳🇱'),
    'PG': ('Netherlands', '🇳🇱'), 'PH': ('Netherlands', '🇳🇱'),
    'RA': ('Russia', '🇷🇺'), 'RB': ('Russia', '🇷🇺'), 'RC': ('Russia', '🇷🇺'),
    'RD': ('Russia', '🇷🇺'), 'RE': ('Russia', '🇷🇺'), 'RF': ('Russia', '🇷🇺'),
    'RG': ('Russia', '🇷🇺'), 'RH': ('Russia', '🇷🇺'), 'RI': ('Russia', '🇷🇺'),
    'RJ': ('Russia', '🇷🇺'), 'RK': ('Russia', '🇷🇺'), 'RL': ('Russia', '🇷🇺'),
    'RM': ('Russia', '🇷🇺'), 'RN': ('Russia', '🇷🇺'), 'RO': ('Russia', '🇷🇺'),
    'RP': ('Russia', '🇷🇺'), 'RQ': ('Russia', '🇷🇺'), 'RR': ('Russia', '🇷🇺'),
    'RS': ('Russia', '🇷🇺'), 'RT': ('Russia', '🇷🇺'), 'RU': ('Russia', '🇷🇺'),
    'RV': ('Russia', '🇷🇺'), 'RW': ('Russia', '🇷🇺'), 'RX': ('Russia', '🇷🇺'),
    'RY': ('Russia', '🇷🇺'), 'RZ': ('Russia', '🇷🇺'),
    'S5': ('Slovenia', '🇸🇮'),
    'SA': ('Sweden', '🇸🇪'), 'SB': ('Sweden', '🇸🇪'), 'SC': ('Sweden', '🇸🇪'),
    'SD': ('Sweden', '🇸🇪'), 'SE': ('Sweden', '🇸🇪'), 'SF': ('Sweden', '🇸🇪'),
    'SG': ('Sweden', '🇸🇪'), 'SH': ('Sweden', '🇸🇪'), 'SI': ('Sweden', '🇸🇪'),
    'SJ': ('Sweden', '🇸🇪'), 'SK': ('Sweden', '🇸🇪'), 'SL': ('Sweden', '🇸🇪'),
    'SM': ('Sweden', '🇸🇪'),
    'SN': ('Poland', '🇵🇱'), 'SO': ('Poland', '🇵🇱'), 'SP': ('Poland', '🇵🇱'),
    'SQ': ('Poland', '🇵🇱'), 'SR': ('Poland', '🇵🇱'),
    'SV': ('Greece', '🇬🇷'), 'SW': ('Greece', '🇬🇷'), 'SX': ('Greece', '🇬🇷'),
    'SY': ('Greece', '🇬🇷'), 'SZ': ('Greece', '🇬🇷'),
    'T7': ('San Marino', '🇸🇲'),
    'TA': ('Turkey', '🇹🇷'), 'TB': ('Turkey', '🇹🇷'), 'TC': ('Turkey', '🇹🇷'),
    'TF': ('Iceland', '🇮🇸'),
    'TK': ('Corsica', '🇫🇷'),
    'TM': ('France', '🇫🇷'),
    'UA': ('Russia', '🇷🇺'), 'UB': ('Russia', '🇷🇺'), 'UC': ('Russia', '🇷🇺'),
    'UD': ('Russia', '🇷🇺'), 'UE': ('Russia', '🇷🇺'), 'UF': ('Russia', '🇷🇺'),
    'UG': ('Russia', '🇷🇺'), 'UH': ('Russia', '🇷🇺'), 'UI': ('Russia', '🇷🇺'),
    'UN': ('Kazakhstan', '🇰🇿'), 'UO': ('Kazakhstan', '🇰🇿'),
    'UP': ('Kazakhstan', '🇰🇿'), 'UQ': ('Kazakhstan', '🇰🇿'),
    'UR': ('Ukraine', '🇺🇦'), 'US': ('Ukraine', '🇺🇦'), 'UT': ('Ukraine', '🇺🇦'),
    'UU': ('Ukraine', '🇺🇦'), 'UV': ('Ukraine', '🇺🇦'), 'UW': ('Ukraine', '🇺🇦'),
    'UX': ('Ukraine', '🇺🇦'), 'UY': ('Ukraine', '🇺🇦'), 'UZ': ('Ukraine', '🇺🇦'),
    'YL': ('Latvia', '🇱🇻'),
    'YO': ('Romania', '🇷🇴'), 'YP': ('Romania', '🇷🇴'),
    'YQ': ('Romania', '🇷🇴'), 'YR': ('Romania', '🇷🇴'),
    'YT': ('Serbia', '🇷🇸'), 'YU': ('Serbia', '🇷🇸'),
    'Z3': ('N. Macedonia', '🇲🇰'),
    'Z6': ('Kosovo', '🇽🇰'),
    'ZA': ('Albania', '🇦🇱'),
    'ZB': ('Gibraltar', '🇬🇮'),

    # ── North America ──────────────────────────────────────────
    'K':  ('USA', '🇺🇸'),
    'N':  ('USA', '🇺🇸'),
    'W':  ('USA', '🇺🇸'),
    'AA': ('USA', '🇺🇸'), 'AB': ('USA', '🇺🇸'), 'AC': ('USA', '🇺🇸'),
    'AD': ('USA', '🇺🇸'), 'AE': ('USA', '🇺🇸'), 'AF': ('USA', '🇺🇸'),
    'AG': ('USA', '🇺🇸'), 'AI': ('USA', '🇺🇸'), 'AJ': ('USA', '🇺🇸'),
    'AK': ('USA', '🇺🇸'), 'AL': ('USA', '🇺🇸'),
    'VA': ('Canada', '🇨🇦'), 'VB': ('Canada', '🇨🇦'), 'VC': ('Canada', '🇨🇦'),
    'VD': ('Canada', '🇨🇦'), 'VE': ('Canada', '🇨🇦'), 'VF': ('Canada', '🇨🇦'),
    'VG': ('Canada', '🇨🇦'), 'VY': ('Canada', '🇨🇦'),
    'XE': ('Mexico', '🇲🇽'),

    # ── Rest of world ──────────────────────────────────────────
    'BY': ('China', '🇨🇳'), 'BA': ('China', '🇨🇳'), 'BD': ('China', '🇨🇳'),
    'BI': ('China', '🇨🇳'), 'BJ': ('China', '🇨🇳'), 'BL': ('China', '🇨🇳'),
    'BM': ('China', '🇨🇳'), 'BN': ('China', '🇨🇳'), 'BR': ('China', '🇨🇳'),
    'BS': ('China', '🇨🇳'), 'BT': ('China', '🇨🇳'), 'BV': ('Taiwan', '🇹🇼'),
    'HZ': ('Saudi Arabia', '🇸🇦'),
    'JA': ('Japan', '🇯🇵'), 'JE': ('Japan', '🇯🇵'), 'JF': ('Japan', '🇯🇵'),
    'JG': ('Japan', '🇯🇵'), 'JH': ('Japan', '🇯🇵'), 'JI': ('Japan', '🇯🇵'),
    'JK': ('Japan', '🇯🇵'), 'JL': ('Japan', '🇯🇵'), 'JM': ('Japan', '🇯🇵'),
    'JN': ('Japan', '🇯🇵'), 'JO': ('Japan', '🇯🇵'), 'JP': ('Japan', '🇯🇵'),
    'JQ': ('Japan', '🇯🇵'), 'JR': ('Japan', '🇯🇵'), 'JS': ('Japan', '🇯🇵'),
    'HL': ('South Korea', '🇰🇷'), 'DS': ('South Korea', '🇰🇷'),
    'PP': ('Brazil', '🇧🇷'), 'PY': ('Brazil', '🇧🇷'),
    'LU': ('Argentina', '🇦🇷'),
    'VK': ('Australia', '🇦🇺'),
    'ZL': ('New Zealand', '🇳🇿'),
    'ZS': ('South Africa', '🇿🇦'),
    'VU': ('India', '🇮🇳'),
    'EP': ('Iran', '🇮🇷'),
    'TI': ('Costa Rica', '🇨🇷'),
    'YB': ('Indonesia', '🇮🇩'),
    'YV': ('Venezuela', '🇻🇪'),
    'ZP': ('Paraguay', '🇵🇾'),
}

# Pre-sort by prefix length descending so longest match wins
_SORTED_PREFIXES = sorted(_PREFIX_TABLE.keys(), key=len, reverse=True)


def lookup_prefix(callsign: str) -> tuple:
    """Return (country, flag) for a callsign. Falls back to ('Unknown', '🌍')."""
    cs = callsign.upper()
    for prefix in _SORTED_PREFIXES:
        if cs.startswith(prefix):
            return _PREFIX_TABLE[prefix]
    return ('Unknown', '🌍')


# ── Detector class ─────────────────────────────────────────────

class CallsignDetector:
    """
    Feed decoded characters one at a time. On each word boundary
    (space received), scans recent text for callsigns and emits events.

    Deduplication: same callsign is not re-emitted within RESSPOT_SECS,
    but its contact count increments so the UI can show activity level.
    """

    RESSPOT_SECS = 60   # seconds before re-emitting a known callsign
    BUFFER_LEN   = 80   # rolling character window to scan

    def __init__(self):
        self._buffer   = deque(maxlen=self.BUFFER_LEN)
        self._spotted  = {}   # callsign → {first_seen, last_seen, count, country, flag}
        self._callbacks = []
        self.frequency_mhz = 0.0

    def on_callsign(self, callback):
        """Register callback(entry: dict) called when a callsign is spotted."""
        self._callbacks.append(callback)

    def feed(self, char: str):
        """Feed one decoded character. Scans on word boundaries."""
        self._buffer.append(char)
        if char in (' ', '\n'):
            self._scan()

    def get_all(self) -> list:
        """Return all spotted callsigns sorted by last seen (newest first)."""
        return sorted(
            self._spotted.values(),
            key=lambda e: e['last_seen'],
            reverse=True,
        )

    # ── Internal ───────────────────────────────────────────────

    def _scan(self):
        text = ''.join(self._buffer)
        for m in CALLSIGN_RE.finditer(text):
            cs = m.group(1)
            if self._valid(cs):
                self._emit(cs)

    def _valid(self, cs: str) -> bool:
        if len(cs) < _MIN_LEN:
            return False
        if cs in _FALSE_POSITIVES:
            return False
        # Must have at least one letter in suffix (last char)
        if not cs[-1].isalpha():
            return False
        return True

    def _emit(self, callsign: str):
        now = time.time()

        if callsign in self._spotted:
            entry = self._spotted[callsign]
            entry['count']    += 1
            entry['last_seen'] = now
            if now - entry['last_seen_emitted'] < self.RESSPOT_SECS:
                return   # suppress re-emit, but count was incremented
            entry['last_seen_emitted'] = now
        else:
            country, flag = lookup_prefix(callsign)
            entry = {
                'callsign':          callsign,
                'country':           country,
                'flag':              flag,
                'frequency_mhz':     round(self.frequency_mhz, 4),
                'first_seen':        now,
                'last_seen':         now,
                'last_seen_emitted': now,
                'count':             1,
            }
            self._spotted[callsign] = entry

        payload = {k: v for k, v in entry.items() if k != 'last_seen_emitted'}
        for cb in self._callbacks:
            cb(payload)
