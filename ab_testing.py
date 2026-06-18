"""
A/B Testing Framework
Tests different routing strategies against each other to find the best one.
"""

import random
import sqlite3
from datetime import datetime

class ABTest:
    """
    Splits traffic between two routing strategies and measures which performs better.
    Users are randomly assigned to group A or B, and stick with that group for the session.
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self.active_tests = {}
    
    def create_test(self, test_name, strategy_a, strategy_b):
        """Create a new A/B test comparing two routing strategies."""
        self.active_tests[test_name] = {
            'strategy_a': strategy_a,  # Function that takes a prompt, returns model name
            'strategy_b': strategy_b,
            'results_a': {'total': 0, 'positive': 0, 'latency': []},
            'results_b': {'total': 0, 'positive': 0, 'latency': []},
            'started': datetime.now()
        }
        return test_name
    
    def get_group(self, user_id, test_name):
        """Assign a user to group A or B. Same user always gets same group."""
        # Hash user_id to a number, use that to deterministically assign groups
        hash_val = sum(ord(c) for c in user_id)
        return 'A' if hash_val % 2 == 0 else 'B'
    
    def route(self, user_id, test_name, prompt):
        """Route a prompt using the assigned strategy for this user's group."""
        if test_name not in self.active_tests:
            return None  # Test not found
        
        test = self.active_tests[test_name]
        group = self.get_group(user_id, test_name)
        
        if group == 'A':
            return test['strategy_a'](prompt), 'A'
        else:
            return test['strategy_b'](prompt), 'B'
    
    def record_result(self, test_name, group, was_positive, latency):
        """Record the outcome of a routed request."""
        if test_name not in self.active_tests:
            return
        
        results = self.active_tests[test_name][f'results_{group.lower()}']
        results['total'] += 1
        if was_positive:
            results['positive'] += 1
        results['latency'].append(latency)
    
    def get_results(self, test_name):
        """Get current results of an A/B test."""
        if test_name not in self.active_tests:
            return None
        
        test = self.active_tests[test_name]
        
        def calc_stats(results):
            if results['total'] == 0:
                return {'satisfaction': 0, 'avg_latency': 0, 'total': 0}
            return {
                'satisfaction': results['positive'] / results['total'] * 100,
                'avg_latency': sum(results['latency']) / len(results['latency']) if results['latency'] else 0,
                'total': results['total']
            }
        
        return {
            'test_name': test_name,
            'started': test['started'].isoformat(),
            'group_a': calc_stats(test['results_a']),
            'group_b': calc_stats(test['results_b']),
            'winner': 'A' if calc_stats(test['results_a'])['satisfaction'] > calc_stats(test['results_b'])['satisfaction'] else 'B'
        }


# ─── Singleton ──────────────────────────────────────────────────
ab_tester = ABTest()

# Example: Create a test comparing keyword routing vs always-DeepSeek
ab_tester.create_test(
    'keyword_vs_deepseek',
    strategy_a=lambda prompt: 'deepseek',  # Always DeepSeek
    strategy_b=lambda prompt: 'deepseek'    # Keyword routing (placeholder)
)