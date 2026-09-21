# -*- coding: utf-8 -*-
#
# PIIP — IPTV player with live Persian audio translation
# Copyright (c) 2026 Routekernel. All rights reserved.
#
# Telegram : https://t.me/routekernel1
# YouTube  : https://youtube.com/@routekernel
# Project  : https://github.com/dreamboxone/piip
#
# Licensed under the PIIP End User Licence Agreement; see LICENSE.
# Unauthorised reverse engineering or removal of this notice is prohibited.
#
"""Gemini Live API client specialised for continuous speech translation.

Audio contract (from the Live API docs):
  input  : raw 16-bit PCM, 16 kHz, little-endian, mimeType "audio/pcm;rate=16000"
  output : raw 16-bit PCM, 24 kHz, little-endian

The session is kept alive for as long as the channel is playing; the Live
API caps session length, so a watchdog reconnects transparently and the
mixer simply sees a short gap in translated audio.
"""

import base64
import collections
import json
import threading
import time
import traceback

from . import ws

ENDPOINT = ('wss://generativelanguage.googleapis.com/ws/'
            'google.ai.generativelanguage.v1beta.GenerativeService.'
            'BidiGenerateContent')

# Purpose-built for speech-to-speech translation: it keeps the speaker's
# intonation and pacing and takes a target language instead of a prompt.
TRANSLATE_MODEL = 'gemini-3.5-live-translate-preview'

# Live-API-capable models, best first. Overridable from settings.
MODELS = [
    TRANSLATE_MODEL,
    'gemini-3.1-flash-live-preview',
    'gemini-2.5-flash-native-audio-preview-12-2025',
]

# BCP-47 codes for translationConfig.
LANGUAGE_CODES = {
    'Persian': 'fa',
    'Farsi': 'fa',
    'Arabic': 'ar',
    'English': 'en',
    'Turkish': 'tr',
    'Kurdish': 'ku',
    'Azerbaijani': 'az',
}


def language_code(language):
    """'Persian' -> 'fa'. An unknown name is assumed to already be a code."""
    if not language:
        return 'fa'
    hit = LANGUAGE_CODES.get(language)
    if hit:
        return hit
    text = str(language).strip()
    return text.lower() if len(text) <= 5 else 'fa'


def is_translate_model(model):
    """Dedicated translation models take translationConfig, not a prompt."""
    return 'live-translate' in (model or '')

IN_RATE = 16000
OUT_RATE = 24000
IN_BPS = IN_RATE * 2

# Input is sent at the speed it is spoken. ffmpeg decodes HLS segments in
# bursts of several seconds; pushed out as fast as they arrive, Live stops
# reading the socket, a send then blocks for 10-30 s and the translation
# comes back later in one burst that no longer fits the picture.
PACE_LEAD_S = 0.3        # how far ahead of real time input may run
# Input read ahead of real time (HLS bursts, catch-up after a stall) waits
# here rather than being lost; the viewer is correspondingly further behind.
MAX_QUEUE_S = 30.0
# As E2Dub does on the same receiver, Gemini is only ever given speech it can
# still translate in time. A chunk the viewer will hear in less than this is
# skipped: translated late, it would play over a later picture.
MIN_LEAD_S = 1.5
# Closer than this to its playback, a chunk is sent at once instead of paced.
URGENT_S = 1.5
SEND_TIMEOUT_S = 5.0     # a send slower than this ends the session
RESUME_KEEP_S = 2.0      # input kept across a reconnect

PROMPT = (
    u"You are a live simultaneous interpreter for a television broadcast. "
    u"Translate everything you hear into natural spoken Persian (Farsi). "
    u"Speak ONLY the Persian translation. "
    u"Never answer questions, never add commentary, never describe what you hear, "
    u"never mention that you are translating. "
    u"If a segment is music, silence or noise, stay silent. "
    u"Keep the translation short and keep pace with the speaker: if you fall "
    u"behind, condense rather than skip. Preserve names and numbers exactly."
)


class GeminiTranslator(object):
    """Streams PCM in, calls on_audio(pcm24k_bytes) as translation comes back."""

    def __init__(self, api_key, on_audio, model=None, prompt=None,
                 language=u'Persian', on_state=None, log=None,
                 positional=False):
        self.api_key = api_key
        self.on_audio = on_audio
        # on_audio(pcm, sent_position) instead of on_audio(pcm)
        self.positional = positional
        self.on_state = on_state or (lambda s: None)
        self.model = model or MODELS[0]
        self.language = language
        self.language_code = language_code(language)
        self.prompt = (prompt or PROMPT).replace(u'Persian (Farsi)', language)
        self.log = log or (lambda *a: None)

        self._ws = None
        self._stop = threading.Event()
        self._sendlock = threading.Lock()
        self._thread = None
        self.connected = False
        self.bytes_in = 0
        self.bytes_out = 0
        self.last_audio_at = 0.0
        self._session_handle = None
        self._resume = False
        self._go_away = False
        self.sessions = 0
        self.errors = 0
        self.last_error = ''
        self._queue = collections.deque()
        self._queued = 0
        self._qlock = threading.Lock()
        self._wake = threading.Event()
        self._sender = None
        self.dropped_in = 0
        self.send_max_ms = 0
        self.on_sent = None      # callable(pcm, t) for diagnostics
        # Programme position (seconds of input) at the end of the last chunk
        # sent; replies are scheduled against it.
        self.sent_position = 0.0
        # callable() -> programme seconds the viewer is hearing now
        self.play_position = None
        self.stale_dropped = 0
        self._active_audio = False

    def setup_message(self):
        """The first frame of the session, which differs per model family."""
        if is_translate_model(self.model):
            setup = {
                'setup': {
                    'model': 'models/%s' % self.model,
                    'generationConfig': {
                        'responseModalities': ['AUDIO'],
                        'translationConfig': {
                            'targetLanguageCode': self.language_code,
                            # Stay silent when the speaker is already
                            # talking in the target language.
                            'echoTargetLanguage': False,
                        },
                    },
                    # A null handle asks Gemini to begin issuing resumption
                    # tokens; subsequent reconnects attach the newest token.
                    'sessionResumption': {
                        'handle': self._session_handle if self._resume else None
                    },
                }
            }
            return setup
        # A general Live model has to be told what to do instead.
        return {
            'setup': {
                'model': 'models/%s' % self.model,
                'generationConfig': {'responseModalities': ['AUDIO']},
                'systemInstruction': {'parts': [{'text': self.prompt}]},
            }
        }

    # ------------------------------------------------------------- lifecycle

    def start(self):
        self._thread = threading.Thread(target=self._run, name='gemini')
        self._thread.daemon = True
        self._thread.start()
        self._sender = threading.Thread(target=self._send_loop,
                                        name='gemini-send')
        self._sender.daemon = True
        self._sender.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        w = self._ws
        if w:
            try:
                w.close()
            except Exception:
                pass

    def _run(self):
        backoff = 0.5
        pending = None
        while not self._stop.is_set():
            try:
                conn = pending or self._open()
                pending = None
                backoff = 0.5
                pending = self._receive(conn)
            except Exception as e:
                self.connected = False
                self.errors += 1
                self.last_error = str(e)[:300]
                self.on_state('error: %s' % e)
                self.log('[gemini] session ended: %s' % e)
                if self._session_handle is not None and self._resume:
                    # A rejected resumption must not block every retry.
                    self.log('[gemini] dropping the resumption handle')
                    self._resume = False
                    self._session_handle = None
            if self._stop.is_set() or pending is not None:
                continue
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 8.0)

    def _open(self):
        """Connect and complete setup; the new session is not yet active."""
        url = '%s?key=%s' % (ENDPOINT, self.api_key)
        self.log('[gemini] connecting, model=%s, target=%s%s'
                 % (self.model, self.language_code,
                    ', resuming' if self._resume and self._session_handle else ''))
        conn = ws.connect(url, timeout=15.0)
        try:
            conn.send_json(self.setup_message())
            # The server acknowledges with setupComplete before taking audio.
            while not self._stop.is_set():
                msg = conn.recv_json()
                if msg is None:
                    raise ws.WSError('closed before setupComplete')
                if 'setupComplete' in msg:
                    break
                if 'error' in msg:
                    raise ws.WSError(str(msg['error'])[:300])
            # Reads treat the timeout as "nothing yet"; writes use it as the
            # limit on a stalled uplink.
            conn.sock.settimeout(SEND_TIMEOUT_S)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            raise
        return conn

    def _activate(self, conn):
        with self._qlock:
            # Keep only the newest input: older speech would come back too
            # late for the picture it belongs to.
            keep = int(RESUME_KEEP_S * IN_BPS)
            while self._queued > keep and self._queue:
                _pos, old = self._queue.popleft()
                self._queued -= len(old)
                self.dropped_in += len(old)
        self._ws = conn
        self._active_audio = False
        self.connected = True
        self.sessions += 1
        self._go_away = False
        self._wake.set()
        self.on_state('connected')
        self.log('[gemini] session ready (#%d)' % self.sessions)

    def _receive(self, conn):
        """Serve one session; return its successor after a goAway, or None."""
        self._activate(conn)
        successor = None
        try:
            while not self._stop.is_set():
                msg = conn.recv_json()
                if msg is None:
                    break
                if 'goAway' in msg:
                    self.log('[gemini] server goAway %s' % json.dumps(msg['goAway']))
                    # Open the next session while this one still delivers
                    # the speech already in progress, then hand over.
                    self._resume = bool(self._session_handle)
                    try:
                        successor = self._open()
                    except Exception as exc:
                        self.log('[gemini] handover failed: %s' % exc)
                        self._resume = False
                        self._session_handle = None
                        break
                    self._drain_later(conn)
                    conn = None
                    return successor
                self._handle(msg)
        finally:
            if conn is not None:
                if self._ws is conn:
                    self.connected = False
                    self._ws = None
                try:
                    conn.close()
                except Exception:
                    pass
        return successor

    def _drain_later(self, old):
        """Let the old session finish its current sentence in the background."""
        def drain():
            deadline = time.time() + 10.0
            try:
                while time.time() < deadline and not self._stop.is_set():
                    msg = old.recv_json()
                    if msg is None:
                        break
                    if msg.get('serverContent'):
                        self._handle(msg, draining=True)
            except Exception:
                pass
            finally:
                try:
                    old.close()
                except Exception:
                    pass
        t = threading.Thread(target=drain, name='gemini-drain')
        t.daemon = True
        t.start()

    def _handle(self, msg, draining=False):
        sc = msg.get('serverContent')
        if not sc:
            update = msg.get('sessionResumptionUpdate') or {}
            if update.get('resumable') and update.get('newHandle'):
                self._session_handle = update['newHandle']
            return
        turn = sc.get('modelTurn') or {}
        for part in turn.get('parts', []):
            inline = part.get('inlineData')
            if not inline:
                continue
            data = inline.get('data')
            if not data:
                continue
            try:
                pcm = base64.b64decode(data)
            except Exception:
                continue
            if pcm:
                if draining and self._active_audio:
                    # The new session has started speaking: two voices
                    # interleaved would be worse than a clipped sentence.
                    return
                if not draining:
                    self._active_audio = True
                self.bytes_out += len(pcm)
                self.last_audio_at = time.time()
                if self.positional:
                    self.on_audio(pcm, self.sent_position)
                else:
                    self.on_audio(pcm)
        # Live Translate interruptions are conversational metadata, not an
        # instruction to discard audio already scheduled by the mixer.

    # ----------------------------------------------------------------- input

    def enqueue(self, pcm16k, position=None):
        """Queue input for the paced sender; never blocks the caller.

        `position` is the programme time (seconds) at the END of the chunk.
        """
        if not pcm16k:
            return
        with self._qlock:
            self._queue.append((position, pcm16k))
            self._queued += len(pcm16k)
            limit = int(MAX_QUEUE_S * IN_BPS)
            while self._queued > limit and self._queue:
                _pos, old = self._queue.popleft()
                self._queued -= len(old)
                self.dropped_in += len(old)
        self._wake.set()

    def clear_queue(self):
        with self._qlock:
            self._queue.clear()
            self._queued = 0

    def queued_seconds(self):
        return self._queued / float(IN_BPS)

    def _send_loop(self):
        clock = None          # (wall time, bytes sent) of the pacing origin
        session = -1
        while not self._stop.is_set():
            if not self.connected or self._ws is None:
                clock = None
                self._wake.wait(0.2)
                self._wake.clear()
                continue
            if session != self.sessions:
                session, clock = self.sessions, None
            with self._qlock:
                item = self._queue[0] if self._queue else None
            if item is None:
                self._wake.wait(0.1)
                self._wake.clear()
                continue
            now = time.time()
            urgent = False
            play = None
            if self.play_position is not None and item[0] is not None:
                try:
                    play = self.play_position()
                except Exception:
                    play = None
            if play:
                margin = item[0] - play
                if margin < MIN_LEAD_S:
                    with self._qlock:
                        if self._queue and self._queue[0] is item:
                            self._queue.popleft()
                            self._queued -= len(item[1])
                            self.stale_dropped += len(item[1])
                    continue
                urgent = margin < MIN_LEAD_S + URGENT_S
            if clock is None:
                clock = [now, 0]
            due = clock[0] + clock[1] / float(IN_BPS) - PACE_LEAD_S
            if due > now and not urgent:
                self._stop.wait(min(0.1, due - now))
                continue
            if now - due > 1.0:
                # Input paused (no speech decoded); restart the clock
                # instead of bursting to catch up.
                clock = [now, 0]
            with self._qlock:
                if not self._queue or self._queue[0] is not item:
                    continue
                self._queue.popleft()
                position, chunk = item
                self._queued -= len(chunk)
            t0 = time.time()
            if not self.feed(chunk):
                clock = None
                continue
            if position is not None:
                self.sent_position = position
            took = int((time.time() - t0) * 1000)
            self.send_max_ms = max(self.send_max_ms, took)
            clock[1] += len(chunk)
            if self.on_sent is not None:
                try:
                    self.on_sent(chunk, t0)
                except Exception:
                    pass

    def feed(self, pcm16k):
        """Push a chunk of 16 kHz mono little-endian PCM."""
        conn = self._ws
        if not conn or not self.connected:
            return False
        payload = {
            'realtimeInput': {
                'audio': {
                    'data': base64.b64encode(pcm16k).decode('ascii'),
                    'mimeType': 'audio/pcm;rate=%d' % IN_RATE,
                }
            }
        }
        try:
            with self._sendlock:
                conn.send_json(payload)
            self.bytes_in += len(pcm16k)
            return True
        except Exception as e:
            self.log('[gemini] feed failed: %s' % e)
            self.connected = False
            # A half-dead socket must not stay "connected" forever: closing
            # it ends the receive loop, and _run opens a fresh session.
            try:
                conn.close()
            except Exception:
                pass
            return False
