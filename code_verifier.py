"""
Code Verification Sandbox
Runs generated code in Docker to verify it works before returning to user.
"""

import subprocess
import tempfile
import os
import re
import json

class CodeVerifier:
    """
    Sandboxes code execution in Docker.
    Verifies code runs without errors before showing to user.
    """
    
    def __init__(self, timeout=30):
        self.timeout = timeout
    
    def extract_code(self, response_text):
        """Extract code blocks from AI response."""
        code_blocks = re.findall(r'```(?:python|javascript|java|rust|go)?\n(.*?)```', response_text, re.DOTALL)
        return code_blocks
    
    def verify_python(self, code):
        """
        Run Python code in Docker sandbox.
        Returns (success, output, error).
        """
        # Write code to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name
        
        try:
            # Run in Docker sandbox (isolated, no network, limited memory)
            result = subprocess.run(
                [
                    'docker', 'run', '--rm',
                    '--network=none',  # No internet access
                    '--memory=256m',    # Limited memory
                    '--cpus=1',         # Limited CPU
                    '-v', f'{temp_path}:/code/test.py:ro',
                    'python:3.12-slim',
                    'timeout', str(self.timeout),
                    'python', '/code/test.py'
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout + 5
            )
            
            success = result.returncode == 0
            output = result.stdout[:1000] if result.stdout else ""
            error = result.stderr[:1000] if result.stderr else ""
            
            return success, output, error
        
        except subprocess.TimeoutExpired:
            return False, "", f"Execution timed out after {self.timeout}s"
        except Exception as e:
            return False, "", str(e)
        finally:
            os.unlink(temp_path)
    
    def verify_response(self, response_text):
        """
        Verify all code blocks in a response.
        Returns verification results for each block.
        """
        code_blocks = self.extract_code(response_text)
        
        if not code_blocks:
            return {'verified': True, 'blocks': 0, 'note': 'No code blocks to verify'}
        
        results = []
        all_passed = True
        
        for i, code in enumerate(code_blocks):
            # Only verify Python for now (extend for other languages)
            if 'def ' in code or 'import ' in code or 'print(' in code:
                success, output, error = self.verify_python(code)
                results.append({
                    'block': i + 1,
                    'passed': success,
                    'output': output[:200],
                    'error': error[:200]
                })
                if not success:
                    all_passed = False
        
        return {
            'verified': all_passed,
            'blocks': len(results),
            'results': results
        }


# ─── Singleton ──────────────────────────────────────────────────
code_verifier = CodeVerifier()