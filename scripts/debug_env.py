# debug_env.py
#!/usr/bin/env python3
"""Debug environment variable loading."""
import os
from pathlib import Path
from dotenv import load_dotenv

print("=" * 60)
print("Environment Variable Debug")
print("=" * 60)

# 1. Check current directory
print(f"\n1. Current directory: {Path.cwd()}")

# 2. Check if .env exists
env_path = Path(".env")
print(f"2. .env file exists: {env_path.exists()}")
if env_path.exists():
    print(f"   .env path: {env_path.absolute()}")
    print(f"   .env content:")
    with open(env_path, 'r') as f:
        print(f"   ---\n{f.read()}   ---")

# 3. Load .env file
print("\n3. Loading .env file...")
load_dotenv()

# 4. Check environment variables
print("\n4. Environment variables:")
print(f"   DEEPSEEK_API_KEY in os.environ: {'DEEPSEEK_API_KEY' in os.environ}")
api_key = os.getenv("DEEPSEEK_API_KEY")
print(f"   os.getenv('DEEPSEEK_API_KEY'): {repr(api_key)}")
print(f"   Length of key: {len(api_key) if api_key else 0}")

# 5. Check all env vars
print("\n5. All environment variables (filtered):")
for key, value in os.environ.items():
    if 'DEEPSEEK' in key.upper() or 'API' in key.upper():
        print(f"   {key}={repr(value)}")

print("\n" + "=" * 60)
