"""
Unified Evaluator — Quality scoring + outcome tracking in one module.
"""

import sqlite3
import re
from datetime import datetime

class Evaluator:
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
    
    def score_response(self, prompt, response, task_type, model_used):
        """Score response quality on 3 dimensions. Returns 0-1."""
        scores = {}
        scores['correctness'] = self._score_correctness(response, task_type)
        scores['completeness'] = self._score_completeness(response)
        scores['safety'] = self._score_safety(response)
        overall = round((scores['correctness'] * 0.5 + scores['completeness'] * 0.3 + scores['safety'] * 0.2), 2)
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''UPDATE routing_dataset_v2 SET quality_score = ? 
                     WHERE prompt_preview = ? AND model_selected = ?
                     ORDER BY created_at DESC LIMIT 1''',
                  (overall, prompt[:200], model_used))
        conn.commit()
        conn.close()
        
        return {'overall': overall, 'dimensions': scores}
    
    def _score_correctness(self, response, task_type):
        score = 0.5
        if '```' in response: score += 0.2
        if 'def ' in response or 'function ' in response: score += 0.1
        error_patterns = ['undefined', 'null pointer', 'syntax error']
        if not any(p in response.lower() for p in error_patterns): score += 0.1
        if task_type == 'debug' and 'fix' in response.lower(): score += 0.1
        return min(score, 1.0)
    
    def _score_completeness(self, response):
        score = 0.5
        if len(response) > 200: score += 0.2
        has_code = '```' in response
        has_text = len(re.sub(r'```.*?```', '', response, flags=re.DOTALL).strip()) > 50
        if has_code and has_text: score += 0.2
        if response.rstrip().endswith(('.', ')', '}', '`')): score += 0.1
        return min(score, 1.0)
    
    def _score_safety(self, response):
        score = 1.0
        if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', response): score -= 0.3
        if 'eval(' in response: score -= 0.3
        if re.search(r'f".*SELECT.*\{', response): score -= 0.3
        return max(score, 0.0)
    
    def analyze_conversation(self, conversation_id):
        """Analyze conversation outcomes from user behavior."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT role, content, model_used FROM history WHERE conversation_id = ? ORDER BY created_at ASC', (conversation_id,))
        messages = c.fetchall()
        conn.close()
        
        if len(messages) < 2:
            return None
        
        outcomes = []
        for i in range(0, len(messages) - 1, 2):
            if i + 1 >= len(messages): break
            user_msg, ai_msg = messages[i], messages[i + 1]
            if user_msg[0] != 'user' or ai_msg[0] != 'assistant': continue
            
            has_code = '```' in (ai_msg[1] or '')
            no_refusal = not any(p in (ai_msg[1] or '').lower() for p in ['i apologize', 'i cannot', 'unable to'])
            is_followup = False
            if i + 2 < len(messages):
                next_msg = messages[i + 2]
                is_followup = any(w in (next_msg[1] or '').lower() for w in ['still not', 'error', 'actually'])
            
            success = (has_code and no_refusal and not is_followup)
            outcomes.append({'success': success, 'model': ai_msg[2], 'has_code': has_code})
        
        return outcomes


evaluator = Evaluator()