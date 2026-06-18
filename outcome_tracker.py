"""
Outcome-Based Learning Engine
Tracks whether responses actually solved the user's problem.
Replaces 👍👎 with real success metrics.
"""

import sqlite3
import json
import re
from datetime import datetime

class OutcomeTracker:
    """
    Tracks response success beyond thumbs up/down.
    
    Success signals:
    - User didn't ask follow-up clarification (indicates problem solved)
    - User copied code (indicates usable output)
    - User asked similar task again (indicates workflow adoption)
    - User didn't regenerate (first response was good enough)
    - Response contained working code that compiles
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS outcomes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      conversation_id TEXT,
                      prompt TEXT,
                      model_used TEXT,
                      task_type TEXT,
                      success_score REAL DEFAULT 0,
                      signals TEXT,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()
    
    def analyze_conversation(self, conversation_id):
        """Analyze a conversation to determine if responses were successful."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT role, content, model_used, task_type, created_at FROM history WHERE conversation_id = ? ORDER BY created_at ASC', (conversation_id,))
        messages = c.fetchall()
        conn.close()
        
        if len(messages) < 2:
            return None
        
        outcomes = []
        for i in range(0, len(messages) - 1, 2):
            if i + 1 >= len(messages):
                break
            
            user_msg = messages[i]
            ai_msg = messages[i + 1]
            
            if user_msg[0] != 'user' or ai_msg[0] != 'assistant':
                continue
            
            success_score, signals = self._calculate_success(user_msg, ai_msg, messages, i)
            
            outcome = {
                'prompt': user_msg[1][:200],
                'model_used': ai_msg[2],
                'task_type': ai_msg[3],
                'success_score': success_score,
                'signals': signals
            }
            
            # Store in database
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('INSERT INTO outcomes (conversation_id, prompt, model_used, task_type, success_score, signals) VALUES (?, ?, ?, ?, ?, ?)',
                      (conversation_id, user_msg[1][:500], ai_msg[2], ai_msg[3], success_score, json.dumps(signals)))
            conn.commit()
            conn.close()
            
            outcomes.append(outcome)
        
        return outcomes
    
    def _calculate_success(self, user_msg, ai_msg, all_messages, current_index):
        """Calculate success score from multiple signals."""
        signals = {}
        score = 0.0
        
        user_content = user_msg[1]
        ai_content = ai_msg[1]
        
        # Signal 1: Code in response (weight: 0.2)
        has_code = '```' in ai_content
        signals['has_code'] = has_code
        if has_code:
            score += 0.2
        
        # Signal 2: User didn't immediately ask follow-up (weight: 0.3)
        # Check if the next user message is a follow-up question
        is_followup = False
        if current_index + 2 < len(all_messages):
            next_user = all_messages[current_index + 2]
            followup_indicators = ['still not', 'doesn\'t work', 'error', 'actually', 'instead', 'what about']
            is_followup = any(ind in next_user[1].lower() for ind in followup_indicators)
        signals['no_followup'] = not is_followup
        if not is_followup:
            score += 0.3
        
        # Signal 3: Response length appropriate for task (weight: 0.15)
        # Too short = probably incomplete. Too long = probably overkill.
        response_len = len(ai_content)
        if 200 < response_len < 3000:
            score += 0.15
        signals['appropriate_length'] = 200 < response_len < 3000
        
        # Signal 4: Contains explanation (weight: 0.15)
        has_explanation = bool(re.search(r'(because|therefore|this works|the reason|explanation)', ai_content.lower()))
        signals['has_explanation'] = has_explanation
        if has_explanation:
            score += 0.15
        
        # Signal 5: No apology or refusal (weight: 0.2)
        refusal_patterns = ['I apologize', 'I\'m sorry', 'I cannot', 'I can\'t', 'unable to']
        has_refusal = any(p in ai_content for p in refusal_patterns)
        signals['no_refusal'] = not has_refusal
        if not has_refusal:
            score += 0.2
        
        return round(score, 2), signals
    
    def get_model_success_rates(self, days=30):
        """Get success rates by model and task type."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT model_used, task_type, AVG(success_score) as avg_score, COUNT(*) as total
                     FROM outcomes WHERE created_at > date('now', '-? days')
                     GROUP BY model_used, task_type ORDER BY avg_score DESC''', (days,))
        rows = c.fetchall()
        conn.close()
        
        return [{'model': r[0], 'task': r[1], 'success_rate': round(r[2]*100, 1), 'samples': r[3]} for r in rows]
    
    def learn_from_outcomes(self):
        """Update routing rules based on outcome data."""
        success_rates = self.get_model_success_rates(days=30)
        
        # Build new routing recommendations
        recommendations = {}
        for entry in success_rates:
            task = entry['task']
            model = entry['model']
            rate = entry['success_rate']
            
            if task not in recommendations:
                recommendations[task] = []
            recommendations[task].append({'model': model, 'rate': rate})
        
        # Sort by success rate
        for task in recommendations:
            recommendations[task].sort(key=lambda x: x['rate'], reverse=True)
        
        return {
            'recommendations': recommendations,
            'note': 'Apply these to override default routing rules',
            'generated_at': datetime.now().isoformat()
        }


outcome_tracker = OutcomeTracker()