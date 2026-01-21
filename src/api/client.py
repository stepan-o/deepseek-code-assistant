# src/api/client.py
import os
import yaml
import json
from typing import Dict, Any, AsyncGenerator, Optional
import httpx
from pathlib import Path

class DeepSeekClient:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)

        # Get API key: first from environment, then from config
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            # Try to get from config
            self.api_key = self.config.get('deepseek', {}).get('api_key')
            # If it's a template string, try to resolve it
            if isinstance(self.api_key, str) and self.api_key.startswith('${') and self.api_key.endswith('}'):
                env_var = self.api_key[2:-1]
                self.api_key = os.getenv(env_var)

        if not self.api_key or self.api_key == "your_api_key_here":
            raise ValueError("DEEPSEEK_API_KEY not configured. Please set it in .env file or config.yaml")

        self.base_url = self.config.get('deepseek', {}).get('base_url', 'https://api.deepseek.com')
        self.model = self.config.get('deepseek', {}).get('model', 'deepseek-chat')
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient(timeout=30.0)

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file with validation"""
        path = Path(config_path)
        if not path.exists():
            # Create default config
            default_config = {
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
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                yaml.dump(default_config, f, default_flow_style=False)
            return default_config

        with open(path, 'r') as f:
            config = yaml.safe_load(f)

        # Ensure required structure
        if not isinstance(config, dict):
            config = {}

        # Set defaults if not present
        config.setdefault('deepseek', {})
        config['deepseek'].setdefault('base_url', 'https://api.deepseek.com')
        config['deepseek'].setdefault('model', 'deepseek-chat')

        config.setdefault('app', {})
        config['app'].setdefault('max_tokens', 4096)
        config['app'].setdefault('temperature', 0.7)
        config['app'].setdefault('stream', True)
        config['app'].setdefault('context_window', 128000)

        return config

    async def chat_completion(
            self,
            messages: list,
            stream: bool = None,
            max_tokens: int = None,
            temperature: float = None
    ) -> AsyncGenerator[str, None]:
        """Send chat completion request, optionally streaming"""

        stream = stream if stream is not None else self.config['app']['stream']
        max_tokens = max_tokens if max_tokens is not None else self.config['app']['max_tokens']
        temperature = temperature if temperature is not None else self.config['app']['temperature']

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream
        }

        try:
            if stream:
                async with self.client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
                        json=payload
                ) as response:
                    if response.status_code == 401:
                        raise AuthenticationError("Invalid API key")
                    elif response.status_code == 429:
                        raise RateLimitError("Rate limit exceeded")
                    elif response.status_code >= 400:
                        raise APIError(f"API error: {response.status_code}", response.status_code)

                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                if "choices" in chunk and chunk["choices"]:
                                    delta = chunk["choices"][0].get("delta", {})
                                    if "content" in delta and delta["content"]:
                                        yield delta["content"]
                            except json.JSONDecodeError:
                                continue
            else:
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload
                )

                if response.status_code == 401:
                    raise AuthenticationError("Invalid API key")
                elif response.status_code == 429:
                    raise RateLimitError("Rate limit exceeded")
                elif response.status_code >= 400:
                    raise APIError(f"API error: {response.status_code}", response.status_code)

                response.raise_for_status()
                data = response.json()
                yield data["choices"][0]["message"]["content"]

        except httpx.TimeoutException:
            raise APIError("Request timeout")
        except httpx.RequestError as e:
            raise APIError(f"Request failed: {str(e)}")

    async def test_connection(self) -> bool:
        """Test if API connection works"""
        try:
            # Simple test request
            test_payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10,
                "stream": False
            }

            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=test_payload,
                timeout=10.0
            )

            if response.status_code == 200:
                return True
            elif response.status_code == 401:
                raise AuthenticationError("Invalid API key")
            else:
                return False

        except Exception as e:
            print(f"Connection test failed: {e}")
            return False

    async def get_usage(self) -> Optional[Dict[str, Any]]:
        """Get API usage statistics (if supported)"""
        # Note: DeepSeek API may not have usage endpoint
        # This is a placeholder for future implementation
        return None

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Error classes
class DeepSeekError(Exception):
    """Base exception for DeepSeek API errors."""
    pass

class AuthenticationError(DeepSeekError):
    """Raised when API authentication fails."""
    pass

class RateLimitError(DeepSeekError):
    """Raised when rate limit is exceeded."""
    pass

class APIError(DeepSeekError):
    """Raised for general API errors."""
    def __init__(self, message, status_code=None):
        self.status_code = status_code
        super().__init__(message)

class ConfigurationError(DeepSeekError):
    """Raised for configuration errors."""
    pass

class ContextTooLargeError(DeepSeekError):
    """Raised when context exceeds token limits."""
    pass