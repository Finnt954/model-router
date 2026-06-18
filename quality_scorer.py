"""
Response Quality Scoring
AI evaluates AI. Catches hallucinations before users see them.
"""

import re

class QualityScorer:
    """
    Scores AI responses on multiple dimensions.
    Flags low-quality responses for auto-retry or fallback.
    """
    
    # Patterns that indicate a bad response
    REFUSAL_PATTERNS = [
        r"i (apologize|can't|cannot|'m unable|'m not able|am not able)",
        r"(as an ai|as a language model|as an artificial intelligence)",
        r"(don't have|do not have) (access to|the ability)",
        r"(sorry|unfortunately),? (but|i|this)",
        r"(not capable|unable to|beyond my)",
        r"(against|violates) (my|openai|anthropic)",
    ]
    
    HALLUCINATION_PATTERNS = [
        r"function \w+\(\) doesn't exist",
        r"no such (method|function|class|module)",
        r"this (is|would be) (impossible|not possible|infeasible)",
        r"the (code|solution) (doesn't|does not) (work|run|compile)",
    ]
    
    INCOMPLETE_PATTERNS = [
        r"```$",  # Unclosed code block at end
        r"(to be continued|continued\.{3}|\.{4,})$",
        r"(here's the rest|continuing from|picking up where)",
    ]
    
    def score(self, response_text, expected_task_type=None):
        """
        Score a response on multiple dimensions.
        Returns a dict with scores and flags.
        """
        scores = {
            'overall': 1.0,
            'refusal_detected': False,
            'hallucination_detected': False,
            'incomplete_detected': False,
            'code_quality': 1.0,
            'explanation_quality': 1.0,
            'flags': []
        }
        
        if not response_text or len(response_text) < 10:
            scores['overall'] = 0.0
            scores['flags'].append('empty_response')
            return scores
        
        text_lower = response_text.lower()
        
        # Check for refusal patterns
        refusal_count = sum(1 for p in self.REFUSAL_PATTERNS if re.search(p, text_lower))
        if refusal_count >= 2:
            scores['refusal_detected'] = True
            scores['overall'] -= 0.5
            scores['flags'].append(f'refusal_patterns:{refusal_count}')
        
        # Check for hallucinations
        hallucination_count = sum(1 for p in self.HALLUCINATION_PATTERNS if re.search(p, text_lower))
        if hallucination_count > 0:
            scores['hallucination_detected'] = True
            scores['overall'] -= 0.4
            scores['flags'].append(f'hallucination_patterns:{hallucination_count}')
        
        # Check for incomplete responses
        incomplete_count = sum(1 for p in self.INCOMPLETE_PATTERNS if re.search(p, text_lower))
        if incomplete_count > 0:
            scores['incomplete_detected'] = True
            scores['overall'] -= 0.3
            scores['flags'].append('incomplete_response')
        
        # Score code quality
        code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', response_text, re.DOTALL)
        if code_blocks:
            scores['code_quality'] = self._score_code(code_blocks)
        
        # Score explanation quality
        text_only = re.sub(r'```.*?```', '', response_text, flags=re.DOTALL)
        scores['explanation_quality'] = self._score_explanation(text_only)
        
        # Overall is minimum of all scores
        scores['overall'] = min(
            scores['overall'],
            scores['code_quality'],
            scores['explanation_quality']
        )
        
        return scores
    
    def _score_code(self, code_blocks):
        """Score code quality: comments, error handling, tests."""
        if not code_blocks:
            return 1.0
        
        total_lines = sum(len(block.split('\n')) for block in code_blocks)
        
        score = 1.0
        
        # Has comments
        has_comments = any('//' in block or '#' in block for block in code_blocks)
        if not has_comments:
            score -= 0.1
        
        # Has error handling
        has_error_handling = any('try' in block or 'except' in block or 'catch' in block or 'error' in block.lower() for block in code_blocks)
        if not has_error_handling and total_lines > 20:
            score -= 0.1
        
        # Has type hints or docstrings
        has_types = any(': ' in block and 'def ' in block for block in code_blocks)
        if not has_types:
            score -= 0.05
        
        return max(score, 0.5)
    
    def _score_explanation(self, text):
        """Score explanation quality: structure, examples, clarity."""
        score = 1.0
        
        if len(text) < 50:
            score -= 0.3
        
        # Has bullet points or numbered steps
        has_structure = bool(re.search(r'[\n\r][\s]*[-*\d]+[.)]', text))
        if not has_structure:
            score -= 0.1
        
        # Has examples
        has_examples = bool(re.search(r'(for example|e\.g\.|example|instance)', text.lower()))
        if not has_examples:
            score -= 0.1
        
        return max(score, 0.4)
    
    def should_retry(self, scores, threshold=0.6):
        """Determine if the response should trigger a fallback/retry."""
        if scores['refusal_detected']:
            return True, "Model refused to answer"
        if scores['hallucination_detected']:
            return True, "Possible hallucination detected"
        if scores['incomplete_detected']:
            return True, "Response appears incomplete"
        if scores['overall'] < threshold:
            return True, f"Quality score too low ({scores['overall']:.2f})"
        return False, None


# ─── Singleton ──────────────────────────────────────────────────
quality_scorer = QualityScorer()