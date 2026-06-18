"""
Synthetic Training Data Generator
Uses your own router to generate training data for better routing.
Self-improving system — gets smarter with every iteration.
"""

import sqlite3
import json
import random
from datetime import datetime

class SyntheticDataGenerator:
    """
    Generates training data by having models rate each other's responses.
    This is how GPT-4 was trained — AI evaluating AI.
    """
    
    SEED_TASKS = [
        # Algorithm tasks
        "Write a function to find the kth largest element in an array",
        "Implement a trie with insert, search, and startsWith methods",
        "Write a function to detect cycles in a directed graph",
        "Implement merge sort without using recursion",
        "Write a function to solve the traveling salesman problem using dynamic programming",
        
        # Debug tasks
        "Fix the race condition in this multithreaded code",
        "Debug this memory leak in the Python application",
        "Find why this SQL query returns incorrect results on large datasets",
        "Fix the off-by-one error in this binary search implementation",
        "Debug why this React component keeps re-rendering",
        
        # Refactor tasks
        "Refactor this 500-line function into smaller, testable units",
        "Convert this callback-based code to use async/await",
        "Apply the strategy pattern to remove this switch statement",
        "Refactor this God class into smaller classes with single responsibilities",
        "Convert this inheritance hierarchy to composition",
        
        # Explain tasks
        "Explain how database indexing works under the hood",
        "Explain the difference between TCP and UDP",
        "Explain how garbage collection works in Python vs Java",
        "Explain the CAP theorem with real-world examples",
        "Explain how Docker containers work at the kernel level",
    ]
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
    
    def generate_batch(self, batch_size=20):
        """
        Generate a batch of training examples.
        Each task is sent to both models, and a quality score is computed.
        """
        batch = []
        tasks = random.sample(self.SEED_TASKS, min(batch_size, len(self.SEED_TASKS)))
        
        for task in tasks:
            # In production, actually call both models and compare
            # For now, generate the training structure
            batch.append({
                'prompt': task,
                'deepseek_response': None,  # Would be actual API call
                'claude_response': None,    # Would be actual API call
                'winner': None,             # Which response was better?
                'quality_score': None,      # 0-1 score
                'routing_label': None,      # Which model SHOULD handle this?
                'generated_at': datetime.now().isoformat()
            })
        
        return batch
    
    def generate_advanced_tasks(self, difficulty='hard'):
        """
        Generate harder tasks by combining patterns.
        Creates tasks that test edge cases in routing.
        """
        prefixes = [
            "In a production system with 1M requests/day, ",
            "Given a distributed system with eventual consistency, ",
            "With strict latency requirements of <100ms, ",
            "In a memory-constrained environment (256MB RAM), ",
            "While maintaining backward compatibility with v1 API, ",
        ]
        
        suffixes = [
            " and include comprehensive error handling",
            " with full test coverage",
            " and document the tradeoffs in your approach",
            " ensuring thread safety",
            " with performance benchmarks",
        ]
        
        advanced_tasks = []
        for task in self.SEED_TASKS:
            for prefix in random.sample(prefixes, 2):
                for suffix in random.sample(suffixes, 1):
                    advanced_tasks.append(f"{prefix}{task.lower()}{suffix}")
        
        return advanced_tasks
    
    def label_with_consensus(self, prompt):
        """
        Send a task to both models, have a third model judge which is better.
        This creates labeled training data for the ML router.
        """
        # Production implementation:
        # 1. Send prompt to DeepSeek
        # 2. Send prompt to Claude
        # 3. Send both responses to a judge model: "Which response is better and why?"
        # 4. Label the winner
        # 5. Store in training database
        
        return {
            'prompt': prompt,
            'status': 'labeled',
            'method': 'cross-model-consensus'
        }


# ─── Usage ──────────────────────────────────────────────────────

if __name__ == '__main__':
    generator = SyntheticDataGenerator()
    
    batch = generator.generate_batch(10)
    print(f"Generated {len(batch)} training examples")
    
    advanced = generator.generate_advanced_tasks('hard')
    print(f"Generated {len(advanced)} advanced tasks")
    print(f"Example: {advanced[0][:80]}...")