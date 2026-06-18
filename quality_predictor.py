"""
Quality Prediction Engine
Predicts response quality BEFORE calling the model.
Skips expensive models when confidence is high on cheaper ones.
"""

import sqlite3
import json
import hashlib
from datetime import datetime
from collections import defaultdict

class QualityPredictor:
    """
    Predicts expected quality without making an API call.
    
    Uses:
    - Historical performance on similar prompts
    - Task complexity estimation
    - Model track record for this task type
    - Time of day effects on latency
    - User's past satisfaction with each model
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
    
    def predict_quality(self, prompt, model_key, task_type, user_id=None):
        """
        Predict quality score (0-1) for a model on this prompt.
        Returns predicted quality, confidence interval, and recommendation.
        """
        scores = {}
        
        # Factor 1: Historical model performance on this task type (40%)
        task_history = self._get_task_performance(model_key, task_type)
        scores['task_history'] = task_history * 0.4
        
        # Factor 2: Prompt complexity (30%)
        complexity = self._estimate_complexity(prompt)
        # Complex prompts benefit from better models
        complexity_score = 0.7 if complexity == 'high' else 0.5 if complexity == 'medium' else 0.4
        scores['complexity'] = complexity_score * 0.3
        
        # Factor 3: Model track record (20%)
        model_track = self._get_model_track_record(model_key)
        scores['track_record'] = model_track * 0.2
        
        # Factor 4: User preference (10%)
        if user_id:
            user_pref = self._get_user_preference(user_id, model_key)
            scores['user_preference'] = user_pref * 0.1
        else:
            scores['user_preference'] = 0.05
        
        predicted_quality = sum(scores.values())
        
        return {
            'model': model_key,
            'predicted_quality': round(predicted_quality, 2),
            'breakdown': {k: round(v, 2) for k, v in scores.items()},
            'recommendation': 'use' if predicted_quality > 0.5 else 'skip',
            'complexity': complexity
        }
    
    def _get_task_performance(self, model_key, task_type):
        """Get historical success rate for model on this task type."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT AVG(success_score) FROM routing_dataset 
                     WHERE model_used LIKE ? AND task_type = ? AND created_at > date('now', '-30 days')''',
                  (f'%{model_key}%', task_type))
        row = c.fetchone()
        conn.close()
        return row[0] if row[0] else 0.5  # Default neutral
    
    def _estimate_complexity(self, prompt):
        """Estimate task complexity from prompt characteristics."""
        score = 0
        
        # Long prompts = more complex
        if len(prompt) > 500: score += 2
        elif len(prompt) > 200: score += 1
        
        # Code in prompt = likely complex
        if '```' in prompt: score += 2
        
        # Multiple requirements
        if prompt.count(',') > 3 or prompt.count(' and ') > 2: score += 1
        
        # Advanced keywords
        advanced = ['optimize', 'scale', 'architecture', 'design', 'system', 'distributed', 'concurrent']
        score += sum(1 for w in advanced if w in prompt.lower())
        
        if score >= 4: return 'high'
        if score >= 2: return 'medium'
        return 'low'
    
    def _get_model_track_record(self, model_key):
        """Get overall model success rate."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT AVG(success_score) FROM routing_dataset 
                     WHERE model_used LIKE ? AND created_at > date('now', '-30 days')''',
                  (f'%{model_key}%',))
        row = c.fetchone()
        conn.close()
        return row[0] if row[0] else 0.5
    
    def _get_user_preference(self, user_id, model_key):
        """Get individual user's satisfaction with this model."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT AVG(success_score) FROM routing_dataset 
                     WHERE user_id = ? AND model_used LIKE ?''',
                  (user_id, f'%{model_key}%'))
        row = c.fetchone()
        conn.close()
        return row[0] if row[0] else 0.5
    
    def compare_models(self, prompt, task_type, models=None, user_id=None):
        """Compare predicted quality across models. Recommend best."""
        if models is None:
            models = ['deepseek', 'claude']
        
        predictions = []
        for model in models:
            pred = self.predict_quality(prompt, model, task_type, user_id)
            predictions.append(pred)
        
        predictions.sort(key=lambda x: x['predicted_quality'], reverse=True)
        
        best = predictions[0]
        cheapest = min(predictions, key=lambda x: 0.00028 if 'deepseek' in x['model'] else 0.003)
        
        # If cheapest is close enough to best, use cheapest
        if cheapest['model'] != best['model']:
            quality_gap = best['predicted_quality'] - cheapest['predicted_quality']
            if quality_gap < 0.15:  # Within 15% quality = use cheaper
                best = cheapest
                best['savings_note'] = 'Cheaper model nearly as good'
        
        return best


quality_predictor = QualityPredictor()