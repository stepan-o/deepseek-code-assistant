# src/assistant/ui/chat_cli.py
"""
Chat CLI interface for DeepSeek Code Assistant - UPDATED WITH ENGINE INTEGRATION.
"""
import asyncio
import sys
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
import readline  # For better input handling

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED

from assistant.core.context_manager import ContextManager
from assistant.core.file_loader import FileLoader

console = Console()


class ChatCLI:
    def __init__(self, api_client, config_path: str = "config.yaml"):
        self.api_client = api_client
        self.config_path = config_path
        self.conversation_active = True

        # Initialize context manager
        self.context_manager = ContextManager()

        # Initialize engine integration (will be initialized async)
        self.engine_integration = None
        self.engine_available = False

        # Load configuration
        self.config = self._load_config()

        # Load existing context if available
        self._load_context()

        # Initialize messages list from context manager
        self.messages = []

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        import yaml

        path = Path(self.config_path)
        if not path.exists():
            # Try to find config.yaml in current directory
            path = Path.cwd() / "config.yaml"
            if not path.exists():
                return {}

        with open(path, 'r') as f:
            config = yaml.safe_load(f)

        return config or {}

    def _load_context(self):
        """Load existing context if available."""
        ctx_file = Path("storage/current_context.json")
        if ctx_file.exists():
            try:
                self.context_manager.load_context(str(ctx_file))

                # Show context info
                if self.context_manager.code_context.files:
                    file_count = len(self.context_manager.code_context.files)

                    # Check if we have snapshot context
                    if hasattr(self.context_manager, 'snapshot_metadata') and self.context_manager.snapshot_metadata:
                        snapshot_name = self.context_manager.snapshot_metadata.get('snapshot_name', 'unknown')
                        console.print(f"[green]✅ Loaded snapshot context: {snapshot_name}[/green]")
                        console.print(f"[dim]   with {file_count} file(s)[/dim]")
                    else:
                        console.print(f"[green]✅ Loaded context with {file_count} file(s)[/green]")

                    # Show file list
                    files = list(self.context_manager.code_context.files.keys())
                    if len(files) <= 5:
                        for f in files:
                            console.print(f"   📄 {f}")
                    else:
                        for f in files[:3]:
                            console.print(f"   📄 {f}")
                        console.print(f"   ... and {len(files) - 3} more")

                    if self.context_manager.code_context.current_file:
                        console.print(f"[yellow]🔍 Focus file: {self.context_manager.code_context.current_file}[/yellow]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not load context: {e}[/yellow]")

    async def initialize_engine(self):
        """Initialize the engine integration."""
        try:
            console.print("[dim]Initializing architectural reasoning engine...[/dim]")
            # Try to import and initialize engine integration
            from assistant.integrations.chat_integration import ChatIntegration, create_chat_integration
            self.engine_integration = await create_chat_integration(self, self.config_path)
            self.engine_available = True
            console.print("[green]✅ Engine integration initialized[/green]")
            return True
        except ImportError as e:
            console.print(f"[yellow]⚠️  Engine integration not available: {e}[/yellow]")
            console.print("[dim]Some features may be unavailable. Install all dependencies.[/dim]")
            self.engine_available = False
            return False
        except Exception as e:
            console.print(f"[red]❌ Failed to initialize engine: {e}[/red]")
            console.print("[dim]Engine features will be unavailable[/dim]")
            self.engine_integration = None
            self.engine_available = False
            return False

    async def start(self):
        """Start the chat interface with engine integration."""
        # Display welcome banner
        console.print(Panel.fit(
            "[bold cyan]🤖 DeepSeek Code Assistant[/bold cyan]",
            subtitle="Context-aware AI pair programmer with architectural reasoning"
        ))

        # Initialize engine integration (if available)
        await self.initialize_engine()

        # Show engine status
        if self.engine_available and self.engine_integration:
            engine_status = self.engine_integration.get_engine_status()
            status_text = "✅ Ready" if engine_status['initialized'] else "❌ Not available"
            console.print(f"[cyan]🏗️  Architectural Engine: {status_text}[/cyan]")

        # Show context status
        if self.context_manager.code_context.files:
            self._show_context_status()
        else:
            console.print("[yellow]ℹ️  No file context loaded[/yellow]")
            console.print("   Use [bold]deepseek load --context <files>[/bold] to add files")
            console.print("   Or use [bold]deepseek load-snapshot <path>[/bold] to load a snapshot")

        console.print("\n[dim]" + "="*60 + "[/dim]")
        console.print("[bold]Commands:[/bold]")
        console.print("  Standard Chat:")
        console.print("    /clear     - Clear conversation")
        console.print("    /exit      - Exit")
        console.print("    /help      - Show this help")
        console.print("    /save      - Save conversation")
        console.print("    /context   - Show/manage context")
        console.print("    /files     - List files in context")
        console.print("    /focus <f> - Set focus file")
        console.print("    /load <f>  - Load additional files")
        console.print("    /clearctx  - Clear all context")
        console.print("    /snapshot  - Show snapshot info")

        if self.engine_available:
            console.print("\n  Architectural Engine:")
            console.print("    /architect <req> - Start architectural reasoning")
            console.print("    /architect-init  - Initialize/reinitialize engine")
            console.print("    /session <cmd>   - Manage implementation sessions")
            console.print("    /learnings <cmd> - Query and manage learnings")
            console.print("    /validate <cmd>  - Run validation")
            console.print("    /engine-status   - Show engine status")

        console.print("[dim]" + "="*60 + "[/dim]\n")

        # Load conversation history from context manager
        self.messages = self.context_manager.conversation_history.copy()

        while self.conversation_active:
            try:
                user_input = await self._get_user_input()

                if user_input.startswith('/'):
                    await self._handle_command(user_input)
                    continue

                if not user_input.strip():
                    continue

                # Add user message to history
                self.context_manager.add_to_history("user", user_input)
                self.messages.append({"role": "user", "content": user_input})

                # Build prompt with context - NOW INCLUDES ARCHITECTURAL CONTEXT
                messages_with_context = self._build_prompt_with_architecture(user_input)

                # Show context info if files are loaded
                if self.context_manager.code_context.files:
                    self._show_context_usage()

                # Get and stream response
                console.print("\n[bold cyan]🤖 Assistant:[/bold cyan] ", end="", flush=True)
                full_response = ""

                async for chunk in self.api_client.chat_completion(messages_with_context):
                    console.print(chunk, end="", flush=True)
                    full_response += chunk

                console.print("\n")  # New line after response

                # Add assistant response to history
                self.context_manager.add_to_history("assistant", full_response)
                self.messages.append({"role": "assistant", "content": full_response})

                # Save updated context
                self._save_context()

            except KeyboardInterrupt:
                console.print("\n\n[bold]Exiting...[/bold]")
                break
            except EOFError:
                console.print("\n\n[bold]Exiting...[/bold]")
                break
            except Exception as e:
                console.print(f"\n[red]⚠️  Error: {e}[/red]")
                continue

        # Cleanup
        if self.engine_integration:
            try:
                await self.engine_integration.cleanup()
            except:
                pass

    def _build_prompt_with_architecture(self, user_message: str) -> List[Dict[str, str]]:
        """Build a prompt with architectural context if available."""
        messages = []

        # Check if we have snapshot metadata with architectural context
        has_snapshot_context = (
                hasattr(self.context_manager, 'snapshot_metadata') and
                self.context_manager.snapshot_metadata and
                self.context_manager.snapshot_metadata.get('system_context')
        )

        if has_snapshot_context:
            # Use architectural context from snapshot
            system_context = self.context_manager.snapshot_metadata['system_context']

            # Add architectural context with file context if available
            if self.context_manager.code_context.files:
                system_prompt = f"""You are a code assistant with deep understanding of this codebase's architecture.

{system_context}

You have access to the following files from this codebase:"""

                for filename, content in self.context_manager.code_context.files.items():
                    system_prompt += f"\n\n--- File: {filename} ---"

                    # Truncate if too long
                    if len(content) > 5000:
                        content = content[:2500] + "\n... [truncated] ...\n" + content[-2500:]

                    system_prompt += f"\n{content}"

                if self.context_manager.code_context.current_file:
                    system_prompt += f"\n\nCurrently focused on: {self.context_manager.code_context.current_file}"
            else:
                # Just architectural context without files
                system_prompt = f"""You are a code assistant with deep understanding of this codebase's architecture.

{system_context}"""

            messages.append({"role": "system", "content": system_prompt})
        elif self.context_manager.code_context.files:
            # Use regular file context without architectural context
            system_msg = self.context_manager._create_system_message()
            messages.append({"role": "system", "content": system_msg})
        else:
            # No context at all - just a basic assistant
            messages.append({"role": "system", "content": "You are a helpful code assistant."})

        # Add conversation history
        for msg in self.context_manager.conversation_history[-10:]:  # Last 10 messages
            messages.append({"role": msg['role'], "content": msg['content']})

        # Add current user message
        messages.append({"role": "user", "content": user_message})

        return messages

    def _show_context_status(self):
        """Show current context status with snapshot awareness."""
        if not self.context_manager.code_context.files:
            return

        file_count = len(self.context_manager.code_context.files)
        total_chars = sum(len(c) for c in self.context_manager.code_context.files.values())
        estimated_tokens = total_chars // 4

        # Check if we have snapshot context
        has_snapshot_context = (
                hasattr(self.context_manager, 'snapshot_metadata') and
                self.context_manager.snapshot_metadata
        )

        if has_snapshot_context:
            snapshot_name = self.context_manager.snapshot_metadata.get('snapshot_name', 'unknown')
            snapshot_dir = self.context_manager.snapshot_metadata.get('snapshot_dir', 'unknown')

            panel_content = f"[bold]📦 Snapshot:[/bold] {snapshot_name}\n"
            panel_content += f"[bold]📁 Files:[/bold] {file_count} file(s)\n"
            panel_content += f"[bold]📊 Size:[/bold] ~{estimated_tokens:,} tokens\n"
            panel_content += f"[bold]🔍 Focus:[/bold] {self.context_manager.code_context.current_file or 'None'}"

            console.print(Panel.fit(
                panel_content,
                title="Architectural Context",
                border_style="cyan"
            ))

            # Show architectural context preview if available
            if self.context_manager.snapshot_metadata.get('system_context'):
                arch_context = self.context_manager.snapshot_metadata['system_context']
                preview = arch_context[:200] + ("..." if len(arch_context) > 200 else "")
                console.print(f"[dim]🏗️  Architecture: {preview}[/dim]")
        else:
            console.print(Panel.fit(
                f"[bold]📁 Context:[/bold] {file_count} file(s)\n"
                f"[bold]📊 Size:[/bold] ~{estimated_tokens:,} tokens\n"
                f"[bold]🔍 Focus:[/bold] {self.context_manager.code_context.current_file or 'None'}",
                title="File Context",
                border_style="cyan"
            ))

    def _show_context_usage(self):
        """Show context usage information."""
        if not self.context_manager.code_context.files:
            return

        total_chars = sum(len(c) for c in self.context_manager.code_context.files.values())
        estimated_tokens = total_chars // 4
        max_tokens = self.config.get('app', {}).get('context_window', 128000)

        usage_percent = min(100, int((estimated_tokens / max_tokens) * 100))

        # Create a simple progress bar
        bar_length = 20
        filled = int(bar_length * usage_percent / 100)
        bar = "█" * filled + "░" * (bar_length - filled)

        console.print(f"[dim]📊 Context usage: [{bar}] {usage_percent}% ({estimated_tokens:,}/{max_tokens:,} tokens)[/dim]")

    async def _get_user_input(self) -> str:
        """Get input from user with rich formatting."""
        loop = asyncio.get_event_loop()
        try:
            # Show prompt with context indicator
            prompt = "[bold cyan]💬 You:[/bold cyan] "

            # Add engine status if available
            if self.engine_available and self.engine_integration and self.engine_integration.is_available():
                prompt = "[bold cyan]💬 You (🏗️):[/bold cyan] "
            elif self.context_manager.code_context.files:
                file_count = len(self.context_manager.code_context.files)
                prompt = f"[bold cyan]💬 You ({file_count}📁):[/bold cyan] "

            # Use asyncio for async input
            user_input = await loop.run_in_executor(None, lambda: console.input(prompt).strip())
            return user_input
        except (EOFError, KeyboardInterrupt):
            return "/exit"
        except Exception:
            return ""

    async def _handle_command(self, command: str):
        """Handle slash commands."""
        parts = command.strip().split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        # Standard chat commands
        if cmd == "/clear":
            await self._handle_clear_command()
        elif cmd == "/exit":
            await self._handle_exit_command()
        elif cmd == "/help":
            await self._handle_help_command()
        elif cmd == "/save":
            await self._handle_save_command()
        elif cmd == "/context":
            await self._handle_context_command(args)
        elif cmd == "/files":
            await self._handle_files_command(args)
        elif cmd == "/focus":
            await self._handle_focus_command(args)
        elif cmd == "/load":
            await self._handle_load_command(args)
        elif cmd == "/clearctx":
            await self._handle_clearctx_command()
        elif cmd == "/snapshot":
            await self._handle_snapshot_command(args)

        # Engine integration commands
        elif cmd == "/architect":
            await self._handle_architect_command(args)
        elif cmd == "/architect-init":
            await self._handle_architect_init_command()
        elif cmd == "/session":
            await self._handle_session_command(args)
        elif cmd == "/learnings":
            await self._handle_learnings_command(args)
        elif cmd == "/validate":
            await self._handle_validate_command(args)
        elif cmd == "/engine-status":
            await self._handle_engine_status_command()
        else:
            console.print(f"[red]❓ Unknown command: {cmd}[/red]")
            console.print("Type /help for available commands")

    def _show_help(self):
        """Show help information."""
        help_table = Table(box=ROUNDED, show_header=False)
        help_table.add_column("Command", style="cyan")
        help_table.add_column("Description", style="white")

        # Standard commands
        help_table.add_row("/clear", "Clear conversation history")
        help_table.add_row("/exit", "Exit the program")
        help_table.add_row("/help", "Show this help message")
        help_table.add_row("/save", "Save conversation to file")
        help_table.add_row("/context", "Show/manage context [show|list|clear]")
        help_table.add_row("/files", "List files in context [<file> to preview]")
        help_table.add_row("/focus <file>", "Set focus file")
        help_table.add_row("/load <files>", "Load additional files")
        help_table.add_row("/clearctx", "Clear all context (files & conversation)")
        help_table.add_row("/snapshot", "Show snapshot information")

        # Engine commands (if available)
        if self.engine_available:
            help_table.add_row("", "")
            help_table.add_row("[bold]Architectural Engine:[/bold]", "")
            help_table.add_row("/architect <req>", "Start architectural reasoning")
            help_table.add_row("/architect-init", "Initialize/reinitialize engine")
            help_table.add_row("/session <cmd>", "Manage implementation sessions")
            help_table.add_row("/learnings <cmd>", "Query and manage learnings")
            help_table.add_row("/validate <cmd>", "Run validation")
            help_table.add_row("/engine-status", "Show engine status")

        console.print("\n[bold]Available Commands:[/bold]")
        console.print(help_table)
        console.print()

    # ============================================================================
    # STANDARD CHAT COMMAND HANDLERS (preserved from original)
    # ============================================================================

    async def _handle_clear_command(self):
        """Clear conversation."""
        self.messages = []
        self.context_manager.conversation_history = []
        console.print("[green]🗑️  Conversation cleared[/green]")

    async def _handle_exit_command(self):
        """Exit the program."""
        self.conversation_active = False
        console.print("[bold]👋 Goodbye![/bold]")

    async def _handle_help_command(self):
        """Show help."""
        self._show_help()

    async def _handle_save_command(self):
        """Save conversation to file."""
        await self._save_conversation()

    async def _handle_context_command(self, args: List[str]):
        """Handle context management commands."""
        if not args:
            # Show context summary
            if not self.context_manager.code_context.files:
                console.print("[yellow]⚠️  No context loaded[/yellow]")
                return

            table = Table(title="Current Context", box=ROUNDED)
            table.add_column("File", style="cyan")
            table.add_column("Size", style="yellow")
            table.add_column("Lines", justify="right")
            table.add_column("Status", style="green")

            for filename, content in self.context_manager.code_context.files.items():
                lines = len(content.split('\n'))
                size = f"{len(content):,}"

                if self.context_manager.code_context.current_file == filename:
                    status = "📌 Focus"
                else:
                    status = "✓ Loaded"

                table.add_row(filename, size, str(lines), status)

            console.print(table)

            total_chars = sum(len(c) for c in self.context_manager.code_context.files.values())
            total_files = len(self.context_manager.code_context.files)
            console.print(f"\n📊 Total: {total_files} files, ~{total_chars // 4:,} tokens")

            if self.context_manager.code_context.current_file:
                console.print(f"🔍 Focus file: {self.context_manager.code_context.current_file}")

            # Show snapshot info if available
            if hasattr(self.context_manager, 'snapshot_metadata') and self.context_manager.snapshot_metadata:
                snapshot_name = self.context_manager.snapshot_metadata.get('snapshot_name', 'unknown')
                console.print(f"\n[cyan]📦 Snapshot Context: {snapshot_name}[/cyan]")

        elif args[0] == "clear":
            self.context_manager.code_context.files.clear()
            self.context_manager.code_context.current_file = None
            # Also clear snapshot metadata
            if hasattr(self.context_manager, 'snapshot_metadata'):
                self.context_manager.snapshot_metadata = None
            self._save_context()
            console.print("[green]✅ Context cleared[/green]")

        elif args[0] == "list":
            files = list(self.context_manager.code_context.files.keys())
            if files:
                console.print("[bold]Files in context:[/bold]")
                for i, f in enumerate(files, 1):
                    console.print(f"  {i}. {f}")
            else:
                console.print("[yellow]No files in context[/yellow]")

        else:
            console.print("[red]❓ Unknown context command[/red]")
            console.print("Usage: /context [show|list|clear]")

    async def _handle_files_command(self, args: List[str]):
        """Handle file listing and preview."""
        if not self.context_manager.code_context.files:
            console.print("[yellow]⚠️  No files in context[/yellow]")
            return

        if not args:
            # List all files
            files = list(self.context_manager.code_context.files.keys())
            console.print("[bold]Files in context:[/bold]")
            for i, f in enumerate(files, 1):
                size = len(self.context_manager.code_context.files[f])
                lines = len(self.context_manager.code_context.files[f].split('\n'))
                console.print(f"  {i}. {f} ({size:,} chars, {lines} lines)")
        else:
            # Show specific file
            filename = ' '.join(args)
            if filename in self.context_manager.code_context.files:
                content = self.context_manager.code_context.files[filename]

                # Determine language for syntax highlighting
                if filename.endswith('.py'):
                    lang = "python"
                elif filename.endswith('.js'):
                    lang = "javascript"
                elif filename.endswith('.ts'):
                    lang = "typescript"
                elif filename.endswith('.java'):
                    lang = "java"
                elif filename.endswith('.go'):
                    lang = "go"
                elif filename.endswith('.rs'):
                    lang = "rust"
                elif filename.endswith('.cpp') or filename.endswith('.h'):
                    lang = "cpp"
                else:
                    lang = "text"

                console.print(f"\n[bold cyan]📄 {filename}[/bold cyan]")
                console.print(f"Size: {len(content):,} characters, {len(content.split('\n'))} lines")
                console.print(Syntax(content, lang, theme="monokai", line_numbers=True))
            else:
                console.print(f"[red]❌ File not found in context: {filename}[/red]")

    async def _handle_focus_command(self, args: List[str]):
        """Set focus file."""
        if not args:
            if self.context_manager.code_context.current_file:
                console.print(f"[bold]Current focus:[/bold] {self.context_manager.code_context.current_file}")
            else:
                console.print("[yellow]No focus file set[/yellow]")
            return

        filename = ' '.join(args)
        if filename in self.context_manager.code_context.files:
            self.context_manager.code_context.current_file = filename
            self._save_context()
            console.print(f"[green]✅ Focus set to: {filename}[/green]")
        else:
            console.print(f"[red]❌ File not in context: {filename}[/red]")
            console.print("Use /load command to add it first")

    async def _handle_load_command(self, args: List[str]):
        """Load additional files."""
        if not args:
            console.print("[red]❌ No files specified[/red]")
            console.print("Usage: /load <file1> [file2 ...]")
            return

        console.print(f"[yellow]📂 Loading {len(args)} file(s)...[/yellow]")

        loader = FileLoader()
        loaded = loader.load_multiple_files(args)

        for filename, content in loaded.items():
            self.context_manager.add_file(filename, content)
            console.print(f"  [green]✓[/green] {filename} ({len(content):,} chars)")

        if loaded:
            self._save_context()
            console.print(f"[green]✅ {len(loaded)} file(s) added to context[/green]")
        else:
            console.print("[red]❌ No files could be loaded[/red]")

    async def _handle_clearctx_command(self):
        """Clear all context."""
        self.context_manager.code_context.files.clear()
        self.context_manager.code_context.current_file = None
        self.context_manager.conversation_history = []
        self.messages = []
        # Clear snapshot metadata too
        if hasattr(self.context_manager, 'snapshot_metadata'):
            self.context_manager.snapshot_metadata = None
        self._save_context()
        console.print("[green]✅ All context cleared (files & conversation)[/green]")

    async def _handle_snapshot_command(self, args: List[str]):
        """Handle snapshot information command."""
        if not hasattr(self.context_manager, 'snapshot_metadata') or not self.context_manager.snapshot_metadata:
            console.print("[yellow]⚠️  No snapshot context loaded[/yellow]")
            console.print("   Use: deepseek load-snapshot <snapshot_path>")
            return

        metadata = self.context_manager.snapshot_metadata

        console.print("[bold cyan]📦 Snapshot Information[/bold cyan]")
        console.print(f"  Name: {metadata.get('snapshot_name', 'unknown')}")
        console.print(f"  Directory: {metadata.get('snapshot_dir', 'unknown')}")

        artifacts = metadata.get('artifacts_loaded', [])
        if artifacts:
            console.print(f"  Artifacts: {', '.join(artifacts)}")

        key_files = metadata.get('key_files_loaded', [])
        if key_files:
            console.print(f"  Key files loaded: {len(key_files)}")
            for i, f in enumerate(key_files[:5], 1):
                console.print(f"    {i}. {f}")
            if len(key_files) > 5:
                console.print(f"    ... and {len(key_files) - 5} more")

        # Show architecture summary preview
        arch_summary = metadata.get('architecture_summary', {})
        if arch_summary and isinstance(arch_summary, dict):
            arch_context = arch_summary.get('architecture_context', {})
            if arch_context:
                overview = arch_context.get('overview', '').strip()
                if overview:
                    console.print(f"\n[bold]🏗️  Architecture Overview:[/bold]")
                    console.print(overview[:400] + ("..." if len(overview) > 400 else ""))

    async def _save_conversation(self):
        """Save conversation to file."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"conversation_{timestamp}.md"

            # Ensure conversations directory exists
            conversations_dir = Path("storage/conversations")
            conversations_dir.mkdir(parents=True, exist_ok=True)

            filepath = conversations_dir / filename

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("# DeepSeek Conversation\n\n")
                f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                # Save context info
                if hasattr(self.context_manager, 'snapshot_metadata') and self.context_manager.snapshot_metadata:
                    snapshot_name = self.context_manager.snapshot_metadata.get('snapshot_name', 'unknown')
                    f.write(f"## Snapshot Context: {snapshot_name}\n\n")

                    arch_summary = self.context_manager.snapshot_metadata.get('architecture_summary', {})
                    if arch_summary and isinstance(arch_summary, dict):
                        arch_context = arch_summary.get('architecture_context', {})
                        if arch_context:
                            overview = arch_context.get('overview', '').strip()
                            if overview:
                                f.write(f"### Architecture Overview\n\n{overview}\n\n")

                if self.context_manager.code_context.files:
                    f.write("## Context Files\n\n")
                    for filename in self.context_manager.code_context.files.keys():
                        f.write(f"- `{filename}`\n")
                    f.write("\n")

                # Save conversation
                for i, msg in enumerate(self.messages):
                    role = "User" if msg["role"] == "user" else "Assistant"
                    f.write(f"## {role} (Message {i+1})\n\n")
                    f.write(f"{msg['content']}\n\n")

            console.print(f"[green]💾 Conversation saved to {filepath}[/green]")
        except Exception as e:
            console.print(f"[red]❌ Failed to save: {e}[/red]")

    def _save_context(self):
        """Save current context to file."""
        try:
            storage_dir = Path("storage")
            storage_dir.mkdir(exist_ok=True)

            ctx_file = storage_dir / "current_context.json"
            self.context_manager.save_context(str(ctx_file))
        except Exception as e:
            console.print(f"[yellow]⚠️  Could not save context: {e}[/yellow]")

    # ============================================================================
    # ENGINE INTEGRATION COMMAND HANDLERS (new)
    # ============================================================================

    async def _handle_architect_command(self, args: List[str]):
        """Start architectural reasoning session."""
        if not args:
            console.print("[red]❌ Missing requirements[/red]")
            console.print("Usage: /architect <requirements>")
            console.print("Example: /architect \"Add authentication module to the API\"")
            return

        if not self.engine_available or not self.engine_integration:
            console.print("[yellow]⚠️  Engine not available[/yellow]")
            console.print("Try: /architect-init to initialize the engine")
            return

        requirements = ' '.join(args)
        console.print(f"[cyan]🏗️  Starting architectural reasoning for:[/cyan] {requirements}")

        try:
            response = await self.engine_integration.start_architectural_dialogue(requirements)

            # Format and display response
            if response.get('status') == 'error':
                console.print(f"[red]❌ {response.get('message', 'Unknown error')}[/red]")
                if response.get('suggestion'):
                    console.print(f"[yellow]💡 {response.get('suggestion')}[/yellow]")
            else:
                console.print(f"[green]✅ {response.get('message', 'Success')}[/green]")

                # Show details if available
                if 'details' in response:
                    details = response['details']
                    if isinstance(details, dict):
                        for key, value in details.items():
                            if value:
                                console.print(f"[dim]   {key}: {value}[/dim]")

                # Show actions if available
                if 'actions' in response:
                    console.print("\n[bold]Available actions:[/bold]")
                    for action in response['actions'][:3]:
                        console.print(f"  {action['command']} - {action['description']}")

        except Exception as e:
            console.print(f"[red]❌ Architectural reasoning failed: {e}[/red]")

    async def _handle_architect_init_command(self):
        """Initialize or reinitialize the engine."""
        console.print("[cyan]🔄 Initializing architectural engine...[/cyan]")

        if self.engine_integration:
            try:
                await self.engine_integration.cleanup()
            except:
                pass
            self.engine_integration = None

        success = await self.initialize_engine()

        if success:
            console.print("[green]✅ Engine initialized successfully[/green]")
        else:
            console.print("[red]❌ Engine initialization failed[/red]")

    async def _handle_session_command(self, args: List[str]):
        """Manage implementation sessions."""
        if not self.engine_available or not self.engine_integration:
            console.print("[yellow]⚠️  Engine not available[/yellow]")
            console.print("Try: /architect-init to initialize the engine")
            return

        if not args:
            # Show session help
            console.print("[bold]Session Commands:[/bold]")
            console.print("  /session plan          - Create implementation plan for current session")
            console.print("  /session execute       - Execute current session")
            console.print("  /session summary [id]  - Show session summary")
            console.print("  /session list          - List all sessions")
            console.print("  /session chunks list   - List work chunks for current session")
            console.print("  /session validate      - Validate current session")
            console.print("  /session iterate       - Create iteration plan based on feedback")
            return

        command = args[0]

        try:
            response = await self.engine_integration.handle_session_command(command, args[1:])

            # Format and display response
            if response.get('status') == 'error':
                console.print(f"[red]❌ {response.get('message', 'Unknown error')}[/red]")
                if response.get('suggestion'):
                    console.print(f"[yellow]💡 {response.get('suggestion')}[/yellow]")
            else:
                console.print(f"[green]✅ {response.get('message', 'Success')}[/green]")

                # Show details based on format
                if 'format' in response:
                    if response['format'] == 'table':
                        # Simple table formatting
                        details = response.get('details', {})
                        if isinstance(details, dict):
                            for key, value in details.items():
                                if value:
                                    console.print(f"[dim]   {key}: {value}[/dim]")
                    elif response['format'] == 'sessions_table':
                        sessions = response.get('details', [])
                        if sessions:
                            console.print("\n[bold]Sessions:[/bold]")
                            for session in sessions[:5]:
                                console.print(f"  • {session.get('session_id', 'Unknown')} - {session.get('status', 'unknown')}")
                elif 'details' in response:
                    details = response['details']
                    if isinstance(details, dict):
                        for key, value in details.items():
                            if value:
                                console.print(f"[dim]   {key}: {value}[/dim]")

                # Show actions if available
                if 'actions' in response:
                    console.print("\n[bold]Available actions:[/bold]")
                    for action in response['actions'][:3]:
                        console.print(f"  {action['command']} - {action['description']}")

        except Exception as e:
            console.print(f"[red]❌ Session command failed: {e}[/red]")

    async def _handle_learnings_command(self, args: List[str]):
        """Query and manage learnings."""
        if not self.engine_available or not self.engine_integration:
            console.print("[yellow]⚠️  Engine not available[/yellow]")
            console.print("Try: /architect-init to initialize the engine")
            return

        if not args:
            # Show learnings help
            console.print("[bold]Learnings Commands:[/bold]")
            console.print("  /learnings search <query> - Search for relevant learnings")
            console.print("  /learnings stats         - Show learning system statistics")
            console.print("  /learnings capture       - Capture learnings from current session")
            console.print("  /learnings apply         - Apply learnings to current session")
            return

        command = args[0]

        try:
            response = await self.engine_integration.handle_learnings_command(command, args[1:])

            # Format and display response
            if response.get('status') == 'error':
                console.print(f"[red]❌ {response.get('message', 'Unknown error')}[/red]")
            else:
                console.print(f"[green]✅ {response.get('message', 'Success')}[/green]")

                # Show details based on format
                if 'format' in response:
                    if response['format'] == 'learnings_table':
                        learnings = response.get('details', [])
                        if learnings:
                            console.print("\n[bold]Learnings:[/bold]")
                            for learning in learnings[:3]:
                                title = learning.get('title', 'Unknown')
                                category = learning.get('category', 'unknown')
                                console.print(f"  • [{category}] {title}")
                    elif response['format'] == 'stats_table':
                        stats = response.get('details', {})
                        if stats:
                            console.print("\n[bold]Statistics:[/bold]")
                            for key, value in stats.items():
                                if key not in ['storage_path', 'by_category']:
                                    console.print(f"  {key}: {value}")

                # Show details if available
                elif 'details' in response:
                    details = response['details']
                    if isinstance(details, dict):
                        for key, value in details.items():
                            if value:
                                console.print(f"[dim]   {key}: {value}[/dim]")

        except Exception as e:
            console.print(f"[red]❌ Learnings command failed: {e}[/red]")

    async def _handle_validate_command(self, args: List[str]):
        """Run validation."""
        if not self.engine_available or not self.engine_integration:
            console.print("[yellow]⚠️  Engine not available[/yellow]")
            console.print("Try: /architect-init to initialize the engine")
            return

        if not args:
            console.print("[bold]Validation Commands:[/bold]")
            console.print("  /validate session <id> - Validate a session")
            console.print("  /validate quick       - Quick validation of current context")
            return

        try:
            response = await self.engine_integration.handle_validation_command(args)

            # Format and display response
            if response.get('status') == 'error':
                console.print(f"[red]❌ {response.get('message', 'Unknown error')}[/red]")
                if response.get('suggestion'):
                    console.print(f"[yellow]💡 {response.get('suggestion')}[/yellow]")
            else:
                console.print(f"[green]✅ {response.get('message', 'Success')}[/green]")

                # Show details
                if 'details' in response:
                    details = response['details']
                    if isinstance(details, dict):
                        for key, value in details.items():
                            if value:
                                console.print(f"[dim]   {key}: {value}[/dim]")

                # Show validation result if available
                if 'validation_result' in response:
                    result = response['validation_result']
                    status = result.get('overall_status', 'unknown')
                    confidence = result.get('confidence_score', 0)
                    issues = len(result.get('issues_found', []))
                    warnings = len(result.get('warnings', []))

                    console.print(f"\n[bold]Validation Details:[/bold]")
                    console.print(f"  Status: {status}")
                    console.print(f"  Confidence: {confidence:.1%}")
                    console.print(f"  Issues: {issues}")
                    console.print(f"  Warnings: {warnings}")

        except Exception as e:
            console.print(f"[red]❌ Validation command failed: {e}[/red]")

    async def _handle_engine_status_command(self):
        """Show engine status."""
        if not self.engine_integration:
            console.print("[yellow]⚠️  Engine integration not created[/yellow]")
            return

        try:
            status = self.engine_integration.get_engine_status()

            table = Table(title="Engine Status", box=ROUNDED, show_header=False)
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="yellow")

            table.add_row("Initialized", "✅ Yes" if status['initialized'] else "❌ No")
            table.add_row("Status", status['status'])
            table.add_row("Current Session", status['current_session'] or "None")
            table.add_row("Active Sessions", str(status['active_sessions']))
            table.add_row("Last Operation", status['last_operation'] or "None")
            table.add_row("Timestamp", status['timestamp'])

            console.print(table)

        except Exception as e:
            console.print(f"[red]❌ Failed to get engine status: {e}[/red]")


# ============================================================================
# MAIN ENTRY POINTS
# ============================================================================

async def main():
    """Main entry point for CLI."""
    try:
        from assistant.api.client import DeepSeekClient

        console.print("[bold cyan]Initializing DeepSeek client...[/bold cyan]")
        client = DeepSeekClient()

        # Test connection
        console.print("[bold green]Testing API connection...[/bold green]")
        if await client.test_connection():
            console.print("[green]✅ API connection successful![/green]")
        else:
            console.print("[red]❌ API connection failed[/red]")
            console.print("Please check your API key in .env file")
            return

        cli = ChatCLI(client)
        await cli.start()

        # Clean up
        await client.close()

    except ImportError as e:
        console.print(f"[red]❌ Import error: {e}[/red]")
        console.print("Make sure you're running from the project root directory")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]❌ Configuration error: {e}[/red]")
        console.print("\nPlease set your API key in .env file:")
        console.print("  DEEPSEEK_API_KEY=your_api_key_here")
        console.print("\nGet your API key from: https://platform.deepseek.com/api_keys")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]❌ Unexpected error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run():
    """Synchronous entry point for scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run()