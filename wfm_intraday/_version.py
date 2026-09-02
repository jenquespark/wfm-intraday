"""Single authoritative version source for WFM Intraday.

The version lives in exactly one place. ``pyproject.toml`` declares
``dynamic = ["version"]`` and reads it back from this attribute, so
``importlib.metadata.version("wfm-intraday")`` and
``wfm_intraday.__version__`` always agree.
"""

__version__ = "0.2.1"
