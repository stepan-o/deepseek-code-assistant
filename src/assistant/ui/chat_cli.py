# src/assistant/ui/chat_cli.py
"""
Chat CLI interface for DeepSeek Code Assistant.
"""
import asyncio
import sys
from typing import Optional
from pathlib import Path
import readline  # For better input handling


class ChatCLI:
    def __init__(self, api_client):
        self.api_client = api_client
        self.messages = []
        self.conversation_active = True

    async def start(self):
        """Start the chat interface."""
        print("\n" + "="*50)
        print("🤖 DeepSeek Code Assistant")
        print("="*50)
        print("Type your messages. Commands:")
        print("  /clear    - Clear conversation")
        print("  /exit     - Exit")
        print("  /help     - Show this help")
        print("  /save     - Save conversation")
        print("="*50 + "\n")

        while self.conversation_active:
            try:
                user_input = await self._get_user_input()

                if user_input.startswith('/'):
                    await self._handle_command(user_input)
                    continue

                if not user_input.strip():
                    continue

                # Add user message to history
                self.messages.append({"role": "user", "content": user_input})

                # Get and stream response
                print("\n🤖 Assistant: ", end="", flush=True)
                full_response = ""

                async for chunk in self.api_client.chat_completion(self.messages):
                    print(chunk, end="", flush=True)
                    full_response += chunk

                print("\n")  # New line after response

                # Add assistant response to history
                self.messages.append({"role": "assistant", "content": full_response})

            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except EOFError:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"\n⚠️  Error: {e}")
                continue

    async def _get_user_input(self) -> str:
        """Get input from user with basic line editing."""
        loop = asyncio.get_event_loop()
        try:
            # Use asyncio for async input
            user_input = await loop.run_in_executor(None, lambda: input("\n💬 You: ").strip())
            return user_input
        except (EOFError, KeyboardInterrupt):
            return "/exit"
        except Exception:
            return ""

    async def _handle_command(self, command: str):
        """Handle slash commands."""
        cmd = command.strip().lower()

        if cmd == "/clear":
            self.messages = []
            print("🗑️  Conversation cleared")

        elif cmd == "/exit":
            self.conversation_active = False
            print("👋 Goodbye!")

        elif cmd == "/help":
            print("\nCommands:")
            print("  /clear    - Clear conversation history")
            print("  /exit     - Exit the program")
            print("  /help     - Show this help message")
            print("  /save     - Save conversation to file")
            print()

        elif cmd == "/save":
            await self._save_conversation()

        else:
            print(f"❓ Unknown command: {command}")
            print("Type /help for available commands")

    async def _save_conversation(self):
        """Save conversation to file."""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"conversation_{timestamp}.md"

            # Ensure conversations directory exists
            conversations_dir = Path("storage/conversations")
            conversations_dir.mkdir(parents=True, exist_ok=True)

            filepath = conversations_dir / filename

            with open(filepath, 'w') as f:
                f.write("# DeepSeek Conversation\n\n")
                f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                for i, msg in enumerate(self.messages):
                    role = "User" if msg["role"] == "user" else "Assistant"
                    f.write(f"## {role} (Message {i+1})\n\n")
                    f.write(f"{msg['content']}\n\n")

            print(f"💾 Conversation saved to {filepath}")
        except Exception as e:
            print(f"❌ Failed to save: {e}")


async def main():
    """Main entry point for CLI."""
    try:
        from assistant.api.client import DeepSeekClient

        print("Initializing DeepSeek client...")
        client = DeepSeekClient()

        # Test connection
        print("Testing API connection...")
        if await client.test_connection():
            print("✅ API connection successful!")
        else:
            print("❌ API connection failed")
            print("Please check your API key in .env file")
            return

        cli = ChatCLI(client)
        await cli.start()

        # Clean up
        await client.close()

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running from the project root directory")
        sys.exit(1)
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\nPlease set your API key in .env file:")
        print("  DEEPSEEK_API_KEY=your_api_key_here")
        print("\nGet your API key from: https://platform.deepseek.com/api_keys")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run():
    """Synchronous entry point for scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
