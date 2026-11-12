"""Reject leaked model control tokens across arbitrary stream boundaries.

Never parse their contents as executable tool calls. Real function calls still
require the existing typed planner, actor permission and executor validation.
"""


class ModelProtocolError(ValueError):
    pass


class AnswerProtocolGuard:
    _markers = ('<｜｜DSML', '</｜｜DSML', '<|DSML', '</|DSML', '<||DSML', '</||DSML',
                '<｜tool▁call', '<|tool_call')

    def __init__(self):
        self.pending = ''

    def feed(self, text):
        value = self.pending + (text or '')
        self.pending = ''
        lower = value.lower()
        if any(marker.lower() in lower for marker in self._markers):
            raise ModelProtocolError('Model emitted tool protocol in answer content; no execution authorized')
        keep = max((size for marker in self._markers for size in range(1, len(marker))
                    if lower.endswith(marker[:size].lower())), default=0)
        if keep:
            self.pending = value[-keep:]
            return value[:-keep]
        return value

    def flush(self):
        value, self.pending = self.pending, ''
        if len(value) > 1:
            raise ModelProtocolError('Model answer ended inside a control-token prefix')
        return value
