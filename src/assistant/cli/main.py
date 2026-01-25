#!/usr/bin/env python3
"""
Main CLI entry point for DeepSeek Code Assistant.
"""
import asyncio
import sys
from pathlib import Path
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.box import ROUNDED
from rich.progress import Progress, SpinnerColumn, TextColumn

from assistant.api.client import DeepSeekClient
from assistant.ui.chat_cli import ChatCLI
from assistant.core.file_loader import FileLoader
from assistant.core.context_manager import ContextManager

console = Console()

def check_config():
    """Check if configuration is properly set up."""
    from dotenv import load_dotenv
    import os

    load_dotenv()

    # Check .env file exists
    env_path = Path(".env")
    if not env_path.exists():
        console.print("[yellow]⚠️  .env file not found[/yellow]")
        console.print("Create one with: echo 'DEEPSEEK_API_KEY=your_key' > .env")
        return False

    # Check API key
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        console.print("[red]❌ DEEPSEEK_API_KEY not configured[/red]")
        console.print("Get your API key from: https://platform.deepseek.com/api_keys")
        return False

    return True

@click.group()
@click.version_option(version="0.1.0")
def cli():
    """DeepSeek Code Assistant - Your AI pair programmer."""
    pass

@cli.command()
@click.option('--config', '-c', default="config.yaml", help="Path to config file")
def chat(config):
    """Start interactive chat session."""
    if not check_config():
        sys.exit(1)

    asyncio.run(_chat_async(config))

async def _chat_async(config_path: str):
    """Async wrapper for chat command."""
    try:
        console.print(Panel.fit(
            "[bold cyan]🤖 DeepSeek Code Assistant[/bold cyan]",
            subtitle="Start chatting with /help"
        ))

        client = DeepSeekClient(config_path)

        # Test connection first
        with console.status("[bold green]Testing API connection..."):
            if not await client.test_connection():
                console.print("[red]❌ API connection failed[/red]")
                console.print("Please check your API key and network connection")
                await client.close()
                return

        console.print("[green]✅ API connection successful![/green]\n")

        cli_interface = ChatCLI(client)
        await cli_interface.start()
        await client.close()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        sys.exit(1)

@cli.command()
@click.option('--config', '-c', default="config.yaml", help="Path to config file")
def test(config):
    """Test API connection and configuration."""
    # This is a synchronous function, need to run async code
    asyncio.run(_test_async(config))

async def _test_async(config_path: str):
    """Async wrapper for test command."""
    try:
        client = DeepSeekClient(config_path)

        table = Table(title="Configuration Test")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details")

        # Test API key
        if client.api_key and client.api_key != "your_api_key_here":
            table.add_row("API Key", "✅", "Configured")
        else:
            table.add_row("API Key", "❌", "Missing or default")

        # Test API connection
        try:
            success = await client.test_connection()
            if success:
                table.add_row("API Connection", "✅", "Connected to DeepSeek API")
            else:
                table.add_row("API Connection", "❌", "Connection failed")
        except Exception as e:
            table.add_row("API Connection", "❌", str(e))

        console.print(table)
        await client.close()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        sys.exit(1)

@cli.command()
@click.option('--show-key', is_flag=True, help="Show full API key (be careful!)")
def config(show_key):
    """Show current configuration."""
    import yaml
    from dotenv import load_dotenv
    import os

    load_dotenv()

    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="yellow")

    # Environment variables
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        if show_key:
            table.add_row("DEEPSEEK_API_KEY", api_key)
        else:
            masked = "•" * (len(api_key) - 4) + api_key[-4:]
            table.add_row("DEEPSEEK_API_KEY", masked)
    else:
        table.add_row("DEEPSEEK_API_KEY", "[red]NOT SET[/red]")

    # Config file
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
            for section, settings in config_data.items():
                if isinstance(settings, dict):
                    for key, value in settings.items():
                        table.add_row(f"{section}.{key}", str(value))
                else:
                    table.add_row(section, str(settings))
    else:
        table.add_row("config.yaml", "[red]NOT FOUND[/red]")

    console.print(table)

@cli.command()
@click.argument('files', nargs=-1, type=click.Path(exists=True))
@click.option('--context', '-c', is_flag=True, help="Include file context in chat")
@click.option('--summary', '-s', is_flag=True, help="Show summary of loaded files")
def load(files, context, summary):
    """Load files into context for code-aware assistance."""
    if not files:
        console.print("[red]❌ No files specified[/red]")
        console.print("Usage: deepseek load <file1> [file2 ...]")
        console.print("       deepseek load --context <files> (to use in chat)")
        return

    # Initialize context manager
    ctx_manager = ContextManager()

    # Check for existing context
    ctx_file = Path("storage/current_context.json")
    if ctx_file.exists():
        try:
            ctx_manager.load_context(str(ctx_file))
            console.print("[yellow]📂 Merging with existing context[/yellow]")
        except Exception as e:
            console.print(f"[yellow]⚠️  Could not load existing context: {e}[/yellow]")

    # Load files
    console.print(f"[yellow]📂 Loading {len(files)} file(s)...[/yellow]")

    async def _load_files():
        loader = FileLoader()
        loaded = await loader.load_multiple_files(files)

        loaded_count = 0
        total_chars = 0

        for filename, content in loaded.items():
            ctx_manager.add_file(filename, content)
            loaded_count += 1
            total_chars += len(content)

            if summary:
                # Show file preview
                lines = content.split('\n')
                preview = '\n'.join(lines[:10])
                if len(lines) > 10:
                    preview += f"\n... [and {len(lines) - 10} more lines]"

                console.print(f"\n[bold cyan]📄 {filename}[/bold cyan]")
                console.print(f"   Size: {len(content):,} chars, {len(lines)} lines")
                console.print(Syntax(preview, "python", theme="monokai", line_numbers=True))
            else:
                console.print(f"  [green]✓[/green] {filename} ({len(content):,} chars)")

        if loaded_count > 0:
            # Save context if requested or if we're in context mode
            if context or summary:
                storage_dir = Path("storage")
                storage_dir.mkdir(exist_ok=True)
                ctx_manager.save_context(str(ctx_file))

                if context:
                    console.print(f"\n[green]✅ {loaded_count} files loaded with context[/green]")
                    console.print(f"   Context saved to: {ctx_file}")
                    console.print("\n[bold]Now you can use:[/bold]")
                    console.print("   deepseek chat      - Interactive chat with file context")
                    console.print("   deepseek ask <q>   - Direct question about loaded files")
                else:
                    console.print(f"\n[green]✅ {loaded_count} files analyzed[/green]")
                    console.print(f"   Total: {total_chars:,} characters across {loaded_count} files")
            else:
                console.print(f"\n[green]✅ {loaded_count} files loaded into memory[/green]")
                console.print(f"   Total: {total_chars:,} characters")
        else:
            console.print("[red]❌ No files could be loaded[/red]")
            console.print("   Check file permissions and encoding")

    asyncio.run(_load_files())

@cli.command()
@click.argument('query')
@click.option('--file', '-f', help="File to focus on")
@click.option('--no-context', is_flag=True, help="Ask without file context")
def ask(query, file, no_context):
    """Ask a question about loaded files."""
    if no_context:
        # Just ask without file context
        console.print(f"[yellow]🤔 Asking: {query}[/yellow]")

        async def _ask_simple():
            client = DeepSeekClient()
            console.print("\n🤖 Assistant: ", end="", flush=True)

            async for chunk in client.chat_completion([{"role": "user", "content": query}]):
                print(chunk, end="", flush=True)

            print("\n")
            await client.close()

        asyncio.run(_ask_simple())
        return

    # Check for context
    ctx_file = Path("storage/current_context.json")
    if not ctx_file.exists():
        console.print("[red]❌ No context loaded.[/red]")
        console.print("   First load files with: deepseek load --context <files>")
        console.print("   Or use --no-context flag to ask without file context")
        return

    console.print(f"[yellow]🤔 Asking about: {query}[/yellow]")

    async def _ask_with_context():
        # Load context
        ctx_manager = ContextManager()
        try:
            ctx_manager.load_context(str(ctx_file))
        except Exception as e:
            console.print(f"[red]❌ Could not load context: {e}[/red]")
            return

        # Show context info
        if ctx_manager.code_context.files:
            file_list = list(ctx_manager.code_context.files.keys())
            console.print(f"   📂 Context: {len(file_list)} file(s)")
            for f in file_list[:3]:
                console.print(f"      • {f}")
            if len(file_list) > 3:
                console.print(f"      • ... and {len(file_list) - 3} more")

        # Update current file if specified
        if file:
            if file in ctx_manager.code_context.files:
                ctx_manager.set_current_file(file)
                console.print(f"   🔍 Focusing on: {file}")
            else:
                console.print(f"[yellow]⚠️  File not in context: {file}[/yellow]")

        # Build prompt with context
        messages = ctx_manager.build_prompt(query)

        # Show token estimate
        total_chars = sum(len(c) for c in ctx_manager.code_context.files.values())
        estimated_tokens = total_chars // 4  # Rough estimate
        console.print(f"   📊 Estimated context: ~{estimated_tokens:,} tokens")

        # Initialize client and get response
        client = DeepSeekClient()

        # Add to conversation history
        ctx_manager.add_to_history("user", query)

        console.print("\n🤖 Assistant: ", end="", flush=True)
        full_response = ""

        try:
            async for chunk in client.chat_completion(messages):
                print(chunk, end="", flush=True)
                full_response += chunk

            print("\n")

            # Add to conversation history
            ctx_manager.add_to_history("assistant", full_response)

            # Save updated context
            ctx_manager.save_context(str(ctx_file))

        except Exception as e:
            console.print(f"\n[red]❌ Error: {e}[/red]")

        await client.close()

    asyncio.run(_ask_with_context())

@cli.command(name="context")
@click.option('--clear', is_flag=True, help="Clear current context")
@click.option('--list', 'list_files', is_flag=True, help="List files in context")
@click.option('--show', help="Show contents of specific file")
def context_cmd(clear, list_files, show):
    """Manage file context."""
    ctx_file = Path("storage/current_context.json")

    if clear:
        if ctx_file.exists():
            ctx_file.unlink()
            console.print("[green]✅ Context cleared[/green]")
        else:
            console.print("[yellow]⚠️  No context to clear[/yellow]")
        return

    if show:
        if not ctx_file.exists():
            console.print("[red]❌ No context loaded[/red]")
            return

        ctx_manager = ContextManager()
        try:
            ctx_manager.load_context(str(ctx_file))
        except Exception as e:
            console.print(f"[red]❌ Could not load context: {e}[/red]")
            return

        if show in ctx_manager.code_context.files:
            content = ctx_manager.code_context.files[show]

            # Determine language for syntax highlighting
            lang = "python" if show.endswith(".py") else "text"

            console.print(f"\n[bold cyan]📄 {show}[/bold cyan]")
            console.print(f"   Size: {len(content):,} characters")
            console.print(Syntax(content, lang, theme="monokai", line_numbers=True))
        else:
            console.print(f"[red]❌ File not in context: {show}[/red]")
            console.print(f"   Available files: {list(ctx_manager.code_context.files.keys())}")
        return

    if list_files or not (clear or show):
        if not ctx_file.exists():
            console.print("[yellow]⚠️  No context loaded[/yellow]")
            console.print("\nTo load files with context:")
            console.print("   deepseek load --context <files>")
            return

        ctx_manager = ContextManager()
        try:
            ctx_manager.load_context(str(ctx_file))
        except Exception as e:
            console.print(f"[red]❌ Could not load context: {e}[/red]")
            return

        if ctx_manager.code_context.files:
            table = Table(title="Current Context", box=ROUNDED)
            table.add_column("File", style="cyan")
            table.add_column("Size", style="yellow")
            table.add_column("Lines", justify="right")
            table.add_column("Status", style="green")

            for filename, content in ctx_manager.code_context.files.items():
                lines = len(content.split('\n'))
                size = f"{len(content):,}"

                if ctx_manager.code_context.current_file == filename:
                    status = "📌 Focus"
                else:
                    status = "✓ Loaded"

                table.add_row(filename, size, str(lines), status)

            console.print(table)

            total_chars = sum(len(c) for c in ctx_manager.code_context.files.values())
            total_files = len(ctx_manager.code_context.files)
            console.print(f"\n📊 Total: {total_files} files, ~{total_chars // 4:,} tokens")

            if ctx_manager.code_context.current_file:
                console.print(f"🔍 Focus file: {ctx_manager.code_context.current_file}")

            console.print("\n[bold]Commands:[/bold]")
            console.print("   deepseek context --clear    - Clear context")
            console.print("   deepseek context --show <f> - Show file contents")
            console.print("   deepseek chat               - Start chat with context")
            console.print("   deepseek ask <query>        - Ask about context")
        else:
            console.print("[yellow]⚠️  Context is empty[/yellow]")
        return

@cli.command()
@click.argument('files', nargs=-1, type=click.Path(exists=True))
def analyze(files):
    """Analyze code files with enhanced context (Phase 2)."""
    if not files:
        console.print("[yellow]📂 Analyzing current directory...[/yellow]")
        files = [str(f) for f in Path(".").glob("*.py")]
        if not files:
            console.print("[yellow]⚠️  No Python files found[/yellow]")
            return

    console.print(f"[bold cyan]🔍 Analyzing {len(files)} file(s)[/bold cyan]")

    async def _analyze_files():
        loader = FileLoader()
        loaded = await loader.load_multiple_files(files)

        # Create analysis table
        table = Table(title="File Analysis", box=ROUNDED)
        table.add_column("File", style="cyan")
        table.add_column("Size", style="yellow")
        table.add_column("Lines", justify="right")
        table.add_column("Language", style="magenta")

        total_lines = 0
        total_chars = 0

        for filename, content in loaded.items():
            lines = len(content.split('\n'))
            chars = len(content)

            # Determine language
            if filename.endswith('.py'):
                lang = 'Python'
            elif filename.endswith('.js') or filename.endswith('.ts'):
                lang = 'JavaScript/TypeScript'
            elif filename.endswith('.java'):
                lang = 'Java'
            elif filename.endswith('.go'):
                lang = 'Go'
            elif filename.endswith('.rs'):
                lang = 'Rust'
            elif filename.endswith('.cpp') or filename.endswith('.h'):
                lang = 'C++'
            else:
                lang = 'Other'

            table.add_row(filename, f"{chars:,}", str(lines), lang)
            total_lines += lines
            total_chars += chars

        console.print(table)
        console.print(f"\n📊 Summary: {len(loaded)} files, {total_lines:,} lines, {total_chars:,} chars")
        console.print(f"   Estimated tokens: ~{total_chars // 4:,}")

        # Ask if user wants to load with context
        if loaded:
            console.print("\n[bold]Load these files with context?[/bold]")
            console.print("   deepseek load --context " + " ".join(files[:3]) + (" ..." if len(files) > 3 else ""))

    asyncio.run(_analyze_files())

@cli.command()
@click.argument('repo_url')
@click.option('--ref', '-r', help="Branch, tag, or commit SHA")
@click.option('--name', '-n', help="Custom name for the repository")
@click.option('--analyze', '-a', is_flag=True, help="Analyze repository structure")
@click.option('--load-context', '-l', is_flag=True, help="Load files to context after cloning")
@click.option('--pattern', '-p', multiple=True, help="File patterns to load (default: *.py)")
@click.option('--max-files', default=20, help="Maximum files to load")
def clone(repo_url, ref, name, analyze, load_context, pattern, max_files):
    """Clone a git repository for analysis."""

    async def _clone_async():
        try:
            from assistant.integrations.git import GitIntegration
        except ImportError:
            console.print("[red]❌ Git integration not available[/red]")
            console.print("Install with: uv sync --all-extras")
            console.print("Or install git extras: uv add deepseek-assistant[git]")
            return

        git = GitIntegration()

        try:
            # Clone repository
            with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
            ) as progress:
                task = progress.add_task(f"Cloning {repo_url}...", total=None)

                try:
                    repo = await git.clone_repository(repo_url, name=name, ref=ref)
                    progress.update(task, description=f"[green]✓ Repository cloned[/green]")
                except Exception as e:
                    progress.update(task, description=f"[red]✗ Failed to clone repository[/red]")
                    console.print(f"[red]Error: {e}[/red]")
                    return

            # Analyze if requested
            if analyze:
                await git.analyze_repository(repo, max_files=50)

            # Load to context if requested
            if load_context:
                file_patterns = list(pattern) if pattern else None
                loaded_files = await git.load_files_to_context(
                    repo,
                    file_patterns=file_patterns,
                    max_files=max_files
                )

                # Save to context file
                ctx_manager = ContextManager()

                # Load existing context
                ctx_file = Path("storage/current_context.json")
                if ctx_file.exists():
                    try:
                        ctx_manager.load_context(str(ctx_file))
                        console.print("[yellow]📂 Merging with existing context[/yellow]")
                    except Exception as e:
                        console.print(f"[yellow]⚠️  Could not load existing context: {e}[/yellow]")

                # Add loaded files
                for filepath, content in loaded_files.items():
                    ctx_manager.add_file(filepath, content)

                # Save updated context
                storage_dir = Path("storage")
                storage_dir.mkdir(exist_ok=True)
                ctx_manager.save_context(str(ctx_file))

                console.print(f"\n[green]✅ {len(loaded_files)} files loaded to context[/green]")
                console.print(f"   Context saved to: {ctx_file}")
                console.print(f"   Use 'deepseek chat' to start chatting with context")

        finally:
            git.cleanup()

    asyncio.run(_clone_async())

@cli.command()
@click.argument('repo_url')
@click.option('--ref', '-r', help="Branch, tag, or commit SHA")
@click.option('--pattern', '-p', multiple=True, default=["*.py"])
@click.option('--max-files', default=10, help="Maximum files to load")
def quickload(repo_url, ref, pattern, max_files):
    """Quickly clone a repo and load files to context."""

    async def _quickload_async():
        try:
            from assistant.integrations.git import clone_and_load_context
        except ImportError:
            console.print("[red]❌ Git integration not available[/red]")
            console.print("Install with: uv sync --all-extras")
            console.print("Or install git extras: uv add deepseek-assistant[git]")
            return

        console.print(f"[bold]🚀 Quick loading {repo_url}[/bold]")

        file_patterns = list(pattern)

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
        ) as progress:
            task = progress.add_task(f"Cloning and loading {repo_url}...", total=None)

            try:
                loaded_files = await clone_and_load_context(
                    repo_url=repo_url,
                    ref=ref,
                    file_patterns=file_patterns,
                    max_files=max_files
                )

                progress.update(task, description=f"[green]✓ Loaded {len(loaded_files)} files[/green]")

                # Save to context
                ctx_manager = ContextManager()

                # Load existing context
                ctx_file = Path("storage/current_context.json")
                if ctx_file.exists():
                    try:
                        ctx_manager.load_context(str(ctx_file))
                        console.print("[yellow]📂 Merging with existing context[/yellow]")
                    except Exception as e:
                        console.print(f"[yellow]⚠️  Could not load existing context: {e}[/yellow]")

                # Add loaded files
                for filepath, content in loaded_files.items():
                    ctx_manager.add_file(filepath, content)

                # Save updated context
                storage_dir = Path("storage")
                storage_dir.mkdir(exist_ok=True)
                ctx_manager.save_context(str(ctx_file))

                console.print(f"\n[green]✅ Success! Loaded {len(loaded_files)} files[/green]")
                console.print(f"   Context saved to: {ctx_file}")
                console.print(f"   Use 'deepseek chat' or 'deepseek ask' with your questions")

            except Exception as e:
                progress.update(task, description=f"[red]✗ Failed to load repository[/red]")
                console.print(f"[red]❌ Failed to load repository: {e}[/red]")

    asyncio.run(_quickload_async())

@cli.command()
def version():
    """Show version information."""
    console.print(Panel.fit(
        f"[bold cyan]DeepSeek Code Assistant v0.1.0[/bold cyan]\n"
        f"[dim]Local-first AI pair programmer with codebase awareness[/dim]\n\n"
        f"[green]✅ Phase 1: Foundation[/green]\n"
        f"[dim]• Basic API integration[/dim]\n"
        f"[dim]• CLI interface[/dim]\n"
        f"[dim]• Streaming responses[/dim]\n"
        f"[dim]• Conversation management[/dim]\n\n"
        f"[yellow]🚧 Phase 2: Code Awareness (IN PROGRESS)[/yellow]\n"
        f"[dim]• File loading and context[/dim] [green]✓[/green]\n"
        f"[dim]• Context-aware chat[/dim] [green]✓[/green]\n"
        f"[dim]• AST-aware code parsing[/dim] [yellow]⏳[/yellow]\n"
        f"[dim]• Git integration[/dim] [green]✓[/green]\n"
        f"[dim]• Enhanced context management[/dim] [green]✓[/green]\n",
        title="Version Info"
    ))

@cli.command()
def init():
    """Initialize a new project configuration."""
    from dotenv import load_dotenv
    import os
    import yaml

    load_dotenv()

    # Check if .env exists
    env_path = Path(".env")
    if not env_path.exists():
        console.print("[yellow]Creating .env file...[/yellow]")
        with open(env_path, 'w') as f:
            f.write("# DeepSeek API Configuration\n")
            f.write("DEEPSEEK_API_KEY=your_api_key_here\n\n")
            f.write("# Get your API key from: https://platform.deepseek.com/api_keys\n")
        console.print("[green]✅ Created .env file[/green]")
    else:
        console.print("[yellow]⚠️  .env file already exists[/yellow]")

    # Check if config.yaml exists
    config_path = Path("config.yaml")
    if not config_path.exists():
        console.print("[yellow]Creating config.yaml...[/yellow]")
        config = {
            'deepseek': {
                'base_url': 'https://api.deepseek.com',
                'model': 'deepseek-chat',
                'api_key': '${DEEPSEEK_API_KEY}'  # Will be replaced by env var
            },
            'app': {
                'max_tokens': 4096,
                'temperature': 0.7,
                'stream': True,
                'context_window': 128000
            },
            'context': {
                'max_files': 10,
                'max_file_size_kb': 100,
                'auto_chunk': True,
                'chunk_size': 1000
            },
            'git': {
                'clone_depth': 1,
                'fetch_tags': False,
                'temp_dir': './storage/temp',
                'max_repo_size_mb': 100
            }
        }
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        console.print("[green]✅ Created config.yaml[/green]")
    else:
        console.print("[yellow]⚠️  config.yaml already exists[/yellow]")

    # Create storage directory
    storage_path = Path("storage/conversations")
    storage_path.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✅ Created storage directory at {storage_path}[/green]")

    # Create context storage
    context_dir = Path("storage")
    context_dir.mkdir(exist_ok=True)
    console.print(f"[green]✅ Created context storage[/green]")

    # Create temp directory for git operations
    temp_dir = Path("storage/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✅ Created temp directory for git operations[/green]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("1. Edit .env and add your DeepSeek API key")
    console.print("2. Run: deepseek test")
    console.print("3. Run: deepseek load --context <files>")
    console.print("4. Run: deepseek chat (for interactive chat with context)")
    console.print("5. Run: deepseek ask \"What does this code do?\" (for direct questions)")
    console.print("\n[bold]Git Integration:[/bold]")
    console.print("   deepseek clone <repo_url> --load-context")
    console.print("   deepseek quickload <repo_url>")
    console.print("\n[bold]Example:[/bold]")
    console.print("   deepseek quickload https://github.com/psf/requests")
    console.print("   deepseek ask \"How does this library handle HTTP sessions?\"")

if __name__ == "__main__":
    cli()