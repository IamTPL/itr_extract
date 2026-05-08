"""Shared slowapi Limiter instance — import từ cả app.py lẫn các router."""
from slowapi import Limiter
from slowapi.util import get_remote_address
from config.constants import USER_RATE_LIMIT

# Default limit cho tất cả routes; route-level decorator có thể override siết chặt hơn.
limiter = Limiter(key_func=get_remote_address, default_limits=[USER_RATE_LIMIT])
