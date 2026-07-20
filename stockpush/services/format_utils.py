"""Shared formatting utilities for F5.1 push services."""

import shutil


def _has_systemctl() -> bool:
    """Check if systemctl is available on this system."""
    return shutil.which("systemctl") is not None


def format_channel_states(channel_states: str) -> str:
    """Color-code the 30m_mm2 (4th field) in channel state string.

    Red: 4th field is "多", or (4th field is "震" and 5th field is "多")
    Other: green
    """
    parts = channel_states.split("/")
    if len(parts) < 5:
        return channel_states
    val4 = parts[3]   # 30m_mm2
    val5 = parts[4]   # 30m_mm3
    if val4 == "多" or (val4 == "震" and val5 == "多"):
        color = "🔴"
    else:
        color = "🟢"
    parts[3] = f"{color}{val4}"
    return "/".join(parts)
