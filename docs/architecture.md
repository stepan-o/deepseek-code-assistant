┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Snapshotter   │    │   Local Files   │    │   Assistant     │
│   (langgraph)   │────▶   (artifacts)   │────▶   (chat)        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
│                        │                        │
├─ Runs occasionally     ├─ snapshotter artifacts ├─ Reads at startup
├─ Complex pipeline      ...                      ├─ Uses for grounding
└─ Self-contained                                 ├─ Loads particular files for context
                                                  └─ Iterative development through dialogue with the user


┌──────────────────────────────────────────────────────────────┐
│                    USER WORKFLOW                             │
├──────────────────────────────────────────────────────────────┤
│  START CYCLE:                                                │
│  1. User runs: uv run snapshotter --dotenv --dry-run         │
│     → Creates ./snapshots/{repo}/{timestamp}/                │
│                                                              │
│  2. User runs: deepseek load-snapshot ./snapshots/.../       │
│     → Assistant loads: repo_index.json + key files           │
│                                                              │
│  3. User runs: deepseek chat                                 │
│     → Assistant is "grounded" with architecture context      │
│                                                              │
│  WORK CYCLE:                                                 │
│  4. User + Assistant iterate via chat                        │
│     → Assistant suggests code changes                        │
│     → User implements changes in actual files                │
│                                                              │
│  END CYCLE:                                                  │
│  5. User runs snapshotter again (optional)                   │
│     → New snapshot with updated code                         │
│                                                              │
│  6. Start new cycle with fresh snapshot                      │
└──────────────────────────────────────────────────────────────┘


Repo structure:
deepseek-code-assistant/
├── src/
│   ├── assistant/
│   │   ├── __init__.py                     # Package marker for assistant
│   │   ├── api/
│   │   │   ├── __init__.py                 # Package marker for API submodule
│   │   │   └── client.py                   # HTTP client wrapper for DeepSeek API (config/env, usage, health checks)
│   │   ├── cli/
│   │   │   ├── __init__.py                 # Package marker for CLI commands
│   │   │   └── main.py                     # Main assistant CLI (chat, load-snapshot, utilities)
│   │   ├── core/
│   │   │   ├── __init__.py                 # Package marker for core logic
│   │   │   ├── context_manager.py          # Manages assistant context (load/save current_context.json)
│   │   │   ├── file_loader.py              # Helpers to load files/artifacts into assistant context
│   │   │   └── snapshot_loader.py          # TO ADD (planned loader for snapshot directories)
│   │   ├── integrations/
│   │   │   ├── __init__.py                 # Package marker for integrations
│   │   │   └── git.py                      # Git integration helpers (lightweight wrappers)
│   │   └── ui/
│   │       ├── __init__.py                 # Package marker for UI layer
│   │       └── chat_cli.py                 # Chat TUI/REPL for interactive assistant sessions
│   │   ├── tests/                           # Unit tests for assistant package
│   │   │   └── __init__.py                  # Test package marker
│   ├── shared/                              # Shared utilities across modules
│   │   ├── __init__.py                     # Package marker for shared utilities
│   │   └── git_operations.py               # Common Git functions reused across packages
│   └── snapshotter/                        # Offline repo analysis + artifact generation (LangGraph pipeline)
│       ├── __init__.py                     # Package marker for snapshotter
│       ├── cli.py                          # Snapshotter CLI entry (exposed as `snapshotter` command)
│       ├── git_ops.py                      # Low-level Git operations for cloning/inspection
│       ├── graph.py                        # Orchestrates the snapshot pipeline graph
│       ├── job.py                          # Job configuration and execution context
│       ├── main.py                         # Programmatic entry to run snapshot pipeline end-to-end
│       ├── pass1.py                        # Pass 1: static scanning, dependency indexing, manifests
│       ├── pass2_semantic.py               # Pass 2: LLM-based semantic analysis and summaries
│       ├── read_plan.py                    # Reads run plan/configuration for the pipeline
│       ├── s3_uploader.py                  # Uploads snapshot artifacts to S3 (boto3)
│       ├── utils.py                        # General utilities (paths, filtering, helpers)
│       └── validate_basic.py               # Basic validations and sanity checks for inputs
├── storage/
│   ├── conversations/
│   └── current_context.json                # Where snapshot context saves
├── .snapshotter_tmp/                       # Where snapshotter clones the target repo to
│   └── repo/
│       ├── (repo contents)                 # Full contents of the target repo
│       ...
└── snapshots/                              # Where snapshotter saves run outputs
    └── {repo}/
    └── {timestamp}/
        ├── ARCHITECTURE_SUMMARY_SNAPSHOT.json      # Comprehensive architecture overview with modules, data flows, risks
        ├── artifact_manifest.json                  # Manifest of all artifacts generated by snapshotter
        ├── DEPENDENCY_GRAPH.json                   # Internal file dependencies of the target repo
        ├── GAPS_AND_INCONSISTENCIES.json           # Risks and gaps identified in the target repo
        ├── ONBOARDING.md                           # Human-readable onboarding document based on the latest snapshot
        ├── PASS2_ARCH_PACK.json                    # Core architecture files with actual source code
        ├── PASS2_LLM_RAW.txt                       # Raw LLM output
        ├── PASS2_SEMANTIC.json                     # Output of LLM-based semantic analysis
        ├── PASS2_SUPPORT_PACK.json                 # Supporting files with source code
        └── repo_index.json                         # Index of all files in the target repo

📊 ASYNC VS SYNC SUMMARY:
Should be ASYNC (use network/API):
1. chat command - calls DeepSeek API
2. test command - tests API connection
3. ask command - calls DeepSeek API
4. clone command - clones from git remote
5. quickload command - clones from git remote

Should be SYNC (local file I/O only):
1. load command - loads local files (currently async but shouldn't be)
2. load-snapshot command - loads local snapshot files
3. list-snapshots command - lists local directories
4. snapshot-info command - reads local files
5. config command - reads local config files
6. context command - manages local context files
7. analyze command - analyzes local files
8. version command - prints static info
9. init command - creates local files

ARCHITECTURAL PRINCIPLE (SYNC VS ASYNC):
The codebase has a mismatch - some file operations are async when they shouldn't be.

Main principle: sync for LOCAL operations (file I/O), Async for NETWORK operations (API, git remote)



┌─────────────────────────────────────────────────────────────┐
│                ARCHITECTURAL REASONING ENGINE               │
│  (High-level thinking, vision, validation, orchestration)   │
└─────────────────┬───────────────────────────────────────────┘ 
                  │ Orchestrates
                  ▼
┌─────────────────────────────────────────────────────────────┐
│         PROGRAMMATIC API (Coordination Layer)               │
│  (Multi-file planning, structured Q&A, implementation state)│
└─────────────────┬───────────────────────────────────────────┘
                  │ Delegates to
                  ▼
┌─────────────────────────────────────────────────────────────┐
│           EXISTING MODULES (Specialized)                    │
│  - SnapshotLoader   - ContextManager  - FileLoader          │
│  - DeepSeekClient   - GitIntegration                        │
└─────────────────┬───────────────────────────────────────────┘
                  │ Use
                  ▼
┌─────────────────────────────────────────────────────────────┐
│              NEW EXECUTION MODULES                          │
│  - CodeGenerator   - FileOperator    - ChangeTracker        │
│  - TestRunner      - Validator       - Reporter             │
└─────────────────────────────────────────────────────────────┘



┌─────────────────────────────────────────────────────────────────────┐
│                    ARCHITECTURAL REASONING ENGINE                   │
├─────────────────────────────────────────────────────────────────────┤
│  Core Components:                                                   │
│   1. State Analyzer    - Understands current architecture           │
│   2. Vision Creator    - Envisions future state                     │
│   3. Strategy Planner  - Creates implementation strategy            │
│   4. Work Chunker      - Breaks strategy into executable chunks     │
│   5. Orchestrator      - Coordinates execution of chunks            │
│   6. Validator         - Validates results against vision           │
│   7. Iteration Manager - Handles feedback and iterations            │
│                                                                     │
│  Data Stores:                                                       │
│   - Knowledge Base    - Architectural patterns, best practices      │
│   - Session State     - Current reasoning session state             │
│   - Learning Memory   - Lessons from previous implementations       │
└─────────────────────────────────────────────────────────────────────┘



┌─────────────────────────────────────────────────────────────┐
│                      USER (Developer)                       │
└─────────────────┬───────────────────────────────────────────┘
                  │ Chat Commands & Feedback
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    CHAT CLI (Existing)                      │
│  /architect → │ /session → │ /learnings → │ Standard Chat   │
└─────────────────┬───────────────────────────────────────────┘
                  │ ChatIntegration (🆕 TO BUILD)
                  ▼
┌─────────────────────────────────────────────────────────────┐
│              ARCHITECTURAL REASONING ENGINE                 │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐            │
│  │ State   │ │ Vision  │ │ Planning│ │ Learning│            │
│  │ Analyzer│ │ Creator │ │ Engine  │ │ Engine  │            │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘            │
│                  │                     │                    │
│                  ▼                     ▼                    │
│          ┌─────────────┐       ┌─────────────┐              │
│          │   Strategy  │       │   Focused   │              │
│          │   Planner   │       │   Validator │              │
│          └─────────────┘       └─────────────┘              │
│                  │                     │                    │
│                  ▼                     ▼                    │
│          ┌─────────────┐       ┌─────────────┐              │
│          │   Work      │       │ Programmatic│              │
│          │   Chunker   │       │     API     │              │
│          └─────────────┘       └─────────────┘              │
│                                                             │
│  Uses: SnapshotLoader, FileLoader, DeepSeekClient           │
│  Produces: ImplementationSession, WorkChunks, Learnings     │
└─────────────────┬───────────────────────────────────────────┘
                  │ JSON Storage
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                  STORAGE (Local JSON Files)                 │
│  sessions/{id}.json │ learnings.json │ current_context.json │
└─────────────────────────────────────────────────────────────┘