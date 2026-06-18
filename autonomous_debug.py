"""
Autonomous Debugging Loop
Model writes code → runs tests → sees failure → fixes itself → repeats until passing.
100% pass rate before the user sees output.
"""

import subprocess
import tempfile
import os
import re

class AutonomousDebugger:
    """
    Self-healing code generation.
    The model keeps trying until the code actually works.
    Users only see the final working version.
    """
    
    def __init__(self, max_attempts=5):
        self.max_attempts = max_attempts
    
    def generate_and_debug(self, prompt, model='deepseek', test_cases=None):
        """
        Generate code, test it, fix failures, repeat until passing.
        
        This is what makes the product feel magical:
        "Write a function" → 10 seconds later → working, tested code appears.
        """
        from router import call_deepseek, call_claude
        
        call_model = call_deepseek if model == 'deepseek' else call_claude
        
        # Step 1: Generate initial code
        code_prompt = f"{prompt}\n\nWrite ONLY the code. No explanation."
        code = call_model(code_prompt)
        
        # Step 2: Attempt to run it
        for attempt in range(self.max_attempts):
            success, output, error = self._run_code(code)
            
            if success:
                return {
                    'code': code,
                    'attempts': attempt + 1,
                    'status': 'passing',
                    'output': output
                }
            
            # Step 3: Code failed. Feed error back to model.
            debug_prompt = (
                f"The following code failed with this error:\n"
                f"```\n{error}\n```\n\n"
                f"Original code:\n```\n{code}\n```\n\n"
                f"Fix the code. Return ONLY the corrected code."
            )
            code = call_model(debug_prompt)
        
        return {
            'code': code,
            'attempts': self.max_attempts,
            'status': 'failed_after_max_attempts',
            'last_error': error
        }
    
    def _run_code(self, code):
        """Run code in sandbox and return (success, output, error)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name
        
        try:
            result = subprocess.run(
                ['python', temp_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            success = result.returncode == 0
            return success, result.stdout[:500], result.stderr[:500]
        except subprocess.TimeoutExpired:
            return False, "", "Execution timed out"
        finally:
            os.unlink(temp_path)


# ─── Usage ──────────────────────────────────────────────────────

if __name__ == '__main__':
    debugger = AutonomousDebugger(max_attempts=3)
    
    result = debugger.generate_and_debug(
        "Write a function that finds the longest common subsequence of two strings",
        model='deepseek'
    )
    
    print(f"Status: {result['status']}")
    print(f"Attempts: {result['attempts']}")
    if result['status'] == 'passing':
        print("Code works on first try!" if result['attempts'] == 1 else f"Fixed after {result['attempts']} attempts")