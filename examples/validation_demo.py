#!/usr/bin/env python3
"""
Validation Demo - Demonstrate the focused validation system.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from assistant.core.focused_validator import create_focused_validator, validate_single_change
from assistant.core.reasoning_models import CodeChange, ImplementationSession, CurrentStateAnalysis, SolutionVision
from datetime import datetime


async def demo_validation_system():
    """Demonstrate validation system functionality."""
    print("🔍 DeepSeek Code Assistant - Validation System Demo")
    print("=" * 60)

    # Create validator
    print("1. ⚙️  Initializing focused validator...")
    validator = await create_focused_validator()
    print("✅ Validator initialized")

    # Create mock session for testing
    print("\n2. 🎭 Creating mock implementation session...")

    mock_session = ImplementationSession(
        session_id="validation_demo_session",
        vision=SolutionVision(
            id="demo_vision",
            requirements="Add user authentication with secure password handling",
            architectural_approach="Use bcrypt for password hashing, JWT for tokens, repository pattern for data access",
            chosen_approach_reasoning="Secure, stateless, follows best practices",
            rejected_approaches=[],
            acceptance_criteria=[
                "Passwords are hashed with bcrypt",
                "JWT tokens are used for authentication",
                "Repository pattern abstracts data access",
                "No hardcoded secrets in code"
            ],
            architectural_constraints=[
                "No plain text password storage",
                "Use environment variables for configuration",
                "Follow 12-factor app principles"
            ],
            success_metrics={},
            risks_mitigated=[]
        ),
        strategy=None,
        work_chunks={},
        current_state=CurrentStateAnalysis(
            snapshot_dir="./snapshots/demo",
            timestamp=datetime.now(),
            overview="Demo authentication system",
            components={},
            patterns=["repository", "jwt"],
            tech_stack=["python", "fastapi", "postgresql"],
            strengths=["Modular design", "Good test coverage"],
            weaknesses=["Limited documentation"],
            gaps_for_assistant=[],
            risks=[]
        ),
        status="testing"
    )

    print("✅ Mock session created")
    print(f"   Acceptance criteria: {len(mock_session.vision.acceptance_criteria)}")
    print(f"   Constraints: {len(mock_session.vision.architectural_constraints)}")

    # Test Case 1: Good code change
    print("\n3. ✅ Test Case 1: Valid code change")

    good_change = CodeChange(
        id="good_change_001",
        description="Add bcrypt password hashing",
        change_type="add",
        file_path="src/auth/password_service.py",
        new_content="""
import bcrypt
import os

class PasswordService:
    def __init__(self):
        self.salt_rounds = int(os.getenv('BCRYPT_SALT_ROUNDS', 12))
    
    def hash_password(self, password: str) -> str:
        '''Hash password using bcrypt.'''
        salt = bcrypt.gensalt(rounds=self.salt_rounds)
        return bcrypt.hashpw(password.encode(), salt).decode()
    
    def verify_password(self, password: str, hashed: str) -> bool:
        '''Verify password against hash.'''
        return bcrypt.checkpw(password.encode(), hashed.encode())
""",
        reason="Implement secure password hashing as per acceptance criteria"
    )

    print(f"   Testing: {good_change.description}")
    print(f"   File: {good_change.file_path}")

    result1 = await validator.validate_change(good_change, mock_session)

    print(f"   Result: {result1.overall_status}")
    print(f"   Confidence: {result1.confidence_score:.1%}")
    print(f"   Issues found: {len(result1.issues_found)}")
    print(f"   Warnings: {len(result1.warnings)}")

    if result1.issues_found:
        print(f"   Issues:")
        for issue in result1.issues_found[:2]:
            print(f"     • {issue.get('reason', 'Unknown')}")

    # Test Case 2: Bad code change (hardcoded secret)
    print("\n4. ❌ Test Case 2: Invalid code change (hardcoded secret)")

    bad_change = CodeChange(
        id="bad_change_001",
        description="Add JWT token configuration",
        change_type="add",
        file_path="src/auth/jwt_service.py",
        new_content="""
import jwt

class JWTService:
    def __init__(self):
        self.secret_key = "my_super_secret_key_12345"  # BAD: Hardcoded secret!
        self.algorithm = "HS256"
    
    def create_token(self, user_id: str) -> str:
        payload = {"user_id": user_id, "exp": 1234567890}
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str) -> dict:
        return jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
""",
        reason="Add JWT token handling"
    )

    print(f"   Testing: {bad_change.description}")
    print(f"   File: {bad_change.file_path}")

    result2 = await validator.validate_change(bad_change, mock_session)

    print(f"   Result: {result2.overall_status}")
    print(f"   Confidence: {result2.confidence_score:.1%}")
    print(f"   Issues found: {len(result2.issues_found)}")
    print(f"   Warnings: {len(result2.warnings)}")

    if result2.issues_found:
        print(f"   Issues found:")
        for issue in result2.issues_found[:3]:
            print(f"     • {issue.get('reason', 'Unknown')}")
            if 'details' in issue:
                print(f"       {issue['details'][:80]}...")

    # Test Case 3: Code with TODO comment
    print("\n5. ⚠️  Test Case 3: Code with TODO comment")

    todo_change = CodeChange(
        id="todo_change_001",
        description="Add user repository",
        change_type="add",
        file_path="src/repositories/user_repository.py",
        new_content="""
from typing import Optional
from models.user import User

class UserRepository:
    def __init__(self, db_connection):
        self.db = db_connection
    
    def find_by_id(self, user_id: str) -> Optional[User]:
        # TODO: Implement database query
        # FIXME: Handle database errors properly
        return None
    
    def save(self, user: User) -> bool:
        try:
            # TODO: Add validation
            # TODO: Add transaction support
            self.db.execute("INSERT INTO users ...")
            return True
        except Exception as e:
            # BAD: Empty except clause
            pass
            return False
""",
        reason="Implement user repository"
    )

    print(f"   Testing: {todo_change.description}")
    print(f"   File: {todo_change.file_path}")

    result3 = await validator.validate_change(todo_change, mock_session)

    print(f"   Result: {result3.overall_status}")
    print(f"   Confidence: {result3.confidence_score:.1%}")
    print(f"   Issues found: {len(result3.issues_found)}")
    print(f"   Warnings: {len(result3.warnings)}")

    if result3.warnings:
        print(f"   Warnings:")
        for warning in result3.warnings[:2]:
            print(f"     • {warning.get('reason', 'Unknown')}")

    # Show validation criteria
    print("\n6. 📋 Validation Criteria Summary")
    print("   The validator checks 6 criteria:")
    print("   1. ✅ Didn't touch what we shouldn't")
    print("   2. ✅ No bad patterns/hacks")
    print("   3. ✅ Acceptance criteria met (LLM-assisted)")
    print("   4. ✅ Hard constraints not violated")
    print("   5. ✅ Architecture alignment (LLM-assisted)")
    print("   6. ✅ Risk assessment (LLM-assisted)")
    print("   Plus: Syntax validation")

    # Quick validation demo
    print("\n7. ⚡ Quick validation demonstration")

    from assistant.core.focused_validator import quick_validation

    # Create a mock work chunk
    from assistant.core.reasoning_models import create_work_chunk

    mock_chunk = create_work_chunk(
        description="Test validation chunk",
        component="auth",
        files_affected=["src/auth/test.py"],
        requirements="Test quick validation",
        acceptance_criteria=["Code works", "No errors"],
        validation_method="llm_review"
    )

    quick_result = await quick_validation(mock_chunk, mock_session)

    print(f"   Quick validation result: {'✅ Passed' if quick_result.get('passed') else '❌ Failed'}")
    print(f"   Issues found: {len(quick_result.get('issues_found', []))}")

    print("\n" + "=" * 60)
    print("🎉 Validation system demo completed!")
    print("=" * 60)


def main():
    """Main entry point."""
    print("DeepSeek Code Assistant - Focused Validation Demonstration")
    print("This demo shows how the validator checks code against 6 criteria.")
    print()

    asyncio.run(demo_validation_system())

    print("\n📚 What the validator checks:")
    print("   • Hardcoded secrets and bad patterns")
    print("   • Syntax errors")
    print("   • Architecture alignment")
    print("   • Acceptance criteria")
    print("   • Risk assessment")
    print("   • Constraint violations")
    print()
    print("💡 The validator helps maintain code quality and architectural integrity.")
    print("   It learns from past mistakes and applies those learnings.")


if __name__ == "__main__":
    main()