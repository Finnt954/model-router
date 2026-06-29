"""
ModelRouter MCP Server
Implements the Model Context Protocol so OpenCode and other AI tools
can use ModelRouter as a provider.

MCP Overview:
- Tools call `tools/list` to discover available functions
- Tools call `tools/call` to execute a specific function
- Server responds with structured JSON
"""

import json
import sys
import os
from datetime import datetime

# Add the current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from router import route_task, MODELS, ROUTING, call_model, estimate_complexity
from evaluator import evaluator


def handle_request(request):
    """Main MCP request handler."""
    method = request.get('method', '')
    params = request.get('params', {})
    request_id = request.get('id', 0)
    
    if method == 'tools/list':
        return handle_list_tools(request_id)
    elif method == 'tools/call':
        return handle_call_tool(request_id, params)
    elif method == 'initialize':
        return handle_initialize(request_id)
    else:
        return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': f'Method not found: {method}'}}


def handle_initialize(request_id):
    """Initialize the MCP connection."""
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'result': {
            'protocolVersion': '2024-11-05',
            'serverInfo': {
                'name': 'modelrouter',
                'version': '1.0.0',
                'description': 'AI Model Router - intelligently routes coding tasks to the best model'
            },
            'capabilities': {
                'tools': {}
            }
        }
    }


def handle_list_tools(request_id):
    """List all available tools (models and routing functions)."""
    tools = [
        {
            'name': 'route_task',
            'description': 'Route a coding task to the best AI model. Classifies the task type, estimates complexity, and selects the optimal model.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'prompt': {
                        'type': 'string',
                        'description': 'The coding task or question to route'
                    },
                    'model_override': {
                        'type': 'string',
                        'description': 'Force a specific model (deepseek, claude, qwen3-coder, claude-opus, gemini, mistral) or auto',
                        'enum': ['auto', 'deepseek', 'claude', 'qwen3-coder', 'claude-opus', 'gemini', 'mistral']
                    }
                },
                'required': ['prompt']
            }
        },
        {
            'name': 'list_models',
            'description': 'List all available AI models with their strengths and costs',
            'inputSchema': {
                'type': 'object',
                'properties': {}
            }
        },
        {
            'name': 'review_code',
            'description': 'Perform an engineering review of code. Checks security, syntax, edge cases, and provides a confidence score.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'code': {
                        'type': 'string',
                        'description': 'The code to review'
                    },
                    'language': {
                        'type': 'string',
                        'description': 'Programming language (python, javascript, typescript, java, c)',
                        'enum': ['python', 'javascript', 'typescript', 'js', 'ts', 'java', 'c']
                    }
                },
                'required': ['code']
            }
        },
        {
            'name': 'compare_models',
            'description': 'Compare available models on a specific task type',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'task_type': {
                        'type': 'string',
                        'description': 'Type of coding task',
                        'enum': ['algorithm', 'debug', 'refactor', 'explain', 'architecture', 'simple', 'creative']
                    }
                },
                'required': ['task_type']
            }
        }
    ]
    
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'result': {'tools': tools}
    }


def handle_call_tool(request_id, params):
    """Execute a specific tool."""
    tool_name = params.get('name', '')
    arguments = params.get('arguments', {})
    
    try:
        if tool_name == 'route_task':
            return handle_route_task(request_id, arguments)
        elif tool_name == 'list_models':
            return handle_list_models(request_id)
        elif tool_name == 'review_code':
            return handle_review_code(request_id, arguments)
        elif tool_name == 'compare_models':
            return handle_compare_models(request_id, arguments)
        else:
            return {
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {'code': -32601, 'message': f'Tool not found: {tool_name}'}
            }
    except Exception as e:
        return {
            'jsonrpc': '2.0',
            'id': request_id,
            'error': {'code': -32000, 'message': str(e)}
        }


def handle_route_task(request_id, args):
    """Route a coding task to the best model."""
    prompt = args.get('prompt', '')
    model_override = args.get('model_override', 'auto')
    
    # Get routing plan
    plan = route_task(prompt)
    complexity = estimate_complexity(prompt)
    
    # Apply complexity override
    if model_override == 'auto':
        if complexity == 'simple':
            primary = 'gemini'
        elif complexity == 'heavy':
            primary = 'claude-opus'
        else:
            primary = plan['primary_model']
    else:
        primary = model_override
    
    # Get model info
    model_info = MODELS.get(primary, MODELS['deepseek'])
    
    # Generate the response
    result_text = call_model(primary, prompt)
    
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'result': {
            'content': [
                {
                    'type': 'text',
                    'text': result_text
                }
            ],
            'metadata': {
                'model_used': model_info['name'],
                'task_type': plan['task_type'],
                'complexity': complexity,
                'cost_estimate': plan['estimated_cost'],
                'classification_method': plan.get('classification_method', 'ai'),
                'routing_reason': f"Task: {plan['task_type']}, Complexity: {complexity} → {model_info['name']}"
            }
        }
    }


def handle_list_models(request_id):
    """List all available models."""
    models = []
    for key, info in MODELS.items():
        models.append({
            'id': key,
            'name': info['name'],
            'cost_per_1k_tokens': info['cost_per_1k_tokens'],
            'strength': info['strength'],
            'tier': info['tier']
        })
    
    routing = {}
    for task, model in ROUTING.items():
        routing[task] = MODELS[model]['name']
    
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'result': {
            'content': [
                {
                    'type': 'text',
                    'text': json.dumps({
                        'models': models,
                        'routing_rules': routing,
                        'total_models': len(models)
                    }, indent=2)
                }
            ]
        }
    }


def handle_review_code(request_id, args):
    """Perform engineering review of code."""
    code = args.get('code', '')
    language = args.get('language', 'python')
    
    from prove_it import prove_it
    result = prove_it.verify(code, language)
    report = prove_it.format_result(result)
    
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'result': {
            'content': [
                {
                    'type': 'text',
                    'text': report
                }
            ],
            'metadata': {
                'overall': result['overall'],
                'issues': len(result.get('issues', [])),
                'language': language
            }
        }
    }


def handle_compare_models(request_id, args):
    """Compare models for a specific task type."""
    task_type = args.get('task_type', 'algorithm')
    
    # Get outcome-based weights
    weights = evaluator.get_model_weights(days=30)
    task_weights = weights.get(task_type, {})
    
    # Get routing recommendation
    recommended = ROUTING.get(task_type, 'deepseek')
    
    comparison = {
        'task_type': task_type,
        'recommended_model': MODELS[recommended]['name'],
        'model_scores': task_weights,
        'all_models': {}
    }
    
    for key, info in MODELS.items():
        comparison['all_models'][info['name']] = {
            'cost': info['cost_per_1k_tokens'],
            'strength': info['strength'],
            'outcome_score': task_weights.get(key, 'no data')
        }
    
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'result': {
            'content': [
                {
                    'type': 'text',
                    'text': json.dumps(comparison, indent=2)
                }
            ]
        }
    }


def main():
    """Run the MCP server in stdio mode."""
    print("ModelRouter MCP Server starting...", file=sys.stderr)
    
    buffer = ""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        buffer += line
        
        # Try to parse the buffer
        try:
            request = json.loads(buffer)
            response = handle_request(request)
            print(json.dumps(response), flush=True)
            buffer = ""
        except json.JSONDecodeError:
            # Incomplete JSON, keep buffering
            continue
        except Exception as e:
            error_response = {
                'jsonrpc': '2.0',
                'id': 0,
                'error': {'code': -32603, 'message': f'Internal error: {str(e)}'}
            }
            print(json.dumps(error_response), flush=True)
            buffer = ""


if __name__ == '__main__':
    main()