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

"""The Gemini session setup, which differs per model family.



Gemini 3.5 Live Translate is a dedicated speech-to-speech translator and is

configured with a target language code. A general Live model has to be told

what to do with a prompt instead.

"""



import base64
import struct

import json

import os

import sys



HERE = os.path.dirname(os.path.abspath(__file__))

PKG = os.path.dirname(HERE)

sys.path.insert(0, HERE)

sys.path.insert(0, PKG)

sys.path.insert(0, os.path.dirname(PKG))



from translate import gemini



FAIL = []





def check(name, cond, extra=''):

    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))

    if not cond:

        FAIL.append(name)





def make(**kw):

    kw.setdefault('api_key', 'k')

    kw.setdefault('on_audio', lambda pcm: None)

    return gemini.GeminiTranslator(**kw)





print('model selection')

check('the translation model is the default',

      make().model == 'gemini-3.5-live-translate-preview', make().model)

check('it is first in the list',

      gemini.MODELS[0] == gemini.TRANSLATE_MODEL)

check('the general models are still offered', len(gemini.MODELS) >= 3)

check('any model id can be forced',

      make(model='some-future-model').model == 'some-future-model')



print('')

print('translate models are detected')

check('the 3.5 translate model', gemini.is_translate_model(

    'gemini-3.5-live-translate-preview') is True)

check('a future translate model', gemini.is_translate_model(

    'gemini-4-live-translate-x') is True)

check('a general live model is not one',

      gemini.is_translate_model('gemini-3.1-flash-live-preview') is False)

check('an empty model is not one', gemini.is_translate_model('') is False)

check('None is safe', gemini.is_translate_model(None) is False)



print('')

print('language codes')

check('Persian', gemini.language_code('Persian') == 'fa')

check('Farsi is the same thing', gemini.language_code('Farsi') == 'fa')

check('Arabic', gemini.language_code('Arabic') == 'ar')

check('English', gemini.language_code('English') == 'en')

check('Turkish', gemini.language_code('Turkish') == 'tr')

check('a raw code is passed through', gemini.language_code('de') == 'de')

check('a code is lowercased', gemini.language_code('DE') == 'de')

check('empty falls back to Persian', gemini.language_code('') == 'fa')

check('an unknown long name falls back',

      gemini.language_code('Klingonese') == 'fa')



print('')

print('setup message for the translation model')

setup = make(language='Persian').setup_message()['setup']

check('model is namespaced',

      setup['model'] == 'models/gemini-3.5-live-translate-preview',

      setup['model'])

gen = setup['generationConfig']

check('audio is requested', gen['responseModalities'] == ['AUDIO'])

check('translationConfig present', 'translationConfig' in gen)

check('target language is Persian',

      gen['translationConfig']['targetLanguageCode'] == 'fa')

check('echo is off so Persian speech is not repeated',

      gen['translationConfig']['echoTargetLanguage'] is False)

check('no prompt is sent to a translation model',

      'systemInstruction' not in setup)

check('the whole message is JSON-serialisable',

      isinstance(json.dumps(make().setup_message()), str))



arabic = make(language='Arabic').setup_message()['setup']

check('another language changes the code',

      arabic['generationConfig']['translationConfig']['targetLanguageCode']

      == 'ar')



print('')

print('setup message for a general live model')

setup = make(model='gemini-3.1-flash-live-preview').setup_message()['setup']

check('model is namespaced',

      setup['model'] == 'models/gemini-3.1-flash-live-preview')

check('audio is requested',

      setup['generationConfig']['responseModalities'] == ['AUDIO'])

check('a prompt is sent instead', 'systemInstruction' in setup)

check('the prompt says to translate',

      'ranslat' in setup['systemInstruction']['parts'][0]['text'])

check('no translationConfig for a general model',

      'translationConfig' not in setup['generationConfig'])



print('')

print('audio contract')

check('input is 16 kHz', gemini.IN_RATE == 16000)

check('output is 24 kHz', gemini.OUT_RATE == 24000)

check('endpoint is the BidiGenerateContent websocket',

      gemini.ENDPOINT.startswith('wss://')

      and 'BidiGenerateContent' in gemini.ENDPOINT)



print('')

print('feeding audio')

sent = []





class FakeWS(object):

    connected = True



    def send_json(self, payload):

        sent.append(payload)





g = make()

g._ws = FakeWS()

g.connected = True

check('feed reports success', g.feed(b'\x00\x01' * 800) is True)

payload = sent[-1]['realtimeInput']['audio']

check('mime type carries the sample rate',

      payload['mimeType'] == 'audio/pcm;rate=16000', payload['mimeType'])

check('audio is base64 encoded',

      base64.b64decode(payload['data']) == b'\x00\x01' * 800)

check('bytes sent are counted', g.bytes_in == 1600)



g.connected = False

check('feeding a closed session is refused, not fatal',

      g.feed(b'\x00') is False)



g2 = make()

check('feeding before connecting is refused', g2.feed(b'\x00') is False)



print('')

print('only speech that can still be translated in time is sent')

fresh = make()

fresh._ws = FakeWS()

fresh.connected = True

fresh.sessions = 1

fresh.play_position = lambda: 10.0

del sent[:]

fresh.enqueue(struct.pack('<h', 256) * 1600, position=10.5)   # heard in 0.5 s: too late

fresh.enqueue(struct.pack('<h', 256) * 1600, position=12.2)   # 2.2 s ahead: urgent, sent

import threading as _th

_t = _th.Thread(target=fresh._send_loop)

_t.daemon = True

_t.start()

import time as _time

for _ in range(40):

    if sent:

        break

    _time.sleep(0.05)

fresh._stop.set()

check('stale speech is skipped, not sent', fresh.stale_dropped == 3200,

      str(fresh.stale_dropped))

check('speech close to its playback is sent at once', len(sent) == 1, str(len(sent)))



print('')

print('receiving audio')

got = []

g3 = gemini.GeminiTranslator('k', lambda pcm: got.append(pcm))

g3._handle({'serverContent': {'modelTurn': {'parts': [

    {'inlineData': {'data': base64.b64encode(b'audio').decode('ascii')}}]}}})

check('audio reaches the callback', got == [b'audio'], str(got))

check('output bytes are counted', g3.bytes_out == 5)



g3._handle({'serverContent': {}})

check('an empty turn is ignored', len(got) == 1)

g3._handle({'setupComplete': {}})

check('a non-content message is ignored', len(got) == 1)

g3._handle({'serverContent': {'modelTurn': {'parts': [{'text': 'hi'}]}}})

check('a text part is ignored', len(got) == 1)

g3._handle({'serverContent': {'modelTurn': {'parts': [

    {'inlineData': {'data': 'not base64!!'}}]}}})

check('undecodable audio does not raise', len(got) <= 2)



print('')

if FAIL:

    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))

    sys.exit(1)

print('all checks passed')

