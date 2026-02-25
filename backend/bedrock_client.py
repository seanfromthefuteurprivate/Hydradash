"""
HYDRA Bedrock Client v1.0

Shared client for Amazon Bedrock AI models:
- Claude 3.5 Haiku: Flow classification
- Amazon Nova Pro: Sequence matching

Handles authentication, rate limiting, and response parsing.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

log = logging.getLogger("HYDRA.BEDROCK")

try:
    import boto3
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
    log.warning("boto3 not installed - Bedrock features disabled")


# Model IDs
CLAUDE_HAIKU_MODEL = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
NOVA_PRO_MODEL = "amazon.nova-pro-v1:0"
NOVA_MICRO_MODEL = "amazon.nova-micro-v1:0"
TITAN_EMBED_MODEL = "amazon.titan-embed-text-v2:0"

# Default region (should match EC2 for lowest latency)
DEFAULT_REGION = "us-east-1"


@dataclass
class BedrockResponse:
    """Standardized response from Bedrock models."""
    success: bool
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "content": self.content,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "error": self.error
        }


class BedrockClient:
    """
    Client for Amazon Bedrock AI models.

    Supports:
    - Claude 3.5 Haiku for fast classification
    - Amazon Nova Pro for sequence analysis
    - Amazon Titan for embeddings
    """

    def __init__(
        self,
        region: str = None,
        aws_access_key: str = None,
        aws_secret_key: str = None
    ):
        self.region = region or os.environ.get("AWS_REGION", DEFAULT_REGION)
        self.access_key = aws_access_key or os.environ.get("AWS_ACCESS_KEY_ID")
        self.secret_key = aws_secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize the Bedrock runtime client."""
        if not HAS_BOTO3:
            log.error("boto3 not available - cannot initialize Bedrock client")
            return

        try:
            config = Config(
                region_name=self.region,
                retries={"max_attempts": 3, "mode": "adaptive"}
            )

            if self.access_key and self.secret_key:
                self.client = boto3.client(
                    "bedrock-runtime",
                    config=config,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key
                )
            else:
                # Use default credentials (IAM role, ~/.aws/credentials, etc.)
                self.client = boto3.client(
                    "bedrock-runtime",
                    config=config
                )

            log.info(f"Bedrock client initialized for region: {self.region}")

        except Exception as e:
            log.error(f"Failed to initialize Bedrock client: {e}")
            self.client = None

    @property
    def is_available(self) -> bool:
        """Check if Bedrock client is available."""
        return self.client is not None

    def invoke_claude_haiku(
        self,
        prompt: str,
        system: str = None,
        max_tokens: int = 1024,
        temperature: float = 0.0
    ) -> BedrockResponse:
        """
        Invoke Claude 3.5 Haiku for fast classification tasks.

        Args:
            prompt: The user message/prompt
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 = deterministic)

        Returns:
            BedrockResponse with classification result
        """
        if not self.client:
            return BedrockResponse(
                success=False,
                content="",
                model=CLAUDE_HAIKU_MODEL,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                error="Bedrock client not initialized"
            )

        import time
        start_time = time.time()

        try:
            # Build messages
            messages = [{"role": "user", "content": [{"text": prompt}]}]

            # Build request body
            inference_config = {
                "maxTokens": max_tokens,
                "temperature": temperature
            }

            # Make the request
            kwargs = {
                "modelId": CLAUDE_HAIKU_MODEL,
                "messages": messages,
                "inferenceConfig": inference_config
            }

            if system:
                kwargs["system"] = [{"text": system}]

            response = self.client.converse(**kwargs)

            latency_ms = (time.time() - start_time) * 1000

            # Extract response
            output = response.get("output", {})
            message = output.get("message", {})
            content_blocks = message.get("content", [])
            content = content_blocks[0].get("text", "") if content_blocks else ""

            usage = response.get("usage", {})

            return BedrockResponse(
                success=True,
                content=content,
                model=CLAUDE_HAIKU_MODEL,
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                latency_ms=round(latency_ms, 1)
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            log.error(f"Claude Haiku invocation error: {e}")
            return BedrockResponse(
                success=False,
                content="",
                model=CLAUDE_HAIKU_MODEL,
                input_tokens=0,
                output_tokens=0,
                latency_ms=round(latency_ms, 1),
                error=str(e)
            )

    def invoke_nova_pro(
        self,
        prompt: str,
        system: str = None,
        max_tokens: int = 2048,
        temperature: float = 0.0
    ) -> BedrockResponse:
        """
        Invoke Amazon Nova Pro for sequence analysis.

        Args:
            prompt: The user message/prompt
            system: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            BedrockResponse with analysis result
        """
        if not self.client:
            return BedrockResponse(
                success=False,
                content="",
                model=NOVA_PRO_MODEL,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                error="Bedrock client not initialized"
            )

        import time
        start_time = time.time()

        try:
            # Build messages for Nova
            messages = [{"role": "user", "content": [{"text": prompt}]}]

            # Build request
            inference_config = {
                "maxTokens": max_tokens,
                "temperature": temperature
            }

            kwargs = {
                "modelId": NOVA_PRO_MODEL,
                "messages": messages,
                "inferenceConfig": inference_config
            }

            if system:
                kwargs["system"] = [{"text": system}]

            response = self.client.converse(**kwargs)

            latency_ms = (time.time() - start_time) * 1000

            # Extract response
            output = response.get("output", {})
            message = output.get("message", {})
            content_blocks = message.get("content", [])
            content = content_blocks[0].get("text", "") if content_blocks else ""

            usage = response.get("usage", {})

            return BedrockResponse(
                success=True,
                content=content,
                model=NOVA_PRO_MODEL,
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                latency_ms=round(latency_ms, 1)
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            log.error(f"Nova Pro invocation error: {e}")
            return BedrockResponse(
                success=False,
                content="",
                model=NOVA_PRO_MODEL,
                input_tokens=0,
                output_tokens=0,
                latency_ms=round(latency_ms, 1),
                error=str(e)
            )

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Get text embedding using Amazon Titan Embeddings V2.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding vector, or None on error
        """
        if not self.client:
            return None

        try:
            body = json.dumps({
                "inputText": text,
                "dimensions": 512,  # Smaller dimension for efficiency
                "normalize": True
            })

            response = self.client.invoke_model(
                modelId=TITAN_EMBED_MODEL,
                body=body,
                contentType="application/json",
                accept="application/json"
            )

            response_body = json.loads(response["body"].read())
            return response_body.get("embedding")

        except Exception as e:
            log.error(f"Titan embedding error: {e}")
            return None

    def batch_embeddings(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Get embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors (None for failed embeddings)
        """
        return [self.get_embedding(text) for text in texts]


# Singleton instance
_bedrock_client: Optional[BedrockClient] = None


def get_bedrock_client() -> BedrockClient:
    """Get or create the singleton Bedrock client instance."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = BedrockClient()
    return _bedrock_client


# Helper functions for common operations
def classify_with_haiku(prompt: str, system: str = None) -> BedrockResponse:
    """Convenience function for Haiku classification."""
    return get_bedrock_client().invoke_claude_haiku(prompt, system)


def analyze_with_nova(prompt: str, system: str = None) -> BedrockResponse:
    """Convenience function for Nova Pro analysis."""
    return get_bedrock_client().invoke_nova_pro(prompt, system)


def embed_text(text: str) -> Optional[List[float]]:
    """Convenience function for text embedding."""
    return get_bedrock_client().get_embedding(text)


# CLI for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    client = get_bedrock_client()

    if not client.is_available:
        print("Bedrock client not available - check AWS credentials")
        exit(1)

    print("\n" + "=" * 60)
    print("BEDROCK CLIENT - TEST")
    print("=" * 60)

    # Test Haiku
    print("\nTesting Claude Haiku...")
    response = client.invoke_claude_haiku(
        prompt="Classify this market condition: SPY up 0.5%, VIX at 18, volume normal. Respond with JSON: {\"sentiment\": \"bullish/bearish/neutral\", \"confidence\": 0-100}",
        system="You are a market analyst. Respond only with valid JSON.",
        max_tokens=100
    )
    print(f"Success: {response.success}")
    print(f"Content: {response.content}")
    print(f"Latency: {response.latency_ms}ms")
    print(f"Tokens: {response.input_tokens} in, {response.output_tokens} out")

    # Test embedding
    print("\nTesting Titan Embeddings...")
    embedding = client.get_embedding("SPY bullish breakout above VWAP with high volume")
    if embedding:
        print(f"Embedding dimension: {len(embedding)}")
        print(f"First 5 values: {embedding[:5]}")
    else:
        print("Embedding failed")
