"""
Adversarial Routing Engine
Runs tasks through multiple models simultaneously and uses disagreement
as a signal for human review. Ensemble uncertainty for code generation.
"""

import json
import hashlib
from datetime import datetime

class AdversarialRouter:
    """
    When stakes are high, don't trust one model.
    Run through 2-3 models. If they disagree on security, require human review.
    """
    
    # High-stakes keywords that trigger adversarial review
    HIGH_STAKES_KEYWORDS = [
        'payment', 'credit card', 'password', 'authentication', 'authorization',
        'encryption', 'decrypt', 'api key', 'secret', 'token', 'credential',
        'production', 'deploy', 'database migration', 'schema change',
        'delete user', 'delete account', 'refund', 'transaction',
        'gdpr', 'hipaa', 'pii', 'personal data', 'ssn', 'social security'
    ]
    
    # Security-critical patterns to check for disagreement
    SECURITY_PATTERNS = [
        'sql', 'query', 'execute', 'injection',
        'password', 'hash', 'salt', 'bcrypt', 'argon',
        'csrf', 'xss', 'cors', 'sanitize', 'escape',
        'session', 'jwt', 'oauth', 'bearer',
        'permission', 'role', 'admin', 'access control'
    ]
    
    def __init__(self):
        self.reviews = []
    
    def should_adversarial_review(self, prompt):
        """
        Determine if a task needs adversarial review.
        High-stakes tasks trigger multi-model verification.
        """
        prompt_lower = prompt.lower()
        
        # Check for high-stakes keywords
        matches = [kw for kw in self.HIGH_STAKES_KEYWORDS if kw in prompt_lower]
        
        if matches:
            return {
                'review_required': True,
                'reason': f'High-stakes keywords detected: {", ".join(matches[:5])}',
                'risk_level': 'high' if len(matches) >= 3 else 'medium'
            }
        
        # Long complex prompts also get reviewed
        if len(prompt) > 500:
            return {
                'review_required': True,
                'reason': 'Complex task (>500 chars)',
                'risk_level': 'medium'
            }
        
        return {'review_required': False, 'reason': None, 'risk_level': 'low'}
    
    def run_adversarial_review(self, prompt, models=None):
        """
        Run the same task through multiple models.
        Compare outputs for security disagreements.
        """
        from router import call_model
        
        if models is None:
            # Use different model families for diversity
            models = [
                ('claude', 'Anthropic'),
                ('deepseek', 'DeepSeek'),
                ('qwen3-coder', 'Qwen')
            ]
        
        responses = {}
        for model_key, provider in models:
            try:
                response = call_model(model_key, prompt)
                responses[model_key] = {
                    'provider': provider,
                    'model': model_key,
                    'response': response[:3000],
                    'response_hash': hashlib.sha256(response.encode()).hexdigest()
                }
            except Exception as e:
                responses[model_key] = {
                    'provider': provider,
                    'model': model_key,
                    'error': str(e)
                }
        
        # Compare responses for disagreements
        disagreements = self._find_disagreements(responses, prompt)
        
        review = {
            'review_id': hashlib.sha256(f"{prompt}{datetime.now().isoformat()}".encode()).hexdigest()[:16],
            'timestamp': datetime.now().isoformat(),
            'prompt_preview': prompt[:200],
            'models_consulted': len(responses),
            'models_succeeded': sum(1 for r in responses.values() if 'error' not in r),
            'responses': responses,
            'disagreements': disagreements,
            'consensus': len(disagreements) == 0,
            'human_review_required': len(disagreements) > 0
        }
        
        self.reviews.append(review)
        return review
    
    def _find_disagreements(self, responses, prompt):
        """
        Find security-relevant disagreements between model outputs.
        Models disagreeing on security = human review required.
        """
        disagreements = []
        
        # Only compare if at least 2 models succeeded
        successful = {k: v for k, v in responses.items() if 'error' not in v}
        if len(successful) < 2:
            return disagreements
        
        model_names = list(successful.keys())
        
        # Compare each pair of models
        for i in range(len(model_names)):
            for j in range(i + 1, len(model_names)):
                m1 = model_names[i]
                m2 = model_names[j]
                resp1 = successful[m1]['response']
                resp2 = successful[m2]['response']
                
                # Check for security pattern disagreements
                for pattern in self.SECURITY_PATTERNS:
                    in_m1 = pattern.lower() in resp1.lower()
                    in_m2 = pattern.lower() in resp2.lower()
                    
                    # One model mentions a security pattern, the other doesn't
                    if in_m1 != in_m2:
                        disagreements.append({
                            'type': 'security_coverage',
                            'pattern': pattern,
                            'model_with': m1 if in_m1 else m2,
                            'model_without': m2 if in_m1 else m1,
                            'severity': 'high',
                            'detail': f"'{pattern}' mentioned by one model but not the other"
                        })
                
                # Check for different approaches to the same problem
                # If one uses parameterized queries and the other uses string formatting
                if ('parameterized' in resp1.lower() or 'prepared statement' in resp1.lower()) and \
                   ('f"' in resp2 or 'format(' in resp2 or '%s' in resp2):
                    disagreements.append({
                        'type': 'approach_divergence',
                        'pattern': 'sql_safety',
                        'model_safe': m1,
                        'model_risky': m2,
                        'severity': 'critical',
                        'detail': 'Models disagree on SQL safety approach'
                    })
        
        return disagreements
    
    def generate_verdict(self, review):
        """
        Generate a human-readable verdict from an adversarial review.
        """
        if review['consensus']:
            return {
                'verdict': 'CONSENSUS',
                'summary': f"All {review['models_consulted']} models agree. No human review needed.",
                'confidence': 'high'
            }
        
        critical = [d for d in review['disagreements'] if d['severity'] == 'critical']
        high = [d for d in review['disagreements'] if d['severity'] == 'high']
        
        return {
            'verdict': 'REVIEW_REQUIRED',
            'summary': f"{len(review['disagreements'])} disagreements found ({len(critical)} critical, {len(high)} high). Human review required.",
            'confidence': 'low',
            'critical_issues': critical,
            'high_issues': high
        }
    
    def get_review_history(self, limit=20):
        """Get recent adversarial reviews."""
        return self.reviews[-limit:]


# ─── Singleton ──────────────────────────────────────────────────
adversarial = AdversarialRouter()