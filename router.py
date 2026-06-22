"""
AI Model Router - OpenRouter Backend
All models routed through a single OpenRouter API key.
6 models, AI-powered classification, tiered routing.
"""

import os
import time
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

OPENROUTER_KEY = os.environ.get('OPENROUTER_KEY', '')
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_KEY
)

# ─── MODEL METADATA ──────────────────────────────────────────────
MODELS = {
    'gemini': {
        'name': 'Gemini 2.5 Flash',
        'openrouter_id': 'google/gemini-2.5-flash',
        'cost_per_1k_tokens': 0.00015,
        'strength': 'Fastest response, simple tasks',
        'tier': 'budget'
    },
    'deepseek': {
        'name': 'DeepSeek V3',
        'openrouter_id': 'deepseek/deepseek-chat',
        'cost_per_1k_tokens': 0.00028,
        'strength': 'Speed and debugging',
        'tier': 'budget'
    },
    'qwen3-coder': {
        'name': 'Qwen3-Coder 480B',
        'openrouter_id': 'qwen/qwen3-coder',
        'cost_per_1k_tokens': 0.00022,
        'strength': 'Best open-weight coder, algorithms',
        'tier': 'standard'
    },
    'mistral': {
        'name': 'Mistral Large',
        'openrouter_id': 'mistralai/mistral-large',
        'cost_per_1k_tokens': 0.002,
        'strength': 'Creative tasks, multilingual',
        'tier': 'standard'
    },
    'claude': {
        'name': 'Claude Sonnet 4.6',
        'openrouter_id': 'anthropic/claude-sonnet-4-6',
        'cost_per_1k_tokens': 0.003,
        'strength': 'Production code, refactoring',
        'tier': 'standard'
    },
    'claude-opus': {
        'name': 'Claude Opus 4.8',
        'openrouter_id': 'anthropic/claude-opus-4-8',
        'cost_per_1k_tokens': 0.015,
        'strength': 'Architecture, deep research',
        'tier': 'heavy'
    }
}

# ─── ROUTING RULES ───────────────────────────────────────────────
ROUTING = {
    'algorithm': 'qwen3-coder',
    'debug': 'deepseek',
    'refactor': 'claude',
    'explain': 'deepseek',
    'architecture': 'claude-opus',
    'simple': 'gemini',
    'creative': 'mistral',
    'other': 'qwen3-coder'
}

FALLBACK = {
    'gemini': 'deepseek',
    'deepseek': 'qwen3-coder',
    'qwen3-coder': 'claude',
    'mistral': 'qwen3-coder',
    'claude': 'qwen3-coder',
    'claude-opus': 'claude'
}

# ─── AI-POWERED CLASSIFICATION ───────────────────────────────────

def classify_task(prompt):
    """
    AI-powered task classification using Gemini Flash.
    Costs ~$0.000001 per classification. Handles edge cases.
    """
    classification_prompt = f"""Classify this coding task into exactly ONE category. Reply with ONLY the category name.

Categories:
- algorithm (implementing, building, creating code, writing functions)
- debug (fixing bugs, errors, crashes, broken code)
- refactor (improving, cleaning, optimizing, restructuring code)
- explain (understanding concepts, asking how/why questions)
- architecture (designing systems, scaling, tradeoff decisions)
- simple (trivial questions, basic syntax, definitions)
- creative (brainstorming, suggesting alternatives, design patterns)

Task: "{prompt[:500]}"

Category:"""

    try:
        response = openrouter_client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[{"role": "user", "content": classification_prompt}],
            max_tokens=5,
            temperature=0
        )
        result = response.choices[0].message.content.strip().lower()
        
        valid = ['algorithm', 'debug', 'refactor', 'explain', 'architecture', 'simple', 'creative']
        for category in valid:
            if category in result:
                return category
        return 'other'
    except:
        return classify_with_keywords(prompt)


def classify_with_keywords(prompt):
    """Fallback keyword classifier."""
    prompt_lower = prompt.lower()
    if any(w in prompt_lower for w in ['fix', 'bug', 'error', 'broken', 'debug', 'failing', 'crash']):
        return 'debug'
    if any(w in prompt_lower for w in ['refactor', 'clean', 'improve', 'optimize', 'restructure']):
        return 'refactor'
    if any(w in prompt_lower for w in ['explain', 'what does', 'how does', 'why', 'understand']):
        return 'explain'
    if any(w in prompt_lower for w in ['architecture', 'design', 'system', 'scale', 'distributed']):
        return 'architecture'
    if any(w in prompt_lower for w in ['implement', 'build', 'create', 'write', 'algorithm', 'function']):
        return 'algorithm'
    if any(w in prompt_lower for w in ['brainstorm', 'creative', 'suggest', 'alternative', 'idea']):
        return 'creative'
    if len(prompt) < 30:
        return 'simple'
    return 'other'


def estimate_complexity(prompt):
    """Determine if a task is simple, standard, or heavy."""
    prompt_lower = prompt.lower()
    score = 0
    
    simple_words = ['what is', 'how do i', 'short', 'quick', 'basic', 'syntax', 'example']
    for word in simple_words:
        if word in prompt_lower: score -= 1
    
    heavy_words = ['architecture', 'design', 'system', 'scale', 'distributed', 'tradeoff',
                   'evaluate', 'recommend', 'strategy', 'migrate', 'infrastructure', 'pipeline']
    for word in heavy_words:
        if word in prompt_lower: score += 1
    
    if len(prompt) > 500: score += 1
    if len(prompt) < 50: score -= 1
    
    if score >= 2: return 'heavy'
    elif score <= -1: return 'simple'
    return 'standard'


def estimate_cost(prompt, model_key):
    """Estimate cost based on prompt length."""
    token_estimate = len(prompt) / 4
    cost_per_token = MODELS[model_key]['cost_per_1k_tokens']
    return round(token_estimate * cost_per_token / 1000, 8)


def route_task(prompt):
    """AI-powered classification and routing."""
    task_type = classify_task(prompt)
    primary = ROUTING.get(task_type, 'qwen3-coder')
    fallback = FALLBACK.get(primary, 'deepseek')
    
    return {
        'task_type': task_type,
        'confidence': 0.9 if task_type != 'other' else 0.5,
        'primary_model': primary,
        'primary_name': MODELS[primary]['name'],
        'primary_strength': MODELS[primary]['strength'],
        'fallback_model': fallback,
        'fallback_name': MODELS[fallback]['name'],
        'estimated_cost': estimate_cost(prompt, primary),
        'classification_method': 'ai' if task_type != 'other' else 'fallback'
    }

# ─── UNIVERSAL API CALLER ───────────────────────────────────────

def call_model(model_key, prompt, system_prompt=None, max_tokens=2000):
    """Call any model through OpenRouter."""
    if model_key not in MODELS:
        model_key = 'deepseek'
    
    model_id = MODELS[model_key]['openrouter_id']
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    response = openrouter_client.chat.completions.create(
        model=model_id,
        messages=messages,
        temperature=0.3,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content


def call_deepseek(prompt):
    return call_model('deepseek', prompt, "You are an expert software engineer. Be concise. Give one solution unless asked for more. Do not explain unless asked.")

def call_claude(prompt):
    return call_model('claude', prompt, "You are an expert software engineer. Write clean, working code. Be concise. Give one solution unless asked for more.")

def call_qwen3_coder(prompt):
    return call_model('qwen3-coder', prompt, "You are an expert software engineer. Write clean, working code. Be concise.")

def call_claude_opus(prompt):
    return call_model('claude-opus', prompt, "You are a senior software architect. Provide thorough analysis. Consider tradeoffs and edge cases.", max_tokens=4000)

def call_gemini(prompt):
    return call_model('gemini', prompt, "You are a helpful coding assistant. Be fast and concise.")

def call_mistral(prompt):
    return call_model('mistral', prompt, "You are an expert software engineer. Write clean, working code. Be concise.")

# ─── ORCHESTRATION ───────────────────────────────────────────────

def process_with_fallback(prompt):
    """Full pipeline: classify → route → call → fallback if needed."""
    plan = route_task(prompt)
    
    print(f"\n{'─'*60}")
    print(f"  Task: {plan['task_type']} | Method: {plan['classification_method']}")
    print(f"  Model: {plan['primary_name']}")
    print(f"  Cost: ${plan['estimated_cost']:.8f}")
    
    try:
        start = time.time()
        result = call_model(plan['primary_model'], prompt)
        elapsed = time.time() - start
        print(f"  ✓ Success ({elapsed:.1f}s)")
        return {
            'plan': plan,
            'result': result,
            'model_used': plan['primary_name'],
            'used_fallback': False,
            'elapsed': elapsed
        }
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        print(f"  Falling back to {plan['fallback_name']}...")
        try:
            start = time.time()
            result = call_model(plan['fallback_model'], prompt)
            elapsed = time.time() - start
            print(f"  ✓ Fallback ({elapsed:.1f}s)")
            return {
                'plan': plan,
                'result': result,
                'model_used': plan['fallback_name'],
                'used_fallback': True,
                'elapsed': elapsed
            }
        except Exception as e2:
            print(f"  ✗ Both failed: {e2}")
            return {
                'plan': plan,
                'result': None,
                'model_used': None,
                'used_fallback': True,
                'error': str(e2),
                'elapsed': 0
            }


if __name__ == '__main__':
    print("=" * 60)
    print("  AI MODEL ROUTER - 6 Models via OpenRouter")
    print("=" * 60)
    
    test_prompt = "Write a Python function that checks if a string is a palindrome"
    result = process_with_fallback(test_prompt)
    
    if result['result']:
        print(f"\n  Model Used: {result['model_used']}")
        print(f"  Time: {result['elapsed']:.1f}s")
        print(f"  Response: {result['result'][:300]}...")
    
    print(f"\n{'─'*60}")
    print("  Routing Rules")
    print(f"{'─'*60}")
    for task, model in ROUTING.items():
        print(f"  {task:<15} → {MODELS[model]['name']}")