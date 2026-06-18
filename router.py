"""
AI Model Router - Classifies coding tasks and routes to the best model.
With live API calls to DeepSeek V3 and Claude Sonnet 4.
"""

import os
import time
from openai import OpenAI
import anthropic

# ─── CONFIGURATION ───────────────────────────────────────────────
import os
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_KEY', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_KEY', '')
OPENROUTER_KEY = os.environ.get('OPENROUTER_KEY', '')
# API clients
deepseek_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─── MODEL METADATA ──────────────────────────────────────────────
MODELS = {
    'deepseek': {
        'name': 'DeepSeek V3',
        'cost_per_1k_tokens': 0.00028,
        'strength': 'Speed and algorithms',
        'weakness': 'Less thorough on production code'
    },
    'claude': {
        'name': 'Claude Sonnet 4.6',
        'cost_per_1k_tokens': 0.003,
        'strength': 'Production integration and testing',
        'weakness': 'Slower, more expensive'
    },
    'qwen3-coder': {
        'name': 'Qwen3-Coder-480B',
        'cost_per_1k_tokens': 0.00022,
        'strength': 'Best open-weight coder, 256K context',
        'tier': 'standard'
    },
}

# ─── ROUTING RULES ───────────────────────────────────────────────
ROUTING = {
    'algorithm': 'qwen3-coder',
    'debug': 'deepseek',
    'refactor': 'claude',
    'explain': 'deepseek',
    'other': 'qwen3-coder'
}

FALLBACK = {
    'deepseek': 'claude',
    'claude': 'deepseek',
    'qwen3-coder': 'deepseek'
}

# ─── CLASSIFICATION ──────────────────────────────────────────────

def classify_task(prompt):
    """Classify a coding task by type."""
    prompt_lower = prompt.lower()
    
    if any(word in prompt_lower for word in ['fix', 'bug', 'error', 'broken', 'debug', 'failing', 'crash']):
        return 'debug'
    if any(word in prompt_lower for word in ['refactor', 'clean', 'improve', 'optimize', 'restructure', 'tech debt']):
        return 'refactor'
    if any(word in prompt_lower for word in ['explain', 'what does', 'how does', 'document', 'why', 'understand']):
        return 'explain'
    if any(word in prompt_lower for word in ['implement', 'build', 'create', 'write', 'algorithm', 'function', 'add feature']):
        return 'algorithm'
    
    return 'other'

def estimate_complexity(prompt):
    """Determine if a task is simple, standard, or heavy."""
    prompt_lower = prompt.lower()
    score = 0
    
    simple_words = ['what is', 'how do i', 'explain briefly', 'short', 'quick', 'basic', 'syntax', 'example']
    for word in simple_words:
        if word in prompt_lower:
            score -= 1
    
    heavy_words = ['architecture', 'design', 'system', 'scale', 'distributed', 'tradeoff',
                   'evaluate', 'recommend', 'strategy', 'migrate', 'infrastructure', 'pipeline']
    for word in heavy_words:
        if word in prompt_lower:
            score += 1
    
    if len(prompt) > 500:
        score += 1
    if len(prompt) < 50:
        score -= 1
    
    if score >= 2:
        return 'heavy'
    elif score <= -1:
        return 'simple'
    return 'standard'

def classify_confidence(task_type, prompt):
    """Return confidence score (0.0 to 1.0)."""
    prompt_lower = prompt.lower()
    
    indicators = {
        'debug': ['fix', 'bug', 'error', 'broken', 'debug', 'failing', 'crash'],
        'refactor': ['refactor', 'clean', 'improve', 'optimize', 'restructure', 'tech debt'],
        'explain': ['explain', 'what does', 'how does', 'document', 'why', 'understand'],
        'algorithm': ['implement', 'build', 'create', 'write', 'algorithm', 'function', 'add feature']
    }
    
    if task_type not in indicators:
        return 0.3
    
    matches = sum(1 for word in indicators[task_type] if word in prompt_lower)
    total = len(indicators[task_type])
    return round(min(matches / total * 2, 1.0), 2)


def estimate_cost(prompt, model_key):
    """Estimate cost based on prompt length."""
    token_estimate = len(prompt) / 4
    cost_per_token = MODELS[model_key]['cost_per_1k_tokens']
    return round(token_estimate * cost_per_token / 1000, 8)


def route_task(prompt):
    """Classify and route a task. Returns a plan."""
    task_type = classify_task(prompt)
    confidence = classify_confidence(task_type, prompt)
    primary = ROUTING[task_type]
    fallback = FALLBACK[primary]
    
    return {
        'task_type': task_type,
        'confidence': confidence,
        'primary_model': primary,
        'primary_name': MODELS[primary]['name'],
        'primary_strength': MODELS[primary]['strength'],
        'fallback_model': fallback,
        'fallback_name': MODELS[fallback]['name'],
        'estimated_cost': estimate_cost(prompt, primary)
    }

# ─── API CALLS ───────────────────────────────────────────────────

def call_deepseek(prompt):
    """Call DeepSeek V3 API."""
    response = deepseek_client.chat.completions.create(
        model="deepseek-chat",
         messages=[
            {"role": "system", "content": "You are an expert software engineer. Write clean, working code. Be concise. Give one solution unless asked for more. Do not explain unless asked"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=2000
    )
    return response.choices[0].message.content

def call_claude(prompt):
    """Call Claude Sonnet 4 API."""
    response = claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system="You are an expert software engineer. Write clean, working code. Be concise. Give one solution unless asked for more. do not explain unless asked",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return response.content[0].text

def call_qwen3_coder(prompt):
    """Call Qwen3-Coder-480B via OpenRouter."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_KEY
    )
    response = client.chat.completions.create(
        model="qwen/qwen3-coder",
        messages=[
            {"role": "system", "content": "You are an expert software engineer. Write clean, working code. Be concise. Give one solution unless asked for more. Do not explain unless asked"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=2000
    )
    return response.choices[0].message.content

def call_model(model_key, prompt):
    """Route to the correct API."""
    if model_key == 'deepseek':
        return call_deepseek(prompt)
    elif model_key == 'claude':
        return call_claude(prompt)
    elif model_key == 'qwen3-coder':
        return call_qwen3_coder(prompt)
    return None

# ─── ORCHESTRATION ───────────────────────────────────────────────

def process_with_fallback(prompt):
    """Full pipeline: classify → route → call → fallback if needed."""
    plan = route_task(prompt)
    
    print(f"\n{'─'*60}")
    print(f"  Task Type: {plan['task_type']} (confidence: {plan['confidence']})")
    print(f"  Primary:   {plan['primary_name']} ({plan['primary_strength']})")
    print(f"  Est. Cost: ${plan['estimated_cost']:.8f}")
    print(f"  Calling {plan['primary_name']}...")
    
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
            print(f"  ✓ Fallback success ({elapsed:.1f}s)")
            return {
                'plan': plan,
                'result': result,
                'model_used': plan['fallback_name'],
                'used_fallback': True,
                'elapsed': elapsed
            }
        except Exception as e2:
            print(f"  ✗ Both models failed: {e2}")
            return {
                'plan': plan,
                'result': None,
                'model_used': None,
                'used_fallback': True,
                'error': str(e2),
                'elapsed': 0
            }

# ─── MAIN ────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("  AI MODEL ROUTER - Live Test")
    print("=" * 60)

    
    # Quick test
    test_prompt = "Write a Python function that checks if a string is a palindrome"
    
    result = process_with_fallback(test_prompt)
    
    if result['result']:
        print(f"\n{'─'*60}")
        print(f"  Model Used: {result['model_used']}")
        print(f"  Time: {result['elapsed']:.1f}s")
        print(f"  Fallback: {result['used_fallback']}")
        print(f"  Response:")
        print(f"  {result['result'][:300]}...")
    else:
        print(f"\n  ✗ Complete failure: {result.get('error', 'Unknown')}")
    
    print(f"\n{'─'*60}")
    print("  Routing Rules Summary")
    print(f"{'─'*60}")
    for task, model in ROUTING.items():
        print(f"  {task:<12} → {MODELS[model]['name']}")
    print(f"\n  Fallback: DeepSeek ↔ Claude")
    # Test all task types
    print(f"\n{'='*60}")
    print("  TESTING ALL TASK TYPES")
    print(f"{'='*60}")
    
    tests = [
        ("debug", "Fix the null pointer error in the login function"),
        ("algorithm", "Implement a binary search tree with insert and find methods"),
        ("refactor", "Refactor this spaghetti code to use proper class structure"),
        ("explain", "Explain how Python's garbage collector handles circular references")
    ]
    
    for expected_type, prompt in tests:
        plan = route_task(prompt)
        status = "✓" if plan['task_type'] == expected_type else "✗"
        print(f"  {status} Expected: {expected_type:<12} Got: {plan['task_type']:<12} Confidence: {plan['confidence']}")
    # Test Claude refactoring specifically
    print(f"\n{'='*60}")
    print("  TESTING CLAUDE REFACTORING")
    print(f"{'='*60}")
    
    refactor_prompt = """Refactor this function to use list comprehension instead of a for loop:

def get_even_numbers(numbers):
    result = []
    for n in numbers:
        if n % 2 == 0:
            result.append(n)
    return result"""
    
    result = process_with_fallback(refactor_prompt)
    if result['result']:
        print(f"\n  Model: {result['model_used']}")
        print(f"  Response:\n{result['result']}")
    # Interactive mode
    print(f"\n{'='*60}")
    print("  INTERACTIVE MODE")
    print(f"  Type a coding task, or 'quit' to exit")
    print(f"{'='*60}")
    
    while True:
        prompt = input("\n  > ")
        if prompt.lower() == 'quit':
            break
        if prompt.strip():
            result = process_with_fallback(prompt)


