#!/usr/bin/env python3
"""
Morse Code Decoder — Entry Point

Usage:
  python main.py                              # default mic input
  python main.py --list                       # list audio devices
  python main.py --device 'BlackHole 2ch'     # capture WebSDR browser audio
  python main.py --source sdr --freq 7.050    # RTL-SDR on 40m
  python main.py --mqtt-host 192.168.1.x      # + Home Assistant MQTT

Open http://localhost:5000 in your browser once running.
"""

import sys
import time
import threading
import argparse


def main():
    parser = argparse.ArgumentParser(
        description='Open Source Morse Code Decoder',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--source', choices=['audio', 'sdr'], default='audio',
        help='Audio input source (default: audio)',
    )
    parser.add_argument(
        '--device', type=str, default=None,
        help="Audio device name or index. Use --list to see options. "
             "Example: --device 'BlackHole 2ch'",
    )
    parser.add_argument(
        '--freq', type=float, default=7.050,
        help='RTL-SDR center frequency in MHz (default: 7.050 = 40m CW)',
    )
    parser.add_argument(
        '--gain', type=str, default='auto',
        help='RTL-SDR gain in dB, or "auto" (default: auto)',
    )
    parser.add_argument(
        '--list', action='store_true',
        help='List available audio input devices and exit',
    )
    parser.add_argument(
        '--port', type=int, default=5000,
        help='Web UI port (default: 5000)',
    )
    parser.add_argument(
        '--log-dir', type=str, default='logs',
        help='Directory for JSON Lines log files (default: ./logs)',
    )
    parser.add_argument(
        '--mqtt-host', type=str, default=None,
        help='MQTT broker hostname/IP for Home Assistant integration',
    )
    parser.add_argument(
        '--mqtt-port', type=int, default=1883,
        help='MQTT broker port (default: 1883)',
    )

    args = parser.parse_args()

    # ── Device list ────────────────────────────────────────────
    if args.list:
        from src.audio_source import SystemAudioSource
        devices = SystemAudioSource.list_devices()
        print('\nAvailable audio input devices:\n')
        for d in devices:
            print(f"  [{d['index']:2d}]  {d['name']}")
        print()
        print("  Tip: 'BlackHole 2ch' lets you capture WebSDR browser audio.")
        print("  Tip: Your Mac's built-in mic works for testing Morse from YouTube.\n")
        return

    # ── Imports (delayed so --list is instant) ─────────────────
    from src.audio_source import SystemAudioSource, SDRSource
    from src.decoder      import MorseDecoder
    from src.logger       import MorseLogger
    from web.app          import setup_decoder, run_server

    print()
    print('  ╔══════════════════════════════════╗')
    print('  ║      MORSE CODE DECODER          ║')
    print('  ╚══════════════════════════════════╝')
    print()

    # ── Audio source ───────────────────────────────────────────
    if args.source == 'sdr':
        source = SDRSource(frequency=args.freq * 1e6, gain=args.gain)
        print(f'  📡 Source: RTL-SDR @ {args.freq:.3f} MHz')
    else:
        device = args.device
        # Allow passing device index as a number
        if device and device.lstrip('-').isdigit():
            device = int(device)
        source = SystemAudioSource(device=device)
        label = device if device else 'system default'
        print(f'  🎤 Source: {label}')

    decoder = MorseDecoder()
    logger  = MorseLogger(log_dir=args.log_dir)

    print(f'  📝 Logs:   ./{args.log_dir}/')
    print(f'  🌐 Web UI: http://localhost:{args.port}')

    if args.mqtt_host:
        print(f'  📨 MQTT:   {args.mqtt_host}:{args.mqtt_port}')

    print()
    print('  Open the URL above in your browser.')
    print('  Press Ctrl+C to stop.\n')

    # ── Wire everything up ─────────────────────────────────────
    setup_decoder(
        source, decoder, logger,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
    )

    # ── Periodic log flush (background thread) ─────────────────
    def flush_loop():
        while True:
            time.sleep(5)
            wpm  = decoder.timing_decoder.wpm
            freq = decoder.tone_detector.detected_freq
            entry = logger.flush(wpm=wpm, frequency=freq)
            if entry:
                # Also publish completed message to MQTT
                try:
                    from web.app import _mqtt_client
                    if _mqtt_client:
                        import json
                        _mqtt_client.publish('morse/rx/message', json.dumps(entry))
                except Exception:
                    pass

    t = threading.Thread(target=flush_loop, daemon=True)
    t.start()

    # ── Run web server (blocks until Ctrl+C) ───────────────────
    try:
        run_server(port=args.port)
    except KeyboardInterrupt:
        pass
    finally:
        print('\n  Shutting down...')
        logger.force_flush(
            wpm=decoder.timing_decoder.wpm,
            frequency=decoder.tone_detector.detected_freq,
        )
        source.stop()
        print('  Goodbye.\n')


if __name__ == '__main__':
    main()
