"""
Multi-Step Routing Engine
Instead of: classify → choose model
Do: classify → estimate complexity → estimate risk → choose workflow → choose model
"""

class MultiStepRouter:
    """
    Sophisticated routing that considers multiple factors before choosing a model.
    
    Workflow:
    1. Classify task type
    2. Estimate complexity
    3. Estimate risk (what if the model fails?)
    4. Choose workflow (single model, consensus, or iterative?)
    5. Choose model(s)
    6. Set fallback strategy
    """
    
    RISK_LEVELS = {
        'low': 'Simple task, low stakes. Use fastest/cheapest model.',
        'medium': 'Moderate complexity. Use best model for task type.',
        'high': 'Complex or critical. Use consensus or best available.',
        'critical': 'Production-critical. Triple consensus + human review.'
    }
    
    WORKFLOWS = {
        'simple': 'Single model, no fallback needed',
        'standard': 'Single model with automatic fallback',
        'consensus': '3 models, majority vote',
        'iterative': 'Generate → test → fix → retest → deliver'
    }
    
    def route(self, prompt, user_id=None, is_critical=False):
        """Full multi-step routing decision."""
        
        # Step 1: Classify
        from router import route_task
        plan = route_task(prompt)
        task_type = plan['task_type']
        
        # Step 2: Estimate complexity
        complexity = self._estimate_complexity(prompt)
        
        # Step 3: Estimate risk
        risk = self._estimate_risk(prompt, task_type, is_critical)
        
        # Step 4: Choose workflow
        workflow = self._choose_workflow(complexity, risk, task_type)
        
        # Step 5: Choose model
        model = self._choose_model(task_type, complexity, risk, user_id)
        
        # Step 6: Set fallback
        fallback = self._set_fallback(model, risk)
        
        return {
            'task_type': task_type,
            'complexity': complexity,
            'risk': risk,
            'workflow': workflow,
            'model': model,
            'fallback': fallback,
            'explanation': self._explain_decision(task_type, complexity, risk, workflow, model)
        }
    
    def _estimate_complexity(self, prompt):
        """Estimate how complex this task is."""
        score = 0
        if len(prompt) > 500: score += 2
        elif len(prompt) > 200: score += 1
        if '```' in prompt: score += 2
        if prompt.count(',') > 3: score += 1
        advanced = ['optimize', 'scale', 'architecture', 'design', 'system', 'distributed']
        score += sum(1 for w in advanced if w in prompt.lower())
        
        if score >= 4: return 'high'
        if score >= 2: return 'medium'
        return 'low'
    
    def _estimate_risk(self, prompt, task_type, is_critical):
        """Estimate risk of failure."""
        if is_critical:
            return 'critical'
        
        high_risk_tasks = ['refactor', 'debug']
        high_risk_keywords = ['production', 'deploy', 'database', 'security', 'auth', 'payment']
        
        if task_type in high_risk_tasks:
            return 'high'
        if any(w in prompt.lower() for w in high_risk_keywords):
            return 'high'
        
        return 'medium' if task_type in ['algorithm'] else 'low'
    
    def _choose_workflow(self, complexity, risk, task_type):
        """Choose the best workflow for this task."""
        if risk == 'critical':
            return 'consensus'
        if risk == 'high' and complexity == 'high':
            return 'iterative'
        if complexity == 'low' and risk == 'low':
            return 'simple'
        return 'standard'
    
    def _choose_model(self, task_type, complexity, risk, user_id=None):
        """Choose the best model based on all factors."""
        # Default routing
        from router import ROUTING
        model = ROUTING.get(task_type, 'deepseek')
        
        # Override for high complexity: use Claude for better quality
        if complexity == 'high' and risk in ['high', 'critical']:
            return 'claude'
        
        # Override for low risk: always use DeepSeek (cheaper)
        if risk == 'low':
            return 'deepseek'
        
        return model
    
    def _set_fallback(self, primary_model, risk):
        """Determine fallback strategy."""
        if risk == 'critical':
            return 'consensus'  # No single fallback, use voting
        if risk == 'high':
            return 'claude' if primary_model == 'deepseek' else 'deepseek'
        return 'deepseek'  # Low/medium risk: fall back to cheapest
    
    def _explain_decision(self, task_type, complexity, risk, workflow, model):
        """Explain why this routing decision was made."""
        reasons = []
        reasons.append(f"Task classified as: {task_type}")
        reasons.append(f"Complexity: {complexity}")
        reasons.append(f"Risk level: {risk}")
        reasons.append(f"Workflow: {workflow}")
        reasons.append(f"Model chosen: {model}")
        
        if risk == 'critical':
            reasons.append("Using consensus because this is critical")
        elif complexity == 'high':
            reasons.append("Using Claude because complexity is high")
        elif risk == 'low':
            reasons.append("Using DeepSeek because risk is low (cheaper)")
        
        return reasons


multi_step_router = MultiStepRouter()