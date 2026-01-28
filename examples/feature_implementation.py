#!/usr/bin/env python3
"""
Feature Implementation Demo - Complete feature implementation workflow.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from assistant.core.programmatic_api import ProgrammaticOrchestrator


async def demo_complete_workflow():
    """Demonstrate complete feature implementation workflow."""
    print("🚀 DeepSeek Code Assistant - Feature Implementation Demo")
    print("=" * 60)

    # Get user input
    print("\n📋 Please provide details for the feature implementation demo:")

    snapshot_dir = input("Enter snapshot directory path: ").strip()
    if not snapshot_dir:
        print("❌ Snapshot directory is required")
        return

    snapshot_path = Path(snapshot_dir)
    if not snapshot_path.exists():
        print(f"❌ Snapshot directory not found: {snapshot_dir}")
        return

    requirements = input("Enter feature requirements (e.g., 'Add authentication module'): ").strip()
    if not requirements:
        print("⚠️  Using example requirements")
        requirements = "Add user authentication with login, logout, and session management"

    print("\n" + "=" * 60)
    print(f"📦 Snapshot: {snapshot_dir}")
    print(f"📋 Requirements: {requirements}")
    print("=" * 60)

    # Create orchestrator
    print("\n1. 🏗️  Initializing architectural reasoning engine...")
    orchestrator = ProgrammaticOrchestrator()
    await orchestrator.initialize()

    print("✅ Engine initialized")

    try:
        # Create implementation plan
        print("\n2. 📝 Creating implementation plan...")
        session = await orchestrator.create_implementation_plan(requirements, snapshot_dir)

        print(f"✅ Plan created: Session {session.session_id}")
        print(f"   Vision ID: {session.vision.id}")
        print(f"   Components affected: {len(session.strategy.affected_components)}")
        print(f"   New components: {len(session.strategy.new_components)}")
        print(f"   Work chunks: {len(session.work_chunks)}")

        # Show vision details
        if session.vision:
            print(f"\n   Architectural approach:")
            print(f"   {session.vision.architectural_approach[:200]}...")

            print(f"\n   Acceptance criteria:")
            for i, criterion in enumerate(session.vision.acceptance_criteria[:3], 1):
                print(f"   {i}. {criterion}")
            if len(session.vision.acceptance_criteria) > 3:
                print(f"   ... and {len(session.vision.acceptance_criteria) - 3} more")

        # Show work chunks
        if session.work_chunks:
            print(f"\n   Work chunks:")
            for i, (chunk_id, chunk) in enumerate(list(session.work_chunks.items())[:3], 1):
                print(f"   {i}. {chunk.description}")
                print(f"      Component: {chunk.component}")
                print(f"      Complexity: {chunk.estimated_complexity}")
                print(f"      Files: {len(chunk.files_affected)}")
            if len(session.work_chunks) > 3:
                print(f"   ... and {len(session.work_chunks) - 3} more chunks")

        # Ask about execution
        print("\n3. ⚡ Execute the plan?")
        execute = input("Execute the implementation plan? (y/N): ").strip().lower()

        if execute == 'y':
            print("\n4. 🚀 Executing implementation plan...")
            executed_session = await orchestrator.execute_plan(session.session_id)

            print(f"✅ Execution completed: {executed_session.status}")

            # Show execution results
            completed = sum(1 for c in executed_session.work_chunks.values()
                            if c.status.value == 'validated')
            failed = sum(1 for c in executed_session.work_chunks.values()
                         if c.status.value == 'failed')

            print(f"   Chunks completed: {completed}/{len(executed_session.work_chunks)}")
            print(f"   Chunks failed: {failed}")

            if executed_session.applied_learnings:
                print(f"   Learnings applied: {len(executed_session.applied_learnings)}")

            # Validate
            print("\n5. 🔍 Validating implementation...")
            validation = await orchestrator.validate_implementation(session.session_id)

            print(f"✅ Validation: {validation.overall_status}")
            print(f"   Confidence: {validation.confidence_score:.1%}")
            print(f"   Issues found: {len(validation.issues_found)}")
            print(f"   Warnings: {len(validation.warnings)}")

        else:
            print("⏸️  Execution skipped")

        # Get session summary
        print("\n6. 📊 Getting session summary...")
        summary = await orchestrator.get_session_summary(session.session_id)

        print(f"📈 Session {session.session_id} summary:")
        print(f"   Status: {summary.get('status', 'unknown')}")
        print(f"   Duration: {summary.get('duration_minutes', 0)} minutes")
        print(f"   Work chunks: {summary.get('work_chunks', {}).get('total', 0)} total")
        if 'work_chunks' in summary:
            wc = summary['work_chunks']
            print(f"              {wc.get('completed', 0)} completed, {wc.get('failed', 0)} failed")

        print(f"\n💾 Session saved to: storage/sessions/{session.session_id}.json")

    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        print("\n7. 🧹 Cleaning up...")
        await orchestrator.cleanup()
        print("✅ Cleanup completed")

    print("\n" + "=" * 60)
    print("🎉 Feature implementation demo completed!")
    print("=" * 60)


def main():
    """Main entry point."""
    print("DeepSeek Code Assistant - Complete Feature Implementation Demo")
    print("This demo shows the complete workflow from requirements to implementation.")
    print()

    asyncio.run(demo_complete_workflow())

    print("\n📚 What was demonstrated:")
    print("   1. Architectural analysis of snapshot")
    print("   2. Vision creation based on requirements")
    print("   3. Implementation strategy planning")
    print("   4. Work breakdown into chunks")
    print("   5. Optional execution of plan")
    print("   6. Validation of results")
    print("   7. Session persistence and summary")
    print()
    print("💡 Try running with your own repository snapshot!")


if __name__ == "__main__":
    main()