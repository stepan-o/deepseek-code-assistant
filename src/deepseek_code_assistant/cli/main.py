# src/cli/main.py
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
from rich.markdown import Markdown

# Try to import our modules, provide helpful errors if missing
try:
    from src.api.client import DeepSeekClient
    from src.ui.chat_cli import ChatCLI
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Please install the package first: pip install -e .")
    sys.exit(1)

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
    try:
        client = DeepSeekClient(config)

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
def analyze(files):
    """Analyze code files (Phase 2 feature)."""
    console.print("[yellow]⚠️  Feature coming in Phase 2[/yellow]")
    console.print("This will analyze code structure and create embeddings.")

    if files:
        console.print(f"\nFiles to analyze: {len(files)}")
        for file in files:
            console.print(f"  • {file}")

@cli.command()
def version():
    """Show version information."""
    console.print(Panel.fit(
        f"[bold cyan]DeepSeek Code Assistant v0.1.0[/bold cyan]\n"
        f"[dim]Local-first AI pair programmer with codebase awareness[/dim]\n\n"
        f"[yellow]Phase 1: Foundation[/yellow]\n"
        f"[dim]• Basic API integration[/dim]\n"
        f"[dim]• CLI interface[/dim]\n"
        f"[dim]• Streaming responses[/dim]\n\n"
        f"[green]Coming in Phase 2:[/green]\n"
        f"[dim]• AST-aware code parsing[/dim]\n"
        f"[dim]• Git integration[/dim]\n"
        f"[dim]• Enhanced context management[/dim]",
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

    console.print("\n[bold]Next steps:[/bold]")
    console.print("1. Edit .env and add your DeepSeek API key")
    console.print("2. Run: deepseek test")
    console.print("3. Run: deepseek chat")

if __name__ == "__main__":
    cli()