# **DeepSeek Code Assistant** 🤖💻

A local, code-aware AI assistant that understands your repository structure and helps you write better code. It combines the power of DeepSeek's 128K context window with intelligent code analysis to provide context-aware programming assistance right in your terminal.

## ✨ **Features**

- **🔍 AST-Aware Code Understanding**: Parses your codebase structure intelligently, not just as text
- **📁 Smart Context Management**: Automatically includes relevant files and dependencies in conversations
- **🔄 Git Integration**: Understands changes and focuses on what you're actually working on
- **⚡ Token-Efficient**: Uses intelligent chunking and RAG to stay within context limits
- **💬 Natural Chat Interface**: Works like a senior developer pair programmer
- **🔧 Multiple Modes**:
    - Direct chat (like ChatGPT)
    - File-augmented conversations
    - Change-focused discussions (git diff aware)

## 🛠️ **Tech Stack**

- **Python 3.10+** with async/await
- **DeepSeek API** (free tier, 128K context)
- **LangChain/LlamaIndex** for RAG and chunking
- **AST parsing** for language-specific understanding
- **Vector embeddings** for semantic code search
- **Streaming responses** with syntax highlighting

## 🚀 **Quick Start**

```bash
# Clone and setup
git clone https://github.com/yourusername/deepseek-code-assistant.git
cd deepseek-code-assistant
pip install -r requirements.txt

# Configure your API key
cp config.example.yaml config.yaml
# Add your DeepSeek API key

# Start chatting with your code
python main.py chat --files src/myproject/
```

## 📁 **Project Structure**

```
├── src/              # Core implementation
├── adapters/         # API and framework adapters  
├── storage/          # Vector DB and cache
├── ui/               # CLI and web interfaces
└── examples/         # Usage examples
```

## 💡 **Use Cases**

- **Code Reviews**: Get intelligent feedback on your changes
- **Refactoring**: Suggestions with full context awareness
- **Debugging**: Understand complex issues across files
- **Learning**: Ask questions about unfamiliar codebases
- **Documentation**: Generate docs from existing code

## 🎯 **Why This Exists**

Most AI coding assistants either:
1. **Have no context** (generic ChatGPT)
2. **Require manual file uploading** (tedious)
3. **Use simple text splitting** (lose code structure)

**DeepSeek Code Assistant** solves this by:
- Automatically understanding your project structure
- Including just the right context
- Maintaining conversation state
- Being completely free to use

## 🤝 **Contributing**

We're building this in the open! Check out our [Contributing Guide](CONTRIBUTING.md) and join us in making AI-assisted programming more accessible and powerful.

---

**Built with ❤️ for developers who want AI that actually understands their code.**

*Note: This is an unofficial community project, not affiliated with DeepSeek.*