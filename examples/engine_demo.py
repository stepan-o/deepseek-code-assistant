#!/usr/bin/env python3
"""
Engine Demo - Basic demonstration of architectural reasoning engine.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from assistant.core.programmatic_api import ProgrammaticOrchestrator


async def demo_basic_engine():
    """Demonstrate basic engine functionality."""
    print("🚀 DeepSeek Code Assistant - Engine Demo")
    print("=" * 50)

    # Create orchestrator
    print("1. Initializing orchestrator...")
    orchestrator = ProgrammaticOrchestrator()
    await orchestrator.initialize()

    print("✅ Orchestrator initialized")

    # List sessions (if any)
    print("\n2. Checking existing sessions...")
    sessions = orchestrator.list_sessions()

    if sessions:
        print(f"📁 Found {len(sessions)} session(s):")
        for session in sessions[:3]:
            print(f"   • {session['session_id']} - {session['status']}")
    else:
        print("📁 No existing sessions found")

    # Get learning stats
    print("\n3. Checking learning system...")
    stats = await orchestrator.get_learning_stats()

    print(f"📊 Learning system stats:")
    print(f"   Total learnings: {stats.get('total_learnings', 0)}")
    print(f"   Active learnings: {stats.get('active_learnings', 0)}")
    print(f"   By category: {stats.get('by_category', {})}")

    print("\n🎉 Demo completed successfully!")

    # Cleanup
    await orchestrator.cleanup()


async def demo_architectural_review():
    """Demonstrate architectural review."""
    print("\n" + "=" * 50)
    print("🏗️  Architectural Review Demo")
    print("=" * 50)

    # Ask for snapshot path
    snapshot_dir = input("Enter snapshot directory path (or press Enter to skip): ").strip()

    if not snapshot_dir:
        print("⚠️  Skipping architectural review demo")
        return

    snapshot_path = Path(snapshot_dir)
    if not snapshot_path.exists():
        print(f"❌ Snapshot directory not found: {snapshot_dir}")
        return

    # Create orchestrator
    orchestrator = ProgrammaticOrchestrator()
    await orchestrator.initialize()

    try:
        print(f"\nAnalyzing snapshot: {snapshot_dir}")
        analysis = await orchestrator.architectural_review(snapshot_dir)

        print(f"✅ Analysis completed:")
        print(f"   Components: {len(analysis.components)}")
        print(f"   Tech stack: {', '.join(analysis.tech_stack[:5])}")
        print(f"   Patterns: {', '.join(analysis.patterns[:3])}")
        print(f"   Strengths: {len(analysis.strengths)}")
        print(f"   Weaknesses: {len(analysis.weaknesses)}")
        print(f"   Confidence: {analysis.analysis_confidence:.1%}")

        # Show component summary
        if analysis.components:
            print(f"\n📦 Key components:")
            for i, (name, component) in enumerate(list(analysis.components.items())[:5], 1):
                print(f"   {i}. {name} ({component.type.value})")
                print(f"      Purpose: {component.purpose[:80]}...")

    except Exception as e:
        print(f"❌ Architectural review failed: {e}")

    finally:
        await orchestrator.cleanup()


def main():
    """Main entry point."""
    print("DeepSeek Code Assistant - Engine Demonstration")
    print("This demo shows the architectural reasoning engine capabilities.")
    print()

    # Run demos
    asyncio.run(demo_basic_engine())
    asyncio.run(demo_architectural_review())

    print("\n" + "=" * 50)
    print("📚 Next steps:")
    print("   1. Run feature_implementation.py for complete workflow demo")
    print("   2. Run learning_demo.py to see learning system in action")
    print("   3. Run integration_test.py for chat-engine integration test")
    print("=" * 50)


if __name__ == "__main__":
    main()