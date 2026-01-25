# src/assistant/ui/chat_cli.py
"""
Chat CLI interface for DeepSeek Code Assistant.
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

    async def start(self):
        """Start the chat interface."""
        # Display welcome banner
        console.print(Panel.fit(
            "[bold cyan]🤖 DeepSeek Code Assistant[/bold cyan]",
            subtitle="Context-aware AI pair programmer"
        ))

        # Show context status
        if self.context_manager.code_context.files:
            self._show_context_status()
        else:
            console.print("[yellow]ℹ️  No file context loaded[/yellow]")
            console.print("   Use [bold]deepseek load --context <files>[/bold] to add files")

        console.print("\n[dim]" + "="*60 + "[/dim]")
        console.print("[bold]Commands:[/bold]")
        console.print("  /clear     - Clear conversation")
        console.print("  /exit      - Exit")
        console.print("  /help      - Show this help")
        console.print("  /save      - Save conversation")
        console.print("  /context   - Show/manage context")
        console.print("  /files     - List files in context")
        console.print("  /focus <f> - Set focus file")
        console.print("  /load <f>  - Load additional files")
        console.print("  /clearctx  - Clear all context")
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

                # Build prompt with context
                messages_with_context = self.context_manager.build_prompt(user_input)

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

    def _show_context_status(self):
        """Show current context status."""
        if not self.context_manager.code_context.files:
            return

        file_count = len(self.context_manager.code_context.files)
        total_chars = sum(len(c) for c in self.context_manager.code_context.files.values())
        estimated_tokens = total_chars // 4

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
            if self.context_manager.code_context.files:
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

        if cmd == "/clear":
            self.messages = []
            self.context_manager.conversation_history = []
            console.print("[green]🗑️  Conversation cleared[/green]")

        elif cmd == "/exit":
            self.conversation_active = False
            console.print("[bold]👋 Goodbye![/bold]")

        elif cmd == "/help":
            self._show_help()

        elif cmd == "/save":
            await self._save_conversation()

        elif cmd == "/context":
            await self._handle_context_command(args)

        elif cmd == "/files":
            await self._handle_files_command(args)

        elif cmd == "/focus":
            await self._handle_focus_command(args)

        elif cmd == "/load":
            await self._handle_load_command(args)

        elif cmd == "/clearctx":
            await self._handle_clear_context()

        else:
            console.print(f"[red]❓ Unknown command: {cmd}[/red]")
            console.print("Type /help for available commands")

    def _show_help(self):
        """Show help information."""
        help_table = Table(box=ROUNDED, show_header=False)
        help_table.add_column("Command", style="cyan")
        help_table.add_column("Description", style="white")

        help_table.add_row("/clear", "Clear conversation history")
        help_table.add_row("/exit", "Exit the program")
        help_table.add_row("/help", "Show this help message")
        help_table.add_row("/save", "Save conversation to file")
        help_table.add_row("/context", "Show/manage context [show|list|clear]")
        help_table.add_row("/files", "List files in context [<file> to preview]")
        help_table.add_row("/focus <file>", "Set focus file")
        help_table.add_row("/load <files>", "Load additional files")
        help_table.add_row("/clearctx", "Clear all context (files & conversation)")

        console.print("\n[bold]Available Commands:[/bold]")
        console.print(help_table)
        console.print()

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

        elif args[0] == "clear":
            self.context_manager.code_context.files.clear()
            self.context_manager.code_context.current_file = None
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
        loaded = await loader.load_multiple_files(args)

        for filename, content in loaded.items():
            self.context_manager.add_file(filename, content)
            console.print(f"  [green]✓[/green] {filename} ({len(content):,} chars)")

        if loaded:
            self._save_context()
            console.print(f"[green]✅ {len(loaded)} file(s) added to context[/green]")
        else:
            console.print("[red]❌ No files could be loaded[/red]")

    async def _handle_clear_context(self):
        """Clear all context."""
        self.context_manager.code_context.files.clear()
        self.context_manager.code_context.current_file = None
        self.context_manager.conversation_history = []
        self.messages = []
        self._save_context()
        console.print("[green]✅ All context cleared (files & conversation)[/green]")

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