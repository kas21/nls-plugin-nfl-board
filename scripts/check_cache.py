#!/usr/bin/env python3
"""
Simple script to inspect the NFL board cache contents.
Usage: python scripts/check_cache.py
"""

import sys
from pathlib import Path

# Add src to path so we can import diskcache
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import diskcache as dc
from datetime import datetime

def format_time_delta(seconds):
    """Format a time delta in seconds as days, hours, minutes, seconds."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")

    return " ".join(parts)

def main():
    cache = dc.Cache("/tmp/sb_cache")

    print("=" * 80)
    print("NFL Board Cache Inspector")
    print("=" * 80)
    print(f"Cache location: /tmp/sb_cache")
    print(f"Cache size: {cache.volume()} bytes")
    print(f"Total items: {len(cache)}")
    print()

    # Look for NFL-related cache keys
    nfl_keys = [key for key in cache if isinstance(key, str) and key.startswith('nfl_')]

    if not nfl_keys:
        print("❌ No NFL cache entries found!")
        print()
        print("All cache keys:")
        for key in list(cache)[:20]:  # Show first 20 keys
            print(f"  - {key}")
        return

    # Check eviction policy
    print(f"Cache settings:")
    print(f"  Eviction policy: {cache.eviction_policy}")
    print(f"  Size limit: {cache.size_limit} bytes")
    print(f"  Cull limit: {cache.cull_limit}")
    print(f"  Disk usage: {cache.volume()} bytes")
    print()

    print(f"Found {len(nfl_keys)} NFL cache entries:")
    print()

    for key in sorted(nfl_keys):
        # First try with expire_time=False to get even expired data
        value_no_check = cache.get(key, default=None, expire_time=False, retry=True)

        # Then check with expiration
        value, expire_time = cache.get(key, default=None, expire_time=True, retry=True)

        if value_no_check is None:
            print(f"❌ {key}: <completely missing from cache>")
            continue

        # Calculate time info
        if expire_time:
            now = datetime.now().timestamp()
            if expire_time > now:
                remaining = expire_time - now
                time_str = format_time_delta(remaining)
                status = f"✅ Valid (expires in {time_str})"
            else:
                age = now - expire_time
                time_str = format_time_delta(age)
                status = f"⚠️  Expired ({time_str} ago)"
        else:
            status = "♾️  Never expires"

        # Show data size (use value_no_check since value might be None if expired)
        data_value = value if value is not None else value_no_check
        if isinstance(data_value, (list, dict)):
            data_info = f"{len(data_value)} items"
        elif isinstance(data_value, str):
            data_info = f"{len(data_value)} chars"
        else:
            data_info = str(type(data_value).__name__)

        print(f"  {key}")
        print(f"    Status: {status}")
        print(f"    Data: {data_info}")

        # Show if expire_time=False would work
        if value is None and value_no_check is not None:
            print(f"    Note: ⚠️  Data exists but is expired (expire_time=False will return it)")
        print()

    print()
    print("=" * 80)
    print("To clear cache: rm -rf /tmp/sb_cache")
    print("=" * 80)

if __name__ == "__main__":
    main()
