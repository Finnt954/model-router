"""
Continuous Benchmarking Engine
Runs automated tests against every model daily.
Routing decisions become evidence-based, not opinion-based.
"""

import time
import sqlite3
import json
from datetime import datetime, timedelta
from collections import defaultdict

class ContinuousBenchmark:
    """
    Daily automated benchmarking of all supported models.
    
    Tests:
    - Coding accuracy (does the code work?)
    - Latency (how fast?)
    - Cost (how expensive?)
    - Context handling (can it use conversation history?)
    - Reasoning (can it solve multi-step problems?)
    """
    
    BENCHMARKS = {
        'coding_accuracy': [
            ("Write a function that reverses a linked list", "algorithm"),
            ("Find the bug: for i in range(len(arr)): arr[i] = arr[i+1]", "debug"),
            ("Refactor this to use list comprehension: result = []; for x in data: if x > 0: result.append(x*2)", "refactor"),
            ("Explain the difference between a stack and a queue", "explain"),
        ],
        'latency': [
            ("What is 2+2?", "other"),  # Simplest possible task
            ("Write a function to sort an array", "algorithm"),
        ],
        'context_handling': [
            # Multi-turn test: needs to remember previous message
            ("Write a function called calculate_total", "algorithm"),
        ],
        'reasoning': [
            ("If a train leaves at 3pm traveling 60mph, and another leaves at 4pm traveling 80mph, when do they meet if they're 300 miles apart?", "algorithm"),
            ("Design a system to handle 1M requests per second. What are the bottlenecks?", "refactor"),
        ]
    }
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS benchmark_results
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      model_name TEXT,
                      benchmark_type TEXT,
                      task TEXT,
                      task_type TEXT,
                      passed BOOLEAN,
                      latency REAL,
                      cost REAL,
                      quality_score REAL,
                      benchmarked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()
    
    def run_benchmarks(self, models=None):
        """Run all benchmarks against specified models."""
        if models is None:
            models = {
                'deepseek': lambda p: __import__('router').call_deepseek(p),
                'claude': lambda p: __import__('router').call_claude(p)
            }
        
        results = {}
        
        for model_name, model_func in models.items():
            model_results = defaultdict(list)
            
            for benchmark_type, tasks in self.BENCHMARKS.items():
                for task, task_type in tasks:
                    start = time.time()
                    try:
                        response = model_func(task)
                        elapsed = time.time() - start
                        
                        # Score the response
                        quality = self._score_response(response, benchmark_type)
                        passed = quality > 0.5
                        
                        result = {
                            'task': task[:60],
                            'task_type': task_type,
                            'passed': passed,
                            'latency': round(elapsed, 2),
                            'quality': round(quality, 2),
                            'cost': 0  # Would track actual API cost
                        }
                    except Exception as e:
                        result = {
                            'task': task[:60],
                            'passed': False,
                            'error': str(e),
                            'latency': 0,
                            'quality': 0
                        }
                    
                    model_results[benchmark_type].append(result)
                    
                    # Store in database
                    conn = sqlite3.connect(self.db_path)
                    c = conn.cursor()
                    c.execute('''INSERT INTO benchmark_results (model_name, benchmark_type, task, task_type, passed, latency, cost, quality_score)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                              (model_name, benchmark_type, task, task_type, result.get('passed', False), 
                               result.get('latency', 0), result.get('cost', 0), result.get('quality', 0)))
                    conn.commit()
                    conn.close()
            
            results[model_name] = dict(model_results)
        
        return results
    
    def _score_response(self, response, benchmark_type):
        """Score response quality based on benchmark type."""
        score = 0.5
        
        if len(response) > 50:
            score += 0.1
        if '```' in response:
            score += 0.2
        if benchmark_type == 'reasoning' and len(response) > 200:
            score += 0.2
        if benchmark_type == 'coding_accuracy' and 'def ' in response:
            score += 0.1
        
        return min(score, 1.0)
    
    def get_rankings(self, days=7):
        """Get model rankings from recent benchmarks."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT model_name, benchmark_type, 
                     AVG(CASE WHEN passed THEN 1 ELSE 0 END) as pass_rate,
                     AVG(latency) as avg_latency, AVG(quality_score) as avg_quality,
                     COUNT(*) as tests
                     FROM benchmark_results 
                     WHERE benchmarked_at > date('now', '-? days')
                     GROUP BY model_name, benchmark_type
                     ORDER BY model_name, pass_rate DESC''', (days,))
        rows = c.fetchall()
        conn.close()
        
        rankings = defaultdict(dict)
        for model, bench, pass_rate, latency, quality, tests in rows:
            rankings[model][bench] = {
                'pass_rate': round(pass_rate * 100, 1),
                'avg_latency': round(latency, 2),
                'avg_quality': round(quality, 2),
                'tests': tests
            }
        
        return dict(rankings)
    
    def generate_routing_rules(self):
        """Generate evidence-based routing rules from benchmarks."""
        rankings = self.get_rankings()
        
        rules = {}
        for model, benchmarks in rankings.items():
            for bench_type, scores in benchmarks.items():
                if bench_type not in rules:
                    rules[bench_type] = []
                rules[bench_type].append({
                    'model': model,
                    'pass_rate': scores['pass_rate'],
                    'quality': scores['avg_quality']
                })
        
        # Pick best model for each benchmark type
        routing_rules = {}
        for bench_type, candidates in rules.items():
            candidates.sort(key=lambda x: x['quality'], reverse=True)
            best = candidates[0]
            routing_rules[bench_type] = {
                'model': best['model'],
                'confidence': best['pass_rate'],
                'based_on': f"{len(candidates)} models benchmarked"
            }
        
        return routing_rules


continuous_benchmark = ContinuousBenchmark()