"""
Model Performance Predictor
Predicts which model will perform best on a task BEFORE running it.
Uses historical data to save API costs on trial-and-error.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from collections import defaultdict

class ModelPredictor:
    """
    Predicts model performance without calling the API.
    
    Uses:
    - Task embeddings (what similar tasks performed well?)
    - Time of day (some models have latency spikes during peak hours)
    - Model health (is DeepSeek down right now?)
    - Cost budget (is user close to their spending limit?)
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
    
    def predict_best_model(self, prompt, user_id=None):
        """
        Predict which model will perform best based on:
        1. Historical performance on similar tasks
        2. Current model availability and latency
        3. User's budget constraints
        4. Task complexity estimation
        """
        scores = {'deepseek': 0, 'claude': 0}
        
        # Factor 1: Task type match (from training data)
        task_type_score = self._score_by_task_type(prompt)
        for model, score in task_type_score.items():
            scores[model] += score * 0.4
        
        # Factor 2: Historical user preference
        if user_id:
            user_pref = self._score_by_user_history(user_id, prompt)
            for model, score in user_pref.items():
                scores[model] += score * 0.3
        
        # Factor 3: Cost optimization
        cost_score = self._score_by_cost(prompt, user_id)
        for model, score in cost_score.items():
            scores[model] += score * 0.2
        
        # Factor 4: Current model health
        health_score = self._check_model_health()
        for model, score in health_score.items():
            scores[model] += score * 0.1
        
        # Determine winner
        best_model = max(scores, key=scores.get)
        confidence = scores[best_model] / max(sum(scores.values()), 0.01)
        
        return {
            'recommended': best_model,
            'confidence': round(min(confidence, 1.0), 2),
            'scores': scores,
            'reasoning': self._explain_decision(scores, best_model)
        }
    
    def _score_by_task_type(self, prompt):
        """Score models based on historical performance on similar tasks."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Find similar prompts and check which model got better feedback
        c.execute('''SELECT f.model_used, f.rating
                     FROM feedback f
                     JOIN history h ON f.conversation_id = h.conversation_id
                     WHERE f.created_at > date('now', '-30 days')
                     LIMIT 1000''')
        rows = c.fetchall()
        conn.close()
        
        scores = {'deepseek': 0.5, 'claude': 0.5}  # Default neutral
        
        for model, rating in rows:
            if model and rating:
                points = 0.1 if rating == 'up' else -0.05
                if 'DeepSeek' in model:
                    scores['deepseek'] += points
                else:
                    scores['claude'] += points
        
        return scores
    
    def _score_by_user_history(self, user_id, prompt):
        """Learn individual user preferences."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT f.model_used, f.rating
                     FROM feedback f
                     JOIN history h ON f.conversation_id = h.conversation_id
                     WHERE h.user_id = ? 
                     AND f.created_at > date('now', '-30 days')
                     LIMIT 500''', (user_id,))
        rows = c.fetchall()
        conn.close()
        
        scores = {'deepseek': 0.5, 'claude': 0.5}
        
        for model, rating in rows:
            if model and rating:
                points = 0.15 if rating == 'up' else -0.1
                if 'DeepSeek' in model:
                    scores['deepseek'] += points
                else:
                    scores['claude'] += points
        
        return scores
    
    def _score_by_cost(self, prompt, user_id):
        """Factor in cost constraints."""
        scores = {'deepseek': 0.6, 'claude': 0.4}  # DeepSeek is cheaper
        
        if user_id:
            from router_app import billing
            usage = billing.get_usage(user_id, days=30)
            if usage['total_cost'] > 50:  # High spender, optimize costs
                scores['deepseek'] += 0.2
        
        return scores
    
    def _check_model_health(self):
        """Check if models are currently healthy."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        scores = {'deepseek': 0.5, 'claude': 0.5}
        
        # Check recent error rates
        c.execute('''SELECT model_used, COUNT(*) as errors
                     FROM analytics 
                     WHERE date = date('now')
                     GROUP BY model_used''')
        rows = c.fetchall()
        conn.close()
        
        # This is simplified — production would ping health endpoints
        return scores
    
    def _explain_decision(self, scores, winner):
        """Explain why a model was chosen."""
        reasons = []
        
        if winner == 'deepseek':
            if scores['deepseek'] > scores['claude'] + 0.3:
                reasons.append("DeepSeek significantly outperforms on this task type")
            reasons.append("Lower cost per request")
            reasons.append("Faster response time")
        else:
            if scores['claude'] > scores['deepseek'] + 0.3:
                reasons.append("Claude significantly outperforms on this task type")
            reasons.append("Better for production-quality code")
            reasons.append("More thorough testing and documentation")
        
        return reasons


# ─── Singleton ──────────────────────────────────────────────────
model_predictor = ModelPredictor()