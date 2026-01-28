#!/usr/bin/env python3
"""
Learning Demo - Demonstrate the learning system capabilities.
"""

import asyncio
import sys
from pathlib import Path
import json

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from assistant.core.programmatic_api import ProgrammaticOrchestrator
from assistant.core.learning_engine import create_learning_engine, LearningCategory
from assistant.core.reasoning_models import create_learning_point, ImplementationSession, CurrentStateAnalysis


async def demo_learning_system():
    """Demonstrate learning system functionality."""
    print("🧠 DeepSeek Code Assistant - Learning System Demo")
    print("=" * 60)

    # Create learning engine
    print("1. 📚 Initializing learning system...")
    learning_engine = create_learning_engine()

    # Get stats
    stats = learning_engine.get_stats()
    print(f"✅ Learning system initialized")
    print(f"   Total learnings: {stats.get('total_learnings', 0)}")
    print(f"   Active learnings: {stats.get('active_learnings', 0)}")
    print(f"   Storage path: {stats.get('storage_path', 'unknown')}")

    # Create some example learnings if none exist
    if stats.get('active_learnings', 0) < 3:
        print("\n2. 📝 Creating example learnings...")

        # Example learning 1: Architecture
        learning1 = create_learning_point(
            category=LearningCategory.ARCHITECTURE,
            title="API Gateway pattern for microservices",
            description="Using an API gateway as single entry point improves security and simplifies client code",
            source_session_id="demo_session_001",
            context={
                "pattern": "API Gateway",
                "benefits": ["security", "simplification", "routing"],
                "use_case": "microservices architecture"
            },
            pattern_recognized="API Gateway pattern",
            application_conditions=["microservices architecture", "multiple API endpoints"],
            confidence_score=0.9,
            relevance_keywords=["api", "gateway", "microservices", "architecture"]
        )

        # Example learning 2: Mistake
        learning2 = create_learning_point(
            category=LearningCategory.MISTAKE,
            title="Hardcoded configuration values",
            description="Hardcoding configuration values makes deployment difficult and violates 12-factor app principles",
            source_session_id="demo_session_002",
            context={
                "mistake": "hardcoded database credentials",
                "impact": "deployment failures",
                "fix": "use environment variables"
            },
            mistake_to_avoid="Hardcoding configuration values",
            application_conditions=["configuration management", "deployment"],
            confidence_score=0.95,
            relevance_keywords=["configuration", "hardcoded", "environment", "deployment"]
        )

        # Example learning 3: Best Practice
        learning3 = create_learning_point(
            category=LearningCategory.BEST_PRACTICE,
            title="Repository pattern for data access",
            description="Repository pattern abstracts data access and makes testing easier",
            source_session_id="demo_session_003",
            context={
                "pattern": "Repository",
                "benefits": ["testability", "abstraction", "maintainability"],
                "languages": ["python", "java", "c#"]
            },
            best_practice_identified="Use repository pattern for data access layer",
            application_conditions=["data access layer", "need for testing", "multiple data sources"],
            confidence_score=0.85,
            relevance_keywords=["repository", "pattern", "data", "access", "testing"]
        )

        # Save learnings
        learning_engine.storage.save_learning(learning1)
        learning_engine.storage.save_learning(learning2)
        learning_engine.storage.save_learning(learning3)

        print(f"✅ Created 3 example learnings")

    # Search for learnings
    print("\n3. 🔍 Searching for learnings...")

    search_queries = ["api", "configuration", "testing", "architecture"]

    for query in search_queries:
        results = learning_engine.search_learnings(query, limit=2)
        print(f"\n   Search: '{query}'")
        if results:
            for learning, score in results:
                print(f"   • {learning.title} (score: {score:.2f})")
                print(f"     Category: {learning.category.value}")
                print(f"     Relevance: {', '.join(learning.relevance_keywords[:3])}")
        else:
            print(f"   No results found for '{query}'")

    # Get learnings by category
    print("\n4. 📂 Learnings by category...")

    categories = [
        LearningCategory.ARCHITECTURE,
        LearningCategory.BEST_PRACTICE,
        LearningCategory.MISTAKE
    ]

    for category in categories:
        learnings = learning_engine.get_learnings_by_category(category, limit=2)
        print(f"\n   Category: {category.value}")
        if learnings:
            for learning in learnings:
                print(f"   • {learning.title}")
                print(f"     {learning.description[:80]}...")
        else:
            print(f"   No learnings in this category")

    # Demonstrate learning application
    print("\n5. ⚡ Demonstrating learning application...")

    # Create a mock session
    mock_session = ImplementationSession(
        session_id="demo_application_session",
        vision=None,
        strategy=None,
        work_chunks={},
        current_state=CurrentStateAnalysis(
            snapshot_dir="./snapshots/demo",
            timestamp=asyncio.get_event_loop().time(),
            overview="Demo microservices architecture",
            components={},
            patterns=["microservices"],
            tech_stack=["python", "fastapi", "postgresql"],
            strengths=[],
            weaknesses=[],
            gaps_for_assistant=[],
            risks=[]
        ),
        status="planning"
    )

    # Apply learnings to session
    applied_learnings = learning_engine.apply_to_session(mock_session)

    print(f"✅ Applied {len(applied_learnings)} learnings to demo session")
    if applied_learnings:
        for i, applied in enumerate(applied_learnings[:2], 1):
            print(f"   {i}. {applied.get('learning_title', 'Unknown')}")
            print(f"      Impact: {applied.get('impact', {}).get('type', 'Unknown')}")

    # Export/Import demonstration
    print("\n6. 💾 Export/Import demonstration...")

    # Export learnings
    export_path = Path("storage/learnings_export.json")
    success = learning_engine.export_learnings(export_path)

    if success:
        print(f"✅ Exported learnings to {export_path}")

        # Count lines in export file
        try:
            with open(export_path, 'r') as f:
                export_data = json.load(f)
            print(f"   Exported {len(export_data)} learnings")
        except:
            pass

    # Updated stats
    print("\n7. 📊 Final learning system statistics:")
    final_stats = learning_engine.get_stats()

    stats_table = [
        ("Total learnings", final_stats.get('total_learnings', 0)),
        ("Active learnings", final_stats.get('active_learnings', 0)),
        ("Archived learnings", final_stats.get('archived_learnings', 0)),
    ]

    for category, count in final_stats.get('by_category', {}).items():
        stats_table.append((f"  • {category}", count))

    for name, value in stats_table:
        print(f"   {name}: {value}")

    print("\n" + "=" * 60)
    print("🎉 Learning system demo completed!")
    print("=" * 60)

    # Cleanup export file
    if export_path.exists():
        export_path.unlink()
        print(f"🧹 Cleaned up export file")


def main():
    """Main entry point."""
    print("DeepSeek Code Assistant - Learning System Demonstration")
    print("This demo shows how the learning system captures, stores, and applies insights.")
    print()

    asyncio.run(demo_learning_system())

    print("\n📚 Learning system capabilities demonstrated:")
    print("   1. Learning storage and indexing")
    print("   2. Keyword-based search")
    print("   3. Category-based retrieval")
    print("   4. Relevance scoring")
    print("   5. Application to sessions")
    print("   6. Export/Import functionality")
    print()
    print("💡 The learning system helps the assistant improve over time!")
    print("   Each implementation session contributes to the knowledge base.")


if __name__ == "__main__":
    main()