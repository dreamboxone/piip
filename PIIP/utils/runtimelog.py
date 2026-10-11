# -*- coding: utf-8 -*-
"""Bound subprocess output without replacing descriptors held by workers."""
import os
import threading


class ProcessLog(object):
    def __init__(self, path, maximum=1024 * 1024):
        self.maximum = maximum
        self.handle = open(path, 'wb', 0)
        reader, self.writer = os.pipe()
        self.reader = os.fdopen(reader, 'rb', 0)
        self.thread = threading.Thread(target=self._drain)
        self.thread.daemon = True
        self.thread.start()

    def fileno(self):
        return self.writer

    def write(self, text):
        if not isinstance(text, bytes):
            text = text.encode('utf-8', 'replace')
        os.write(self.writer, text)

    def flush(self):
        pass

    def _drain(self):
        try:
            while True:
                data = os.read(self.reader.fileno(), 4096)
                if not data:
                    break
                if self.handle.tell() + len(data) > self.maximum:
                    self.handle.seek(0)
                    self.handle.truncate()
                self.handle.write(data)
        finally:
            self.reader.close()
            self.handle.close()

    def close(self):
        if self.writer is not None:
            os.close(self.writer)
            self.writer = None
        self.thread.join(1.0)
