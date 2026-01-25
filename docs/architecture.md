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