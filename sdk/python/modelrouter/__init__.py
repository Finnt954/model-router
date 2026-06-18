"""
ModelRouter Python SDK
Official Python client for the AI Model Router API.
"""

import requests
from typing import Optional, Dict, List, Generator

class ModelRouter:
    """
    Python SDK for ModelRouter API.
    
    Usage:
        client = ModelRouter(api_key="your-key")
        result = client.route("Write a binary search in Python")
        print(result.model_used)  # "DeepSeek V3"
        print(result.response)     # The actual code
    """
    
    def __init__(self, api_key: str, base_url: str = "http://localhost:5000"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': api_key,
            'Content-Type': 'application/json'
        })
    
    def route(self, prompt: str, model: str = "auto") -> Dict:
        """
        Route a coding task to the best model.
        
        Args:
            prompt: The coding task or question
            model: 'auto' for smart routing, 'deepseek' or 'claude' to force
        
        Returns:
            dict with 'result', 'model_used', 'task_type', 'cost', 'elapsed'
        """
        response = self.session.post(
            f"{self.base_url}/api/v1/route",
            json={"prompt": prompt, "model_override": model}
        )
        response.raise_for_status()
        return response.json()
    
    def route_batch(self, prompts: List[str], model: str = "auto") -> List[Dict]:
        """
        Route multiple tasks. Each routed independently.
        
        Args:
            prompts: List of coding tasks
            model: Model override (applied to all)
        
        Returns:
            List of result dicts
        """
        return [self.route(p, model) for p in prompts]
    
    def list_models(self) -> Dict:
        """Get available models and routing rules."""
        response = self.session.get(f"{self.base_url}/api/v1/models")
        response.raise_for_status()
        return response.json()
    
    def get_usage(self) -> Dict:
        """Get current usage and billing info."""
        response = self.session.get(f"{self.base_url}/billing/usage")
        response.raise_for_status()
        return response.json()
    
    def get_leaderboard(self) -> Dict:
        """Get model performance leaderboard."""
        response = self.session.get(f"{self.base_url}/leaderboard")
        response.raise_for_status()
        return response.json()
    
    def health_check(self) -> bool:
        """Check if the API is up."""
        try:
            response = self.session.get(f"{self.base_url}/health")
            return response.status_code == 200
        except:
            return False


class RouterResult:
    """Typed result from a route request."""
    
    def __init__(self, data: Dict):
        self.result = data.get('result', '')
        self.model_used = data.get('model_used', 'Unknown')
        self.task_type = data.get('task_type', 'unknown')
        self.cost = data.get('cost', 0)
        self.elapsed = data.get('elapsed', 0)
        self.cached = data.get('cached', False)
    
    def __repr__(self):
        return f"RouterResult(model={self.model_used}, task={self.task_type}, cost=${self.cost:.6f})"