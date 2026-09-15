class WeChatLongshotError(Exception):
    """Base class for all project errors."""


class WindowNotFound(WeChatLongshotError):
    pass


class CaptureFailed(WeChatLongshotError):
    pass


class RegionNotFound(WeChatLongshotError):
    pass


class StitchFailed(WeChatLongshotError):
    pass
