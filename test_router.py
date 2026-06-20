"""
Test suite for AI Model Router core modules.
Run with: python -m pytest test_router.py -v
Install: pip install pytest
"""

import sys
import os
sys.path.insert(0, '.')

# Import environment variables
from dotenv import load_dotenv
load_dotenv()

import pytest
from router import classify_task, estimate_complexity, route_task, MODELS, ROUTING


class TestClassifier:
    """Test task classification."""
    
    def test_classify_debug(self):
        assert classify_task("Fix the bug in the login function") == 'debug'
        assert classify_task("Why does this error keep happening?") == 'debug'
        assert classify_task("Debug the null pointer exception") == 'debug'
    
    def test_classify_algorithm(self):
        assert classify_task("Write a function to sort an array") == 'algorithm'
        assert classify_task("Implement a binary search tree") == 'algorithm'
        assert classify_task("Build a pathfinding algorithm") == 'algorithm'
    
    def test_classify_refactor(self):
        assert classify_task("Refactor this to use list comprehension") == 'refactor'
        assert classify_task("Clean up this spaghetti code") == 'refactor'
        assert classify_task("Optimize this database query") == 'refactor'
    
    def test_classify_explain(self):
        assert classify_task("Explain how garbage collection works") == 'explain'
        assert classify_task("What does git status do?") == 'explain'
    
    def test_classify_edge_cases(self):
        assert classify_task("Fix the architecture to scale horizontally") == 'debug'
        assert classify_task("Help me understand why this crashes") == 'explain'


class TestComplexity:
    """Test complexity estimation."""
    
    def test_simple_tasks(self):
        assert estimate_complexity("What is a variable?") == 'simple'
        assert estimate_complexity("How do I print in Python?") == 'simple'
    
    def test_standard_tasks(self):
        assert estimate_complexity("Write a function to sort an array") == 'standard'
        assert estimate_complexity("Fix the null pointer in this code") == 'standard'
    
    def test_heavy_tasks(self):
        prompt = "Design a distributed rate limiter for 1M requests per second across multiple data centers with failover"
        assert estimate_complexity(prompt) == 'heavy'
    
    def test_length_based(self):
        short = "Hi"
        long = "architecture design system scale distributed " * 20
        assert estimate_complexity(short) == 'simple'
        assert estimate_complexity(long) == 'heavy'


class TestRouting:
    """Test routing logic."""
    
    def test_route_algorithm(self):
        result = route_task("Write a function to sort an array")
        assert result['task_type'] == 'algorithm'
        assert result['primary_model'] in ['deepseek', 'qwen3-coder']
    
    def test_route_debug(self):
        result = route_task("Fix the null pointer bug")
        assert result['task_type'] == 'debug'
        assert result['primary_model'] == 'deepseek'
    
    def test_route_refactor(self):
        result = route_task("Refactor this to use dependency injection")
        assert result['task_type'] == 'refactor'
        assert result['primary_model'] == 'claude'
    
    def test_route_explain(self):
        result = route_task("Explain how a hash table works")
        assert result['task_type'] == 'explain'
    
    def test_route_includes_fallback(self):
        result = route_task("Write a sorting function")
        assert 'fallback_model' in result
        assert result['fallback_model'] in MODELS
    
    def test_route_includes_cost(self):
        result = route_task("Write code")
        assert 'estimated_cost' in result
        assert result['estimated_cost'] > 0


class TestModels:
    """Test model configuration."""
    
    def test_all_models_have_required_fields(self):
        required = ['name', 'cost_per_1k_tokens', 'strength', 'tier']
        for model_key, model_data in MODELS.items():
            for field in required:
                assert field in model_data, f"{model_key} missing {field}"
    
    def test_deepseek_cheapest(self):
        costs = {k: v['cost_per_1k_tokens'] for k, v in MODELS.items()}
        assert costs['deepseek'] == min(costs.values())
    
    def test_routing_covers_all_task_types(self):
        task_types = ['algorithm', 'debug', 'refactor', 'explain', 'architecture', 'simple', 'other']
        for task in task_types:
            assert task in ROUTING, f"Missing routing for {task}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])