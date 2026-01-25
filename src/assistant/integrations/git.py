# src/assistant/integrations/git.py
"""
Git integration for DeepSeek Code Assistant.
Provides high-level git operations for code analysis.
"""
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
import tempfile
import shutil

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn

from shared.git_operations import GitRepository, run_async

console = Console()


class GitIntegration:
    """Git integration for code assistant."""

    def __init__(self, workdir: Optional[str] = None):
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="deepseek_git_"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.repositories: Dict[str, GitRepository] = {}

    async def clone_repository(
            self,
            repo_url: str,
            name: Optional[str] = None,
            ref: Optional[str] = None,
            depth: int = 1,
            with_tags: bool = False
    ) -> GitRepository:
        """Clone a repository with progress indication."""
        if not name:
            # Extract name from URL
            name = repo_url.split('/')[-1].replace('.git', '')

        repo_path = self.workdir / name

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
        ) as progress:
            task = progress.add_task(f"Cloning {name}...", total=None)

            try:
                repo = GitRepository(repo_path)
                commit_hash, _ = await repo.clone_and_checkout_async(
                    repo_url=repo_url,
                    ref=ref,
                    depth=depth,
                    with_tags=with_tags
                )

                progress.update(task, description=f"[green]✓ Cloned {name} ({commit_hash[:8]})")
                self.repositories[name] = repo

                # Show repo info
                info = repo.get_repo_info()
                self._display_repo_info(info)

                return repo

            except Exception as e:
                progress.update(task, description=f"[red]✗ Failed to clone {name}")
                console.print(f"[red]Error: {e}[/red]")
                raise

    def _display_repo_info(self, info: Dict[str, Any]):
        """Display repository information."""
        table = Table(title="Repository Information", show_header=False, box=None)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Path", info['path'])
        table.add_row("Remote", info['remote_url'])
        table.add_row("Branch", info['current_branch'])
        table.add_row("Commit", f"{info['commit_hash'][:8]}...")
        table.add_row("Status", "Detached" if info['is_detached'] else "On branch")

        console.print(table)

        # Show commit message
        if info['commit_message']:
            console.print(Panel(
                info['commit_message'],
                title="Latest Commit Message",
                border_style="dim"
            ))

    async def analyze_repository(
            self,
            repo: GitRepository,
            file_pattern: str = "*.py",
            max_files: int = 50
    ) -> Dict[str, Any]:
        """Analyze repository structure and content."""
        console.print(f"[bold]🔍 Analyzing repository...[/bold]")

        # Get all files
        all_files = repo.list_files(file_pattern)

        if not all_files:
            console.print(f"[yellow]No files matching pattern '{file_pattern}'[/yellow]")
            return {"total_files": 0, "files": []}

        # Limit files if needed
        files_to_analyze = all_files[:max_files]

        analysis_results = {
            "total_files": len(all_files),
            "analyzed_files": len(files_to_analyze),
            "files": [],
            "total_lines": 0,
            "total_chars": 0
        }

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
        ) as progress:
            task = progress.add_task("Analyzing files...", total=len(files_to_analyze))

            for filepath in files_to_analyze:
                try:
                    content = repo.get_file_content(filepath)
                    lines = content.count('\n') + 1
                    chars = len(content)

                    analysis_results["files"].append({
                        "path": filepath,
                        "lines": lines,
                        "chars": chars,
                        "language": self._detect_language(filepath)
                    })

                    analysis_results["total_lines"] += lines
                    analysis_results["total_chars"] += chars

                except Exception as e:
                    console.print(f"[yellow]⚠️  Could not read {filepath}: {e}[/yellow]")

                progress.update(task, advance=1)

        # Display summary
        self._display_analysis_summary(analysis_results)

        return analysis_results

    def _detect_language(self, filepath: str) -> str:
        """Detect programming language from file extension."""
        ext = Path(filepath).suffix.lower()

        language_map = {
            '.py': 'Python',
            '.js': 'JavaScript',
            '.ts': 'TypeScript',
            '.jsx': 'JavaScript (React)',
            '.tsx': 'TypeScript (React)',
            '.java': 'Java',
            '.go': 'Go',
            '.rs': 'Rust',
            '.cpp': 'C++',
            '.cc': 'C++',
            '.cxx': 'C++',
            '.h': 'C/C++ Header',
            '.hpp': 'C++ Header',
            '.cs': 'C#',
            '.php': 'PHP',
            '.rb': 'Ruby',
            '.swift': 'Swift',
            '.kt': 'Kotlin',
            '.scala': 'Scala',
            '.html': 'HTML',
            '.css': 'CSS',
            '.json': 'JSON',
            '.yaml': 'YAML',
            '.yml': 'YAML',
            '.toml': 'TOML',
            '.md': 'Markdown',
            '.sql': 'SQL',
            '.sh': 'Shell',
            '.bash': 'Bash',
            '.zsh': 'Zsh',
        }

        return language_map.get(ext, 'Unknown')

    def _display_analysis_summary(self, analysis: Dict[str, Any]):
        """Display analysis summary."""
        if not analysis["files"]:
            return

        table = Table(title="Repository Analysis", box=None)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Total Files", str(analysis["total_files"]))
        table.add_row("Analyzed Files", str(analysis["analyzed_files"]))
        table.add_row("Total Lines", f"{analysis['total_lines']:,}")
        table.add_row("Total Characters", f"{analysis['total_chars']:,}")
        table.add_row("Estimated Tokens", f"{analysis['total_chars'] // 4:,}")

        console.print(table)

        # Show file breakdown by language
        language_stats = {}
        for file_info in analysis["files"]:
            lang = file_info["language"]
            language_stats[lang] = language_stats.get(lang, 0) + 1

        if language_stats:
            lang_table = Table(title="Languages", box=None)
            lang_table.add_column("Language", style="magenta")
            lang_table.add_column("Files", style="white", justify="right")

            for lang, count in sorted(language_stats.items(), key=lambda x: x[1], reverse=True):
                lang_table.add_row(lang, str(count))

            console.print(lang_table)

    async def preview_file(self, repo: GitRepository, filepath: str, lines: int = 20):
        """Preview a file with syntax highlighting."""
        try:
            content = repo.get_file_content(filepath)

            # Determine language for syntax highlighting
            ext = Path(filepath).suffix.lower()
            language = self._detect_language(filepath).lower()

            console.print(f"\n[bold cyan]📄 {filepath}[/bold cyan]")
            console.print(f"[dim]Size: {len(content):,} chars, {content.count('\\n') + 1} lines[/dim]")

            # Show first N lines
            content_lines = content.split('\n')
            preview = '\n'.join(content_lines[:lines])
            if len(content_lines) > lines:
                preview += f"\n... [and {len(content_lines) - lines} more lines]"

            console.print(Syntax(preview, language, theme="monokai", line_numbers=True))

        except Exception as e:
            console.print(f"[red]❌ Could not preview {filepath}: {e}[/red]")

    async def load_files_to_context(
            self,
            repo: GitRepository,
            file_patterns: List[str] = None,
            max_files: int = 10
    ) -> Dict[str, str]:
        """Load repository files into context for chat."""
        if file_patterns is None:
            file_patterns = ["*.py", "*.js", "*.ts", "*.go", "*.rs", "*.java"]

        all_files = []
        for pattern in file_patterns:
            files = repo.list_files(pattern)
            all_files.extend(files)

        # Remove duplicates and limit
        unique_files = list(dict.fromkeys(all_files))[:max_files]

        loaded_files = {}

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
        ) as progress:
            task = progress.add_task("Loading files to context...", total=len(unique_files))

            for filepath in unique_files:
                try:
                    content = repo.get_file_content(filepath)
                    loaded_files[filepath] = content
                except Exception as e:
                    console.print(f"[yellow]⚠️  Could not load {filepath}: {e}[/yellow]")

                progress.update(task, advance=1)

        console.print(f"[green]✅ Loaded {len(loaded_files)} files to context[/green]")
        return loaded_files

    def cleanup(self):
        """Clean up temporary directories."""
        for repo in self.repositories.values():
            if repo.path.exists():
                try:
                    shutil.rmtree(repo.path, ignore_errors=True)
                except:
                    pass

        if self.workdir.exists():
            try:
                shutil.rmtree(self.workdir, ignore_errors=True)
            except:
                pass


# CLI helper functions
async def clone_and_load_context(
        repo_url: str,
        ref: Optional[str] = None,
        file_patterns: List[str] = None,
        max_files: int = 10
) -> Dict[str, str]:
    """High-level function to clone repo and load files to context."""
    git = GitIntegration()

    try:
        # Clone repository
        repo = await git.clone_repository(repo_url, ref=ref)

        # Load files to context
        files = await git.load_files_to_context(
            repo,
            file_patterns=file_patterns,
            max_files=max_files
        )

        return files

    finally:
        git.cleanup()