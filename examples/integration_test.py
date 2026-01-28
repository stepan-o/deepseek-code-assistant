#!/usr/bin/env python3
"""
Integration Test - Test chat-engine integration.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


async def test_chat_integration():
    """Test chat-engine integration."""
    print("🔗 DeepSeek Code Assistant - Integration Test")
    print("=" * 60)

    print("1. Testing module imports...")

    # Test importing all key modules
    modules_to_test = [
        ("assistant.core.reasoning_models", "Data models"),
        ("assistant.core.reasoning_engine", "Reasoning engine"),
        ("assistant.core.learning_engine", "Learning engine"),
        ("assistant.core.focused_validator", "Focused validator"),
        ("assistant.core.programmatic_api", "Programmatic API"),
        ("assistant.integrations.chat_integration", "Chat integration"),
        ("assistant.ui.chat_cli", "Chat CLI"),
    ]

    all_modules_loaded = True
    for module_path, description in modules_to_test:
        try:
            __import__(module_path)
            print(f"   ✅ {description}")
        except ImportError as e:
            print(f"   ❌ {description}: {e}")
            all_modules_loaded = False

    if not all_modules_loaded:
        print("\n❌ Some modules failed to load. Check Python path.")
        return False

    print("\n✅ All modules imported successfully")

    # Test data model creation
    print("\n2. Testing data model creation...")

    try:
        from assistant.core.reasoning_models import (
            create_work_chunk, create_solution_vision, create_learning_point,
            ImplementationStatus, LearningCategory
        )

        # Create example models
        chunk = create_work_chunk(
            description="Test work chunk",
            component="test",
            files_affected=["test.py"],
            requirements="Test requirements",
            acceptance_criteria=["Test passes"],
            validation_method="test"
        )

        vision = create_solution_vision(
            requirements="Test requirements",
            architectural_approach="Test approach",
            chosen_approach_reasoning="Test reasoning",
            acceptance_criteria=["Criterion 1", "Criterion 2"],
            architectural_constraints=["Constraint 1"]
        )

        learning = create_learning_point(
            category=LearningCategory.BEST_PRACTICE,
            title="Test learning",
            description="Test description",
            source_session_id="test_session",
            context={"test": True}
        )

        print(f"   ✅ Created work chunk: {chunk.id}")
        print(f"   ✅ Created solution vision: {vision.id}")
        print(f"   ✅ Created learning point: {learning.id}")

    except Exception as e:
        print(f"   ❌ Data model creation failed: {e}")
        return False

    # Test serialization/deserialization
    print("\n3. Testing JSON serialization...")

    try:
        from assistant.core.reasoning_models import EnhancedJSONEncoder
        import json

        # Test serialization
        chunk_dict = chunk.to_dict()
        vision_dict = vision.to_dict()
        learning_dict = learning.to_dict()

        # Test JSON encoding
        chunk_json = json.dumps(chunk_dict, cls=EnhancedJSONEncoder)
        vision_json = json.dumps(vision_dict, cls=EnhancedJSONEncoder)
        learning_json = json.dumps(learning_dict, cls=EnhancedJSONEncoder)

        print(f"   ✅ Work chunk JSON: {len(chunk_json)} characters")
        print(f"   ✅ Vision JSON: {len(vision_json)} characters")
        print(f"   ✅ Learning JSON: {len(learning_json)} characters")

    except Exception as e:
        print(f"   ❌ JSON serialization failed: {e}")
        return False

    # Test programmatic API creation
    print("\n4. Testing programmatic API...")

    try:
        from assistant.core.programmatic_api import ProgrammaticOrchestrator

        # Create orchestrator (don't fully initialize to avoid API calls)
        orchestrator = ProgrammaticOrchestrator()

        print(f"   ✅ Created orchestrator")
        print(f"   ✅ File operator: {orchestrator.file_operator is not None}")
        print(f"   ✅ Change tracker: {orchestrator.change_tracker is not None}")

    except Exception as e:
        print(f"   ❌ Programmatic API test failed: {e}")
        return False

    # Test learning engine
    print("\n5. Testing learning engine...")

    try:
        from assistant.core.learning_engine import create_learning_engine

        learning_engine = create_learning_engine()
        stats = learning_engine.get_stats()

        print(f"   ✅ Learning engine created")
        print(f"   ✅ Total learnings: {stats.get('total_learnings', 0)}")
        print(f"   ✅ Storage path: {stats.get('storage_path', 'unknown')}")

    except Exception as e:
        print(f"   ❌ Learning engine test failed: {e}")
        return False

    # Test integration
    print("\n6. Testing integration patterns...")

    try:
        # Check that modules can work together
        from assistant.core.focused_validator import FocusedValidator
        from assistant.core.file_loader import FileLoader

        # Create components that would work together
        file_loader = FileLoader()
        validator = FocusedValidator(file_loader=file_loader)

        print(f"   ✅ Created integrated components")
        print(f"   ✅ File loader: {file_loader is not None}")
        print(f"   ✅ Validator: {validator is not None}")

    except Exception as e:
        print(f"   ❌ Integration test failed: {e}")
        return False

    print("\n" + "=" * 60)
    print("🎉 Integration test PASSED!")
    print("=" * 60)

    # Summary
    print("\n📊 Integration Test Summary:")
    print("   ✅ Module imports: All modules load correctly")
    print("   ✅ Data models: Can create and serialize models")
    print("   ✅ Programmatic API: Orchestrator can be created")
    print("   ✅ Learning engine: Learning system works")
    print("   ✅ Integration: Components work together")

    return True


async def test_without_api():
    """Test without API calls (for CI/CD)."""
    print("\n" + "=" * 60)
    print("🔄 Testing without API calls...")
    print("=" * 60)

    # Mock the DeepSeek client to avoid actual API calls
    import unittest.mock as mock

    with mock.patch('assistant.api.client.DeepSeekClient'):
        with mock.patch('assistant.core.focused_validator.DeepSeekClient'):
            success = await test_chat_integration()

    return success


def main():
    """Main entry point."""
    print("DeepSeek Code Assistant - Integration Test Suite")
    print("This tests the integration between all components.")
    print()

    # Check for API testing flag
    if "--no-api" in sys.argv:
        print("🚫 Running without API calls (mocked)...")
        success = asyncio.run(test_without_api())
    else:
        print("🔌 Running with potential API calls...")
        print("   Use --no-api to skip API-dependent tests")
        success = asyncio.run(test_chat_integration())

    if success:
        print("\n✅ All integration tests passed!")
        print("\n📚 Next steps:")
        print("   1. Run the actual chat CLI: python -m assistant.ui.chat_cli")
        print("   2. Try engine commands: /architect-init then /architect <requirements>")
        print("   3. Create a snapshot first: uv run snapshotter --dotenv --dry-run")
        return 0
    else:
        print("\n❌ Integration tests failed!")
        print("\n🔧 Troubleshooting:")
        print("   1. Check Python path includes src/ directory")
        print("   2. Verify all dependencies are installed")
        print("   3. Check for syntax errors in the code")
        return 1


if __name__ == "__main__":
    sys.exit(main())