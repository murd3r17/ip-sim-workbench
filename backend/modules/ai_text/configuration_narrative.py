"""Keep model-authored code out of a configuration draft's narrative.

The validated structured payload is appended once by the service and used by
the deployment form. Split/unclosed code fences never reach the client.
Ordinary knowledge answers do not use this filter.
"""
import re
from .draft_guard import StreamingDraftGuard


class ConfigurationNarrativeGuard:
    def __init__(self, protected=None):
        self.scanner = StreamingDraftGuard(protected)
        self.buffer = ''
        self.fence = ''
        self.suppressed = False

    def _line(self, line):
        if self.fence:
            if re.match(r'^\s*' + re.escape(self.fence[0]) + '{' + str(len(self.fence)) + r',}\s*$', line):
                self.fence = ''
            return ''
        opening = re.search(r'`{3,}|~{3,}', line)
        if opening:
            self.suppressed = True
            self.fence = opening[0]
            prefix, rest = line[:opening.start()], line[opening.end():]
            closing = rest.find(self.fence)
            if closing >= 0:
                self.fence = ''
                return prefix + rest[closing + len(opening[0]):]
            return prefix + ('\n' if prefix and line.endswith('\n') else '')
        return line

    def _accept(self, text):
        self.buffer += text
        result = []
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            result.append(self._line(line + '\n'))
        return ''.join(result)

    def feed(self, text):
        return self._accept(self.scanner.feed(text))

    def flush(self):
        result = self._accept(self.scanner.flush())
        line, self.buffer = self.buffer, ''
        return result + self._line(line) if line else result
