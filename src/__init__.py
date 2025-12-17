"""AI Proxy

A proxy server that enables AI models to work with multiple API providers.
"""

# 注意: dotenv 加载已统一移至 src/config/settings.py
# 不要在此处重复加载

try:
    from src._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"

__author__ = "AI Proxy"
