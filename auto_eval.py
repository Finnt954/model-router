"""
Automated Model Evaluation Pipeline
Continuously benchmarks all available models against your test suite.
Alerts you when a new model beats the current champion.
"""

import json
import sqlite3
from datetime import datetime
from collections import defaultdict

class AutoEvaluator:
    """
    Runs your benchmark suite against all models automatically.
    Detects when a new model should be added to the router.
    """
    
    BENCHMARK_TASKS = {
        'algorithm': [
            "Write a function to reverse a linked list",
            "Implement a binary search tree with insert and find",
            "Write a function to detect cycles in a graph",
            "Implement quicksort in-place",
            "Write a function to find the longest palindromic substring",
        ],
        'debug': [
            "Fix the off-by-one error in this for loop",
            "Debug the null pointer exception in this code",
            "Find the memory leak in this Python script",
            "Fix the race condition in this multithreaded code",
            "Debug the SQL query returning wrong results",
        ],
        'refactor': [
            "Refactor this 100-line function into smaller units",
            "Apply the strategy pattern to this switch statement",
            "Convert callback-based code to async/await",
            "Extract an interface from this concrete class",
            "Apply dependency injection to remove tight coupling",
        ],
        'explain': [
            "Explain how garbage collection works in Python",
            "Explain the difference between TCP and UDP",
            "Explain how database indexing improves query performance",
            "Explain the CAP theorem with examples",
            "Explain how HTTPS encryption works",
        ]
    }
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS model_benchmarks
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      model_name TEXT,
                      task_type TEXT,
                      task_prompt TEXT,
                      passed BOOLEAN,
                      quality_score REAL,
                      latency REAL,
                      cost REAL,
                      benchmarked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()
    
    def evaluate_model(self, model_name, model_callable):
        """
        Run the full benchmark suite against a model.
        Returns aggregate scores across all task types.
        """
        results = defaultdict(list)
        
        for task_type, tasks in self.BENCHMARK_TASKS.items():
            for task in tasks:
                import time
                start = time.time()
                
                try:
                    response = model_callable(task)
                    elapsed = time.time() - start
                    
                    # Score the response quality
                    quality = self._score_quality(response, task_type)
                    
                    results[task_type].append({
                        'task': task[:50],
                        'passed': quality > 0.6,
                        'quality': quality,
                        'latency': round(elapsed, 2)
                    })
                    
                    # Store in database
                    conn = sqlite3.connect(self.db_path)
                    c = conn.cursor()
                    c.execute('''INSERT INTO model_benchmarks 
                                 (model_name, task_type, task_prompt, passed, quality_score, latency, cost)
                                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
                              (model_name, task_type, task, quality > 0.6, quality, elapsed, 0))
                    conn.commit()
                    conn.close()
                    
                except Exception as e:
                    results[task_type].append({
                        'task': task[:50],
                        'passed': False,
                        'quality': 0,
                        'error': str(e)
                    })
        
        # Aggregate results
        summary = {}
        for task_type, task_results in results.items():
            passed = [r for r in task_results if r['passed']]
            summary[task_type] = {
                'pass_rate': round(len(passed) / max(len(task_results), 1) * 100, 1),
                'avg_quality': round(sum(r['quality'] for r in task_results) / max(len(task_results), 1), 2),
                'avg_latency': round(sum(r.get('latency', 0) for r in task_results) / max(len(task_results), 1), 2),
                'total_tasks': len(task_results)
            }
        
        return {
            'model': model_name,
            'summary': summary,
            'overall_pass_rate': round(
                sum(s['pass_rate'] for s in summary.values()) / max(len(summary), 1), 1
            ),
            'benchmarked_at': datetime.now().isoformat()
        }
    
    def _score_quality(self, response, task_type):
        """Score response quality heuristically."""
        score = 0.5  # Start neutral
        
        if len(response) > 100:
            score += 0.1
        if '```' in response:
            score += 0.2
        if task_type == 'refactor' and 'class' in response.lower():
            score += 0.1
        if task_type == 'debug' and ('error' in response.lower() or 'fix' in response.lower()):
            score += 0.1
        if task_type == 'explain' and ('example' in response.lower() or 'because' in response.lower()):
            score += 0.1
        
        return min(score, 1.0)
    
    def get_rankings(self):
        """Get current model rankings across all benchmarks."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT model_name, task_type, 
                     AVG(CASE WHEN passed THEN 1 ELSE 0 END) as pass_rate,
                     AVG(quality_score) as avg_quality,
                     AVG(latency) as avg_latency
                     FROM model_benchmarks
                     WHERE benchmarked_at > date('now', '-7 days')
                     GROUP BY model_name, task_type
                     ORDER BY model_name, pass_rate DESC''')
        rows = c.fetchall()
        conn.close()
        
        rankings = defaultdict(dict)
        for model, task, pass_rate, quality, latency in rows:
            rankings[model][task] = {
                'pass_rate': round(pass_rate * 100, 1),
                'quality': round(quality, 2),
                'latency': round(latency, 2)
            }
        
        return dict(rankings)
    
    def detect_new_champion(self, new_model_results, current_best='deepseek'):
        """Alert when a new model beats the current champion."""
        current_scores = self.get_rankings().get(current_best, {})
        
        improvements = []
        for task_type, results in new_model_results['summary'].items():
            current = current_scores.get(task_type, {})
            current_pass = current.get('pass_rate', 0)
            new_pass = results['pass_rate']
            
            if new_pass > current_pass + 5:  # 5% improvement threshold
                improvements.append({
                    'task_type': task_type,
                    'current': current_pass,
                    'new': new_pass,
                    'improvement': round(new_pass - current_pass, 1)
                })
        
        if improvements:
            return {
                'alert': 'NEW_CHAMPION_DETECTED',
                'model': new_model_results['model'],
                'improvements': improvements,
                'recommendation': 'Add to routing table immediately'
            }
        
        return {'alert': 'no_significant_improvement'}


# ─── Singleton ──────────────────────────────────────────────────
auto_evaluator = AutoEvaluator()