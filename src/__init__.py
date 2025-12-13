"""AI Proxy

A proxy server that enables AI models to work with multiple API providers.
"""

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

try:
    from src._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"

__author__ = "AI Proxy"
