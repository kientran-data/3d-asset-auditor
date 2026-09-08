"""Lightweight file fingerprinting for change detection.

Phase 1 uses only file_size_bytes + modified_time_ns.
SHA256 / content hashing is reserved for future phases.
"""


def create_fingerprint(size_bytes: int, mtime_ns: int) -> str:
    """Create a deterministic fingerprint string from file metadata.

    Format: "<size_bytes>:<mtime_ns>"
    """
    return f"{size_bytes}:{mtime_ns}"
