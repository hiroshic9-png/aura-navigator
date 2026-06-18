"""レート制限の共有インスタンス

循環参照を避けるため、limiterをmain.pyやadvisor.pyから独立させる。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
