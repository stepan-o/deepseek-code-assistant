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
from assistant.core.snapshot_loader import SnapshotLoader

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
@click.argument('snapshot_dir')
def load_snapshot(snapshot_dir):
    """Load a snapshot into context with architectural awareness."""
    _load_snapshot_sync(snapshot_dir)

def _load_snapshot_sync(snapshot_dir: str):
    """Synchronous wrapper for load-snapshot command."""
    try:
        console.print(f"[bold cyan]📦 Loading snapshot: {snapshot_dir}[/bold cyan]")

        # Initialize snapshot loader
        loader = SnapshotLoader()

        # Load snapshot artifacts
        with console.status("[bold green]Loading snapshot artifacts..."):
            try:
                artifacts = loader.load_snapshot(snapshot_dir)
                console.print("[green]✅ Snapshot artifacts loaded[/green]")
            except Exception as e:
                console.print(f"[red]❌ Failed to load snapshot: {e}[/red]")
                return

        # Get key files from snapshot
        key_files = loader.get_key_files(artifacts, max_files=15)

        if not key_files:
            console.print("[yellow]⚠️  No key files identified in snapshot[/yellow]")
            return

        console.print(f"[yellow]📂 Found {len(key_files)} key files[/yellow]")

        # Initialize context manager
        ctx_manager = ContextManager()

        # Load existing context if available
        ctx_file = Path("storage/current_context.json")
        if ctx_file.exists():
            try:
                ctx_manager.load_context(str(ctx_file))
                console.print("[yellow]📂 Merging with existing context[/yellow]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not load existing context: {e}[/yellow]")

        # Load key files
        file_loader = FileLoader()
        loaded_files = {}

        console.print("[dim]Loading key files...[/dim]")

        for file_path in key_files:
            try:
                # Try to load file relative to snapshot directory
                snapshot_path = Path(snapshot_dir)

                # Check if file exists in snapshot directory
                file_abs_path = snapshot_path.parent.parent.parent / file_path
                if file_abs_path.exists():
                    content = file_loader.load_file(str(file_abs_path))
                    if content:
                        loaded_files[file_path] = content
                        console.print(f"  [green]✓[/green] {file_path}")
                else:
                    # Try to load from original repo location
                    content = file_loader.load_file(file_path)
                    if content:
                        loaded_files[file_path] = content
                        console.print(f"  [green]✓[/green] {file_path}")
                    else:
                        console.print(f"  [yellow]⚠️[/yellow] {file_path} (not found)")
            except Exception as e:
                console.print(f"  [red]✗[/red] {file_path}: {e}")

        # Add loaded files to context
        for file_path, content in loaded_files.items():
            ctx_manager.add_file(file_path, content)

        # Create system message from architecture context
        system_message = loader.create_system_message(artifacts)

        # Save snapshot metadata to context
        ctx_manager.snapshot_metadata = {
            'snapshot_dir': snapshot_dir,
            'snapshot_name': artifacts.get('snapshot_name', 'unknown'),
            'system_context': system_message,
            'artifacts_loaded': list(artifacts.get('loaded_artifacts', {}).keys()),
            'key_files_loaded': list(loaded_files.keys()),
            'architecture_summary': artifacts.get('loaded_artifacts', {}).get('architecture_summary', {})
        }

        # Save updated context
        storage_dir = Path("storage")
        storage_dir.mkdir(exist_ok=True)
        ctx_manager.save_context(str(ctx_file))

        # Show summary
        console.print(f"\n[green]✅ Snapshot loaded successfully![/green]")
        console.print(f"   📦 Snapshot: {artifacts.get('snapshot_name', 'unknown')}")
        console.print(f"   📄 Files loaded: {len(loaded_files)}/{len(key_files)}")
        console.print(f"   🏗️  Architecture context: {len(system_message):,} chars")

        # Show architecture overview
        arch_summary = artifacts.get('loaded_artifacts', {}).get('architecture_summary', {})
        if arch_summary and isinstance(arch_summary, dict):
            arch_context = arch_summary.get('architecture_context', {})
            if arch_context:
                overview = arch_context.get('overview', '').strip()
                if overview:
                    console.print(f"\n[bold]Architecture Overview:[/bold]")
                    console.print(overview[:300] + ("..." if len(overview) > 300 else ""))

        console.print(f"\n[bold]Next steps:[/bold]")
        console.print("   deepseek chat      - Start chat with architectural context")
        console.print("   deepseek ask <q>   - Ask questions about the architecture")

    except Exception as e:
        console.print(f"[red]❌ Error loading snapshot: {e}[/red]")
        import traceback
        traceback.print_exc()

@cli.command()
@click.argument('repo_name', required=False)
def list_snapshots(repo_name):
    """List available snapshots for a repository."""
    try:
        from assistant.core.snapshot_loader import SnapshotLoader

        loader = SnapshotLoader()
        snapshots_dir = Path("snapshots")

        if not snapshots_dir.exists():
            console.print("[yellow]⚠️  No snapshots directory found[/yellow]")
            console.print("   Run snapshotter first: uv run snapshotter --dotenv --dry-run")
            return

        if repo_name:
            # List snapshots for specific repo
            repo_dir = snapshots_dir / repo_name
            if not repo_dir.exists():
                console.print(f"[red]❌ No snapshots found for repository: {repo_name}[/red]")
                available = [d.name for d in snapshots_dir.iterdir() if d.is_dir()]
                if available:
                    console.print(f"   Available repositories: {', '.join(available)}")
                return

            snapshot_dirs = []
            for item in repo_dir.iterdir():
                if item.is_dir() and item.name:
                    snapshot_dirs.append(item)

            if not snapshot_dirs:
                console.print(f"[yellow]⚠️  No snapshots found for {repo_name}[/yellow]")
                return

            # Sort by timestamp
            snapshot_dirs.sort(key=lambda x: x.name, reverse=True)

            table = Table(title=f"Snapshots for {repo_name}", box=ROUNDED)
            table.add_column("Timestamp", style="cyan")
            table.add_column("Path", style="yellow")
            table.add_column("Age", style="dim")

            from datetime import datetime
            now = datetime.now()

            for snapshot_dir in snapshot_dirs:
                try:
                    # Parse timestamp from directory name
                    ts_str = snapshot_dir.name
                    ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")

                    # Calculate age
                    delta = now - ts
                    if delta.days > 0:
                        age = f"{delta.days}d ago"
                    elif delta.seconds > 3600:
                        age = f"{delta.seconds // 3600}h ago"
                    elif delta.seconds > 60:
                        age = f"{delta.seconds // 60}m ago"
                    else:
                        age = f"{delta.seconds}s ago"

                    table.add_row(ts_str, str(snapshot_dir.relative_to(Path.cwd())), age)
                except:
                    table.add_row(snapshot_dir.name, str(snapshot_dir.relative_to(Path.cwd())), "unknown")

            console.print(table)

        else:
            # List all repositories with snapshots
            repos = []
            for item in snapshots_dir.iterdir():
                if item.is_dir():
                    # Check if it has any snapshot directories
                    has_snapshots = any(subitem.is_dir() for subitem in item.iterdir())
                    if has_snapshots:
                        repos.append(item)

            if not repos:
                console.print("[yellow]⚠️  No snapshots found[/yellow]")
                console.print("   Run snapshotter first: uv run snapshotter --dotenv --dry-run")
                return

            table = Table(title="Available Snapshots", box=ROUNDED)
            table.add_column("Repository", style="cyan")
            table.add_column("Snapshots", style="yellow", justify="right")
            table.add_column("Latest", style="green")

            for repo_dir in sorted(repos, key=lambda x: x.name):
                snapshot_dirs = [d for d in repo_dir.iterdir() if d.is_dir()]
                snapshot_dirs.sort(key=lambda x: x.name, reverse=True)

                latest = snapshot_dirs[0].name if snapshot_dirs else "None"

                table.add_row(repo_dir.name, str(len(snapshot_dirs)), latest)

            console.print(table)
            console.print("\n[bold]Usage:[/bold]")
            console.print("   deepseek list-snapshots <repo_name>  - List snapshots for specific repo")
            console.print("   deepseek load-snapshot <path>        - Load a snapshot into context")

    except Exception as e:
        console.print(f"[red]❌ Error listing snapshots: {e}[/red]")

@cli.command()
@click.argument('snapshot_dir')
def snapshot_info(snapshot_dir):
    """Show detailed information about a snapshot."""
    try:
        from assistant.core.snapshot_loader import SnapshotLoader

        console.print(f"[bold cyan]📦 Snapshot Info: {snapshot_dir}[/bold cyan]")

        # Initialize snapshot loader
        loader = SnapshotLoader()

        # Load snapshot artifacts
        with console.status("[bold green]Loading snapshot..."):
            try:
                artifacts = loader.load_snapshot(snapshot_dir)
            except Exception as e:
                console.print(f"[red]❌ Failed to load snapshot: {e}[/red]")
                return

        # Display snapshot metadata
        table = Table(title="Snapshot Metadata", box=ROUNDED, show_header=False)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="yellow")

        table.add_row("Path", artifacts.get('snapshot_path', 'unknown'))
        table.add_row("Name", artifacts.get('snapshot_name', 'unknown'))

        loaded_artifacts = artifacts.get('loaded_artifacts', {})
        table.add_row("Artifacts Loaded", f"{len(loaded_artifacts)}")

        console.print(table)

        # Show architecture summary
        arch_summary = loaded_artifacts.get('architecture_summary')
        if arch_summary and isinstance(arch_summary, dict):
            arch_context = arch_summary.get('architecture_context', {})

            if arch_context:
                console.print("\n[bold]🏗️  Architecture Summary[/bold]")

                # Overview
                overview = arch_context.get('overview', '').strip()
                if overview:
                    console.print(Panel(overview, title="Overview", border_style="cyan"))

                # Key modules
                key_modules = arch_context.get('key_modules', [])
                if key_modules and isinstance(key_modules, list):
                    console.print("\n[bold]Key Modules:[/bold]")
                    for i, module in enumerate(key_modules[:5], 1):
                        if isinstance(module, dict):
                            name = module.get('name', f'Module {i}')
                            desc = module.get('description', '').strip()
                            if desc:
                                console.print(f"  {i}. [cyan]{name}[/cyan]: {desc}")
                            else:
                                console.print(f"  {i}. {name}")

                # Technology stack
                tech_stack = arch_context.get('tech_stack', [])
                if tech_stack and isinstance(tech_stack, list):
                    console.print("\n[bold]Technology Stack:[/bold]")
                    for tech in tech_stack[:10]:
                        if isinstance(tech, str):
                            console.print(f"  • {tech}")

                # Design patterns
                patterns = arch_context.get('patterns', [])
                if patterns and isinstance(patterns, list):
                    console.print("\n[bold]Design Patterns:[/bold]")
                    for pattern in patterns[:5]:
                        if isinstance(pattern, str):
                            console.print(f"  • {pattern}")

        # Show key files
        key_files = loader.get_key_files(artifacts, max_files=10)
        if key_files:
            console.print(f"\n[bold]📄 Key Files ({len(key_files)}):[/bold]")
            for i, file_path in enumerate(key_files[:10], 1):
                console.print(f"  {i}. {file_path}")
            if len(key_files) > 10:
                console.print(f"  ... and {len(key_files) - 10} more")

        # Show onboarding content if available
        onboarding = loaded_artifacts.get('onboarding')
        if onboarding:
            console.print("\n[bold]📋 Onboarding Guide[/bold]")
            console.print(onboarding[:500] + ("..." if len(onboarding) > 500 else ""))

        console.print(f"\n[bold]Load this snapshot:[/bold]")
        console.print(f"   deepseek load-snapshot {snapshot_dir}")

    except Exception as e:
        console.print(f"[red]❌ Error getting snapshot info: {e}[/red]")

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

    # FileLoader is synchronous, so we can call it directly
    loader = FileLoader()
    loaded = loader.load_multiple_files(files)

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

    # FileLoader is synchronous
    loader = FileLoader()
    loaded = loader.load_multiple_files(files)

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
        f"[dim]• Enhanced context management[/dim] [green]✓[/green]\n"
        f"[dim]• Snapshot integration[/dim] [green]✓[/green]\n",
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
    console.print("\n[bold]Snapshot Integration:[/bold]")
    console.print("   uv run snapshotter --dotenv --dry-run")
    console.print("   deepseek list-snapshots")
    console.print("   deepseek load-snapshot <snapshot_path>")
    console.print("   deepseek snapshot-info <snapshot_path>")
    console.print("\n[bold]Example Workflow:[/bold]")
    console.print("   1. uv run snapshotter --dotenv --dry-run")
    console.print("   2. deepseek load-snapshot snapshots/my-repo/20240101_120000/")
    console.print("   3. deepseek chat")
    console.print("   4. deepseek ask \"How does this architecture handle authentication?\"")

if __name__ == "__main__":
    cli()