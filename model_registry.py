"""
Global Model Registry
Tracks every AI model available, their capabilities, pricing, and status.
Your router becomes the definitive source of truth for AI model selection.
"""

from datetime import datetime

class ModelRegistry:
    """
    Central registry of all available AI models.
    Updated automatically as new models release.
    """
    
    REGISTRY = {
        'deepseek-v3': {
            'provider': 'DeepSeek',
            'type': 'chat',
            'parameters': '671B (MoE)',
            'context_window': 128000,
            'strengths': ['algorithms', 'debugging', 'speed'],
            'pricing': {'input': 0.28, 'output': 0.42},
            'license': 'MIT',
            'api_status': 'active',
            'added_date': '2025-12-01'
        },
        'claude-sonnet-4-6': {
            'provider': 'Anthropic',
            'type': 'chat',
            'parameters': 'Unknown',
            'context_window': 200000,
            'strengths': ['refactoring', 'production code', 'testing'],
            'pricing': {'input': 3.00, 'output': 15.00},
            'license': 'Proprietary',
            'api_status': 'active',
            'added_date': '2025-06-01'
        },
        'gemma-4': {
            'provider': 'Google',
            'type': 'chat',
            'parameters': '27B',
            'context_window': 8192,
            'strengths': ['local inference', 'privacy'],
            'pricing': {'input': 0.00, 'output': 0.00},  # Open weight
            'license': 'Gemma',
            'api_status': 'local_only',
            'added_date': '2026-05-01'
        },
        'qwen3-coder': {
            'provider': 'Alibaba',
            'type': 'code',
            'parameters': '480B (MoE)',
            'context_window': 256000,
            'strengths': ['coding', 'agentic tasks'],
            'pricing': {'input': 0.22, 'output': 1.80},
            'license': 'Apache 2.0',
            'api_status': 'active',
            'added_date': '2026-04-01'
        },
        'gpt-5-codex': {
            'provider': 'OpenAI',
            'type': 'code',
            'parameters': 'Unknown',
            'context_window': 128000,
            'strengths': ['coding', 'refactoring', 'testing'],
            'pricing': {'input': 5.00, 'output': 25.00},
            'license': 'Proprietary',
            'api_status': 'active',
            'added_date': '2026-03-01'
        }
    }
    
    def get_model(self, model_id):
        """Get details for a specific model."""
        return self.REGISTRY.get(model_id)
    
    def list_active_models(self):
        """List all currently available models."""
        return {
            k: v for k, v in self.REGISTRY.items() 
            if v['api_status'] == 'active'
        }
    
    def list_by_strength(self, strength):
        """Find models strong in a particular area."""
        return {
            k: v for k, v in self.REGISTRY.items()
            if strength in v['strengths']
        }
    
    def list_open_weight(self):
        """List all open-weight models (free to use)."""
        return {
            k: v for k, v in self.REGISTRY.items()
            if v['license'] in ['MIT', 'Apache 2.0']
        }
    
    def add_model(self, model_id, details):
        """Register a new model in the registry."""
        details['added_date'] = datetime.now().strftime('%Y-%m-%d')
        self.REGISTRY[model_id] = details
        return model_id
    
    def compare_models(self, model_ids):
        """Compare multiple models side by side."""
        comparison = {}
        for mid in model_ids:
            if mid in self.REGISTRY:
                comparison[mid] = self.REGISTRY[mid]
        return comparison
    
    def get_routing_recommendation(self, task_type, budget=None):
        """
        Get the best model for a task type, considering budget.
        This is the automated version of your original benchmark work.
        """
        candidates = []
        
        for model_id, details in self.REGISTRY.items():
            if details['api_status'] != 'active':
                continue
            
            if task_type in details['strengths']:
                score = details['strengths'].count(task_type) * 10
                
                # Price factor (cheaper = better score)
                price = details['pricing']['input'] + details['pricing']['output']
                price_score = max(0, 10 - price)
                
                candidates.append({
                    'model': model_id,
                    'provider': details['provider'],
                    'score': score + price_score,
                    'price': price
                })
        
        # Sort by score
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        # Filter by budget
        if budget is not None:
            candidates = [c for c in candidates if c['price'] <= budget]
        
        return candidates[0] if candidates else None


# ─── Singleton ──────────────────────────────────────────────────
model_registry = ModelRegistry()