"""
Router Fine-Tuning Pipeline
Trains a custom model on your feedback data to replace keyword-based routing.
This creates a defensible moat — nobody else has your routing data.
"""

import sqlite3
import json
import numpy as np
from datetime import datetime
from collections import Counter

class RouterTrainer:
    """
    Trains a custom classifier on feedback data.
    Start with logistic regression, graduate to a transformer when you have 10K+ samples.
    """
    
    def __init__(self, db_path='router.db'):
        self.db_path = db_path
        self.model = None
        self.feature_names = None
    
    def load_training_data(self, min_samples=50):
        """
        Load all feedback-labeled prompts from the database.
        Only trains on prompts where users gave feedback (up/down).
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Get all rated conversations with their prompts
        c.execute('''
            SELECT h.content, f.rating, f.model_used, h.task_type
            FROM feedback f
            JOIN history h ON f.conversation_id = h.conversation_id
            WHERE f.rating IS NOT NULL 
            AND h.role = 'user'
            AND h.content IS NOT NULL
            ORDER BY h.created_at DESC
            LIMIT 10000
        ''')
        
        rows = c.fetchall()
        conn.close()
        
        if len(rows) < min_samples:
            print(f"Need {min_samples} samples, have {len(rows)}. Keep collecting feedback.")
            return None, None
        
        # Build training data
        X = []  # Features
        y = []  # Labels (which model was best)
        
        for content, rating, model_used, task_type in rows:
            features = self._extract_features(content)
            X.append(features)
            # If user said "helpful", that model was correct for this task
            if rating == 'up':
                y.append(model_used)
            else:
                # If "not helpful", the OTHER model would have been better
                y.append('Claude Sonnet 4.6' if 'DeepSeek' in model_used else 'DeepSeek V3')
        
        self.feature_names = list(X[0].keys())
        return np.array([[f[k] for k in self.feature_names] for f in X]), np.array(y)
    
    def _extract_features(self, prompt):
        """Convert prompt to numerical features. More features = better accuracy."""
        pl = prompt.lower()
        words = pl.split()
        
        return {
            # Task indicators
            'debug_words': sum(1 for w in ['fix', 'bug', 'error', 'broken', 'debug', 'failing'] if w in pl),
            'refactor_words': sum(1 for w in ['refactor', 'clean', 'improve', 'optimize', 'restructure'] if w in pl),
            'explain_words': sum(1 for w in ['explain', 'what does', 'how does', 'why', 'understand'] if w in pl),
            'algorithm_words': sum(1 for w in ['implement', 'build', 'create', 'write', 'algorithm'] if w in pl),
            
            # Complexity indicators (harder tasks -> Claude)
            'prompt_length': len(prompt),
            'word_count': len(words),
            'has_code_block': 1 if '```' in prompt else 0,
            'has_error_trace': 1 if 'traceback' in pl or 'error:' in pl else 0,
            'has_specific_line': 1 if any(c.isdigit() for c in prompt[-50:]) else 0,
            
            # Language indicators
            'question_marks': prompt.count('?'),
            'exclamation_marks': prompt.count('!'),
            'uppercase_ratio': sum(1 for c in prompt if c.isupper()) / max(len(prompt), 1),
            
            # Context indicators
            'has_file_path': 1 if '/' in prompt or '\\' in prompt else 0,
            'has_function_name': 1 if 'def ' in pl or 'function ' in pl else 0,
            'has_class_name': 1 if 'class ' in pl else 0,
        }
    
    def train(self):
        """Train the model. Returns accuracy metrics."""
        X, y = self.load_training_data()
        
        if X is None:
            return None
        
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score
        
        self.model = LogisticRegression(max_iter=1000, class_weight='balanced')
        
        # Cross-validate to measure accuracy
        scores = cross_val_score(self.model, X, y, cv=5)
        
        # Train on full dataset
        self.model.fit(X, y)
        
        return {
            'accuracy': round(scores.mean() * 100, 1),
            'std_dev': round(scores.std() * 100, 1),
            'samples': len(X),
            'features': len(self.feature_names),
            'trained_at': datetime.now().isoformat()
        }
    
    def predict(self, prompt):
        """Predict best model for a prompt. Returns (model_key, confidence)."""
        if self.model is None:
            return None, 0
        
        features = self._extract_features(prompt)
        X = np.array([[features[k] for k in self.feature_names]])
        
        probabilities = self.model.predict_proba(X)[0]
        prediction = self.model.predict(X)[0]
        confidence = max(probabilities)
        
        # Map model name to key
        model_map = {
            'DeepSeek V3': 'deepseek',
            'Claude Sonnet 4.6': 'claude'
        }
        
        return model_map.get(prediction, 'deepseek'), round(confidence, 2)
    
    def save(self, filepath='router_model.pkl'):
        """Save trained model to disk."""
        import pickle
        with open(filepath, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'feature_names': self.feature_names
            }, f)
        print(f"Model saved to {filepath}")
    
    def load(self, filepath='router_model.pkl'):
        """Load trained model from disk."""
        import pickle
        try:
            with open(filepath, 'rb') as f:
                data = pickle.load(f)
            self.model = data['model']
            self.feature_names = data['feature_names']
            print(f"Model loaded from {filepath}")
            return True
        except FileNotFoundError:
            print("No trained model found. Train first with .train()")
            return False


# ─── Usage ──────────────────────────────────────────────────────

if __name__ == '__main__':
    trainer = RouterTrainer()
    
    # Train the model
    metrics = trainer.train()
    if metrics:
        print(f"\nTraining Results:")
        print(f"  Accuracy: {metrics['accuracy']}%")
        print(f"  Samples:  {metrics['samples']}")
        print(f"  Features: {metrics['features']}")
        
        # Save it
        trainer.save()
        
        # Test predictions
        tests = [
            "Fix the null pointer bug in the login handler",
            "Write a binary search implementation in Python",
            "Refactor the authentication module to use dependency injection",
            "Explain how garbage collection works in Python"
        ]
        
        print("\nTest Predictions:")
        for t in tests:
            model, conf = trainer.predict(t)
            print(f"  '{t[:50]}...' → {model} ({conf:.0%} confidence)")
    else:
        print("Not enough training data yet. Keep collecting user feedback.")