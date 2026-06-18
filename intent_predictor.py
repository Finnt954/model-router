"""
Intent Prediction
Predicts what the user needs before they finish typing.
Enables instant responses for common patterns.
"""

import re
from collections import defaultdict

class IntentPredictor:
    """
    Predicts user intent from partial input.
    Used for pre-fetching and smart suggestions.
    """
    
    # Common patterns that predict task type with high confidence
    PATTERNS = {
        'debug': [
            (r"(?:fix|debug|resolve|patch)\s+(?:the\s+)?(?:bug|issue|error|problem)", 0.9),
            (r"(?:not\s+working|doesn't\s+work|isn't\s+working|broke)", 0.85),
            (r"(?:error|exception|traceback|stack\s+trace)", 0.85),
            (r"(?:why\s+(?:is|does|are)|what's\s+wrong)", 0.7),
        ],
        'algorithm': [
            (r"(?:write|implement|code|create|build)\s+(?:a\s+)?(?:function|algorithm|method|class)", 0.9),
            (r"(?:solve|solution|approach|how\s+to\s+solve)", 0.8),
            (r"(?:leetcode|hackerrank|codewars|challenge)", 0.95),
            (r"write\s+(?:me\s+)?(?:a\s+)?(?:python|javascript|java|rust|go)\s+(?:script|function|program)", 0.9),
        ],
        'refactor': [
            (r"(?:refactor|rewrite|restructure|reorganize|clean\s+up)", 0.9),
            (r"(?:improve|optimize)\s+(?:the\s+)?(?:code|performance|structure|readability)", 0.85),
            (r"(?:convert|migrate|upgrade)\s+(?:this|the|from)", 0.8),
            (r"(?:apply|use|implement)\s+(?:design\s+pattern|solid|dry)", 0.85),
        ],
        'explain': [
            (r"(?:explain|describe|elaborate|clarify|what\s+(?:is|are|does))", 0.9),
            (r"(?:how\s+(?:does|do|is|are|would|can|should))", 0.85),
            (r"(?:what's\s+the\s+difference|compare|versus|vs\.?)", 0.85),
            (r"(?:meaning|definition|concept|tutorial|guide|walkthrough)", 0.8),
        ],
    }
    
    def predict(self, partial_text, min_chars=10):
        """
        Predict task type from partial input.
        Returns (task_type, confidence) or (None, 0) if uncertain.
        """
        if len(partial_text) < min_chars:
            return None, 0
        
        text_lower = partial_text.lower()
        best_type = None
        best_confidence = 0
        
        for task_type, patterns in self.PATTERNS.items():
            for pattern, base_confidence in patterns:
                if re.search(pattern, text_lower):
                    # Boost confidence for longer inputs
                    confidence = min(base_confidence + (len(partial_text) / 500), 0.99)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_type = task_type
        
        return best_type, round(best_confidence, 2)
    
    def suggest_models(self, partial_text):
        """Suggest which models to pre-warm based on predicted intent."""
        task_type, confidence = self.predict(partial_text)
        
        if confidence < 0.7:
            return None
        
        suggestions = {
            'debug': ['deepseek'],
            'algorithm': ['deepseek'],
            'refactor': ['claude'],
            'explain': ['deepseek'],
        }
        
        return suggestions.get(task_type, ['deepseek'])


# ─── Singleton ──────────────────────────────────────────────────
intent_predictor = IntentPredictor()