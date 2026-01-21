#!/usr/bin/env python3
"""Test all imports work correctly."""
import sys
from pathlib import Path

# Add src to path for direct execution
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

def test_imports():
    """Test all critical imports."""
    print("Testing imports...")

    try:
        from assistant.api.client import DeepSeekClient
        print("✅ assistant.api.client: OK")
    except ImportError as e:
        print(f"❌ assistant.api.client: {e}")
        return False

    try:
        from assistant.ui.chat_cli import ChatCLI
        print("✅ assistant.ui.chat_cli: OK")
    except ImportError as e:
        print(f"❌ assistant.ui.chat_cli: {e}")
        return False

    try:
        from assistant.cli.main import cli
        print("✅ assistant.cli.main: OK")
    except ImportError as e:
        print(f"❌ assistant.cli.main: {e}")
        return False

    print("\n✅ All imports successful!")
    return True

if __name__ == "__main__":
    if test_imports():
        sys.exit(0)
    else:
        sys.exit(1)