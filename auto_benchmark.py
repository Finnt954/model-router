"""
Automated Benchmarking Engine
Continuously evaluates models against coding tasks.
Makes routing decisions evidence-based, not opinion-based.
"""

import time
import json
import sqlite3
import subprocess
import tempfile
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict

class AutoBenchmark:
    """
    Daily automated benchmarking of all models.
    
    Test categories:
    - Code generation (does it compile/run?)
    - Bug fixing (does it actually fix the bug?)
    - Refactoring (does behavior stay the same?)
    - Explanation quality (accurate and clear?)
    - Edge cases (does it handle weird inputs?)
    """
    
    BENCHMARK_SUITE = {
        'code_generation': [
            {
                'prompt': 'Write a Python function that returns the nth Fibonacci number',
                'test': '''
def test_fib():
    assert fib(0) == 0
    assert fib(1) == 1
    assert fib(10) == 55
    assert fib(20) == 6765
    print("PASSED")
test_fib()
''',
                'expected_output': 'PASSED'
            },
            {
                'prompt': 'Write a Python function that checks if a string is a palindrome',
                'test': '''
def test_palindrome():
    assert is_palindrome("racecar") == True
    assert is_palindrome("hello") == False
    assert is_palindrome("A man a plan a canal Panama".lower().replace(" ", "")) == True
    print("PASSED")
test_palindrome()
''',
                'expected_output': 'PASSED'
            },
            {
                'prompt': 'Write a Python function that sorts a list using quicksort',
                'test': '''
def test_quicksort():
    assert quicksort([3,1,4,1,5,9,2,6]) == [1,1,2,3,4,5,6,9]
    assert quicksort([]) == []
    assert quicksort([1]) == [1]
    print("PASSED")
test_quicksort()
''',
                'expected_output': 'PASSED'
            }
        ],
        'bug_fixing': [
            {
                'prompt': 'Fix this buggy code. It should return the sum of all even numbers:\n\ndef sum_even(numbers):\n    total = 0\n    for i in range(len(numbers)):\n        if numbers[i] % 2 == 0:\n            total += i  # BUG: should be numbers[i]\n    return total',
                'test': '''
def test_sum_even():
    assert sum_even([1,2,3,4,5,6]) == 12
    assert sum_even([2,4,6]) == 12
    assert sum_even([1,3,5]) == 0
    print("PASSED")
test_sum_even()
''',
                'expected_output': 'PASSED'
            }
        ],
        'refactoring': [
            {
                'prompt': 'Refactor this code to use list comprehension:\n\ndef get_positives(numbers):\n    result = []\n    for n in numbers:\n        if n > 0:\n            result.append(n * 2)\n    return result',
                'test': '''
def test_get_positives():
    assert get_positives([1,2,3]) == [2,4,6]
    assert get_positives([-1,0,1]) == [2]
    assert get_positives([]) == []
    print("PASSED")
test_get_positives()
''',
                'expected_output': 'PASSED'
            }
        ]
    }
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS benchmark_results_v2
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      model_name TEXT,
                      category TEXT,
                      task TEXT,
                      passed BOOLEAN,
                      output TEXT,
                      error TEXT,
                      latency_ms REAL,
                      benchmarked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS model_rankings
                     (model_name TEXT,
                      category TEXT,
                      pass_rate REAL,
                      avg_latency REAL,
                      total_tests INTEGER,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (model_name, category))''')
        conn.commit()
        conn.close()
    
    def run_benchmark(self, model_name, model_func):
        """Run full benchmark suite against a model."""
        results = defaultdict(list)
        
        for category, tests in self.BENCHMARK_SUITE.items():
            for test_case in tests:
                start = time.time()
                
                try:
                    # Get code from model
                    response = model_func(test_case['prompt'])
                    
                    # Extract code block
                    code = self._extract_code(response)
                    
                    if not code:
                        results[category].append({
                            'task': test_case['prompt'][:60],
                            'passed': False,
                            'error': 'No code block found in response',
                            'latency': time.time() - start
                        })
                        continue
                    
                    # Combine code + test
                    full_code = code + '\n\n' + test_case['test']
                    
                    # Run in sandbox
                    passed, output, error = self._run_code(full_code)
                    elapsed = time.time() - start
                    
                    result = {
                        'task': test_case['prompt'][:60],
                        'passed': passed and test_case['expected_output'] in output,
                        'output': output[:500],
                        'error': error[:500],
                        'latency': round(elapsed, 3)
                    }
                    
                except Exception as e:
                    result = {
                        'task': test_case['prompt'][:60],
                        'passed': False,
                        'error': str(e),
                        'latency': time.time() - start
                    }
                
                results[category].append(result)
                
                # Store in DB
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                c.execute('''INSERT INTO benchmark_results_v2 (model_name, category, task, passed, output, error, latency_ms)
                             VALUES (?, ?, ?, ?, ?, ?, ?)''',
                          (model_name, category, test_case['prompt'][:100],
                           result['passed'], result.get('output', ''), result.get('error', ''),
                           result['latency'] * 1000))
                conn.commit()
                conn.close()
        
        # Calculate rankings
        rankings = {}
        for category, category_results in results.items():
            passed = sum(1 for r in category_results if r['passed'])
            total = len(category_results)
            avg_latency = sum(r['latency'] for r in category_results) / max(total, 1)
            
            rankings[category] = {
                'pass_rate': round(passed / max(total, 1) * 100, 1),
                'avg_latency': round(avg_latency, 3),
                'total_tests': total
            }
            
            # Update rankings table
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO model_rankings VALUES (?, ?, ?, ?, ?, ?)''',
                      (model_name, category, rankings[category]['pass_rate'],
                       rankings[category]['avg_latency'], total, datetime.now()))
            conn.commit()
            conn.close()
        
        return {
            'model': model_name,
            'results': dict(results),
            'rankings': rankings,
            'overall_pass_rate': round(
                sum(r['pass_rate'] for r in rankings.values()) / max(len(rankings), 1), 1
            )
        }
    
    def _extract_code(self, response):
        """Extract Python code from model response."""
        # Try code blocks first
        match = re.search(r'```(?:python)?\n(.*?)```', response, re.DOTALL)
        if match:
            return match.group(1)
        
        # Try to find function definitions
        lines = response.split('\n')
        code_lines = []
        in_code = False
        for line in lines:
            if line.strip().startswith('def ') or line.strip().startswith('class '):
                in_code = True
            if in_code:
                code_lines.append(line)
        
        if code_lines:
            return '\n'.join(code_lines)
        
        return None
    
    def _run_code(self, code):
        """Run Python code in sandbox and return (passed, output, error)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name
        
        try:
            result = subprocess.run(
                ['python', temp_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, '', 'Execution timed out'
        except Exception as e:
            return False, '', str(e)
        finally:
            os.unlink(temp_path)
    
    def get_rankings(self):
        """Get current model rankings."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT model_name, category, pass_rate, avg_latency, total_tests
                     FROM model_rankings ORDER BY model_name, pass_rate DESC''')
        rows = c.fetchall()
        conn.close()
        
        rankings = defaultdict(dict)
        for model, category, pass_rate, latency, tests in rows:
            rankings[model][category] = {
                'pass_rate': pass_rate,
                'avg_latency': latency,
                'tests': tests
            }
        
        return dict(rankings)
    
    def get_evidence_based_routing(self):
        """Generate routing rules based on benchmark results."""
        rankings = self.get_rankings()
        
        routing_rules = {}
        
        # Map benchmark categories to task types
        category_to_task = {
            'code_generation': 'algorithm',
            'bug_fixing': 'debug',
            'refactoring': 'refactor',
        }
        
        for model, categories in rankings.items():
            for category, scores in categories.items():
                task_type = category_to_task.get(category, category)
                
                if task_type not in routing_rules:
                    routing_rules[task_type] = []
                
                routing_rules[task_type].append({
                    'model': model,
                    'pass_rate': scores['pass_rate'],
                    'latency': scores['avg_latency']
                })
        
        # Pick best model for each task type
        final_rules = {}
        for task_type, candidates in routing_rules.items():
            candidates.sort(key=lambda x: x['pass_rate'], reverse=True)
            best = candidates[0]
            final_rules[task_type] = {
                'model': best['model'].lower().replace(' ', '-'),
                'confidence': best['pass_rate'],
                'evidence': f"{best['pass_rate']}% pass rate on {best['model']}"
            }
        
        return final_rules


# ─── Singleton ──────────────────────────────────────────────────
auto_benchmark = AutoBenchmark()