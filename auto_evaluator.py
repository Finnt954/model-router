"""
Autonomous Evaluation Engine
Every response gets graded automatically.
Scores feed back into routing to continuously improve.
"""

import re
import sqlite3
from datetime import datetime

class AutoEvaluator:
    """
    Grades every AI response automatically on multiple dimensions.
    
    Dimensions:
    - Correctness: Does the code look like it would work?
    - Completeness: Did it fully answer the question?
    - Clarity: Is it well-explained?
    - Efficiency: Is the solution optimal?
    - Safety: Are there obvious security issues?
    """
    
    def evaluate(self, prompt, response, task_type, model_used):
        """Grade a response and return a detailed scorecard."""
        scores = {}
        
        # Dimension 1: Correctness (25%)
        scores['correctness'] = self._score_correctness(prompt, response, task_type)
        
        # Dimension 2: Completeness (25%)
        scores['completeness'] = self._score_completeness(prompt, response)
        
        # Dimension 3: Clarity (20%)
        scores['clarity'] = self._score_clarity(response)
        
        # Dimension 4: Efficiency (15%)
        scores['efficiency'] = self._score_efficiency(response, task_type)
        
        # Dimension 5: Safety (15%)
        scores['safety'] = self._score_safety(response)
        
        # Overall score
        weights = {'correctness': 0.25, 'completeness': 0.25, 'clarity': 0.20, 'efficiency': 0.15, 'safety': 0.15}
        overall = sum(scores[k] * weights[k] for k in weights)
        
        return {
            'overall': round(overall, 2),
            'dimensions': scores,
            'grade': self._letter_grade(overall),
            'evaluated_at': datetime.now().isoformat()
        }
    
    def _score_correctness(self, prompt, response, task_type):
        """Does the response appear correct?"""
        score = 0.5
        
        # Has code
        if '```' in response: score += 0.2
        
        # Code looks runnable
        if 'def ' in response or 'function ' in response or 'class ' in response:
            score += 0.1
        
        # No obvious errors in code
        error_patterns = ['undefined', 'null pointer', 'syntax error', 'does not exist']
        if not any(p in response.lower() for p in error_patterns):
            score += 0.1
        
        # Addresses the specific task
        if task_type == 'debug' and ('fix' in response.lower() or 'bug' in response.lower()):
            score += 0.1
        if task_type == 'refactor' and ('class' in response.lower() or 'function' in response.lower()):
            score += 0.1
        
        return min(score, 1.0)
    
    def _score_completeness(self, prompt, response):
        """Did it fully answer the question?"""
        score = 0.5
        
        # Adequate length
        if len(response) > 200: score += 0.2
        if len(response) > 500: score += 0.1
        
        # Has explanation AND code
        has_code = '```' in response
        has_text = len(re.sub(r'```.*?```', '', response, flags=re.DOTALL).strip()) > 50
        if has_code and has_text: score += 0.1
        
        # Doesn't end mid-sentence
        if response.rstrip().endswith(('.', ')', '}', '`')):
            score += 0.1
        
        return min(score, 1.0)
    
    def _score_clarity(self, response):
        """Is it well-explained?"""
        score = 0.5
        
        # Structured with sections
        if response.count('\n\n') > 2: score += 0.1
        
        # Has examples
        if 'example' in response.lower() or 'e.g.' in response.lower():
            score += 0.1
        
        # Uses bullet points or numbered steps
        if re.search(r'[\n][\s]*[\-\d]+[.)]\s', response):
            score += 0.1
        
        # Code has comments
        if '# ' in response or '// ' in response:
            score += 0.1
        
        # Readable length (not a wall of text)
        paragraphs = [p for p in response.split('\n\n') if len(p) > 50]
        if 2 <= len(paragraphs) <= 10:
            score += 0.1
        
        return min(score, 1.0)
    
    def _score_efficiency(self, response, task_type):
        """Is the solution efficient?"""
        if task_type not in ['algorithm', 'refactor']:
            return 0.7  # Not applicable, neutral score
        
        score = 0.5
        
        # Mentions complexity
        complexity_terms = ['O(n)', 'O(log n)', 'O(1)', 'time complexity', 'space complexity']
        if any(t in response for t in complexity_terms):
            score += 0.3
        
        # Uses appropriate data structures
        efficient_structures = ['set', 'dict', 'hash', 'heap', 'tree', 'cache']
        if any(s in response.lower() for s in efficient_structures):
            score += 0.1
        
        # Avoids obviously inefficient patterns
        inefficient = ['for i in range(len(']
        if not any(p in response for p in inefficient):
            score += 0.1
        
        return min(score, 1.0)
    
    def _score_safety(self, response):
        """Are there obvious security issues?"""
        score = 1.0  # Start perfect, deduct for issues
        
        # Hardcoded secrets
        if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', response):
            score -= 0.3
        
        # SQL injection vulnerable patterns
        if re.search(r'f".*SELECT.*\{"', response) or re.search(r'f".*INSERT.*\{"', response):
            score -= 0.3
        
        # Unsafe eval
        if 'eval(' in response:
            score -= 0.2
        
        # No input validation
        if 'def ' in response and 'if ' not in response and 'raise ' not in response:
            score -= 0.1
        
        return max(score, 0.0)
    
    def _letter_grade(self, score):
        if score >= 0.9: return 'A'
        if score >= 0.8: return 'B'
        if score >= 0.7: return 'C'
        if score >= 0.6: return 'D'
        return 'F'
    
    def evaluate_and_store(self, prompt, response, task_type, model_used, conversation_id=None):
        """Evaluate response and store score for future routing improvements."""
        evaluation = self.evaluate(prompt, response, task_type, model_used)
        
        # Store in database for routing dataset
        conn = sqlite3.connect('router.db')
        c = conn.cursor()
        c.execute('''UPDATE routing_dataset 
                     SET quality_score = ? 
                     WHERE prompt = ? AND model_used = ?
                     AND created_at > datetime('now', '-1 hour')
                     ORDER BY created_at DESC LIMIT 1''',
                  (evaluation['overall'], prompt[:1000], model_used))
        conn.commit()
        conn.close()
        
        return evaluation


auto_evaluator = AutoEvaluator()