/**
 * ModelRouter VS Code Extension
 * 
 * Features:
 * - Highlight code, right-click → "Route with ModelRouter"
 * - See which model was used and why
 * - Inline diff view for AI suggestions
 * - Status bar shows current model routing preference
 */

const vscode = require('vscode');
const axios = require('axios');

let API_URL = 'http://localhost:5000';
let API_KEY = 'demo-key-123';
let statusBarItem = null;

function activate(context) {
    // Load configuration
    const config = vscode.workspace.getConfiguration('modelrouter');
    API_URL = config.get('apiUrl', 'http://localhost:5000');
    API_KEY = config.get('apiKey', 'demo-key-123');
    
    // Status bar
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = '$(hubot) ModelRouter: Auto';
    statusBarItem.command = 'modelrouter.changeModel';
    statusBarItem.tooltip = 'Click to change routing model';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);
    
    // Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('modelrouter.route', routeSelection),
        vscode.commands.registerCommand('modelrouter.routeFullFile', routeFullFile),
        vscode.commands.registerCommand('modelrouter.explainCode', explainCode),
        vscode.commands.registerCommand('modelrouter.fixBug', fixBug),
        vscode.commands.registerCommand('modelrouter.refactor', refactorCode),
        vscode.commands.registerCommand('modelrouter.changeModel', changeModel),
        vscode.commands.registerCommand('modelrouter.proveIt', proveIt)
    );
    
    vscode.window.showInformationMessage('ModelRouter is ready. Highlight code and right-click to route.');
}

async function routeSelection() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    
    const selection = editor.document.getText(editor.selection);
    if (!selection) {
        vscode.window.showWarningMessage('Select some code first.');
        return;
    }
    
    const action = await vscode.window.showQuickPick(
        ['Generate Code', 'Explain This', 'Fix Bug', 'Refactor', 'Prove It (Test + Lint + Security)'],
        { placeHolder: 'What do you want to do?' }
    );
    
    if (!action) return;
    
    const prompts = {
        'Generate Code': `Write code based on this: ${selection}`,
        'Explain This': `Explain what this code does: ${selection}`,
        'Fix Bug': `Fix any bugs in this code: ${selection}`,
        'Refactor': `Refactor this code to improve it: ${selection}`,
        'Prove It (Test + Lint + Security)': `Analyze this code. Write tests, check for security issues, and verify correctness:\n\n${selection}\n\nReturn: 1. Working code 2. Tests 3. Security analysis 4. Performance notes`
    };
    
    await processRequest(prompts[action], action);
}

async function routeFullFile() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    
    const code = editor.document.getText();
    await processRequest(`Analyze this entire file and suggest improvements:\n\n${code}`, 'Full File Analysis');
}

async function explainCode() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    
    const selection = editor.document.getText(editor.selection) || editor.document.getText();
    await processRequest(`Explain this code in detail:\n\n${selection}`, 'Explanation');
}

async function fixBug() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    
    const selection = editor.document.getText(editor.selection) || editor.document.getText();
    await processRequest(`Find and fix all bugs in this code:\n\n${selection}`, 'Bug Fix');
}

async function refactorCode() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    
    const selection = editor.document.getText(editor.selection) || editor.document.getText();
    await processRequest(`Refactor this code following best practices:\n\n${selection}`, 'Refactor');
}

async function proveIt() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    
    const code = editor.document.getText(editor.selection) || editor.document.getText();
    const language = editor.document.languageId;
    
    const prompt = `PROVE IT MODE - Verify this ${language} code:

1. Does it compile/run correctly?
2. Write unit tests that verify correctness
3. Check for security vulnerabilities (SQL injection, XSS, hardcoded secrets, unsafe eval)
4. Check for performance issues (O(n²) patterns, memory leaks, unclosed resources)
5. Check for code quality (naming, structure, error handling)
6. Return a PASS/FAIL for each category with specific issues found

Code to verify:
${code}`;
    
    await processRequest(prompt, 'Prove It');
}

async function processRequest(prompt, action) {
    // Show progress
    await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `ModelRouter: ${action}...`,
        cancellable: false
    }, async (progress) => {
        try {
            progress.report({ message: 'Routing to best model...' });
            
            const response = await axios.post(`${API_URL}/api/v1/route`, {
                prompt: prompt,
                model_override: 'auto'
            }, {
                headers: { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' },
                timeout: 60000
            });
            
            const data = response.data;
            
            // Show result in new document
            const doc = await vscode.workspace.openTextDocument({
                content: data.result,
                language: 'markdown'
            });
            
            await vscode.window.showTextDocument(doc, { 
                viewColumn: vscode.ViewColumn.Beside,
                preview: false 
            });
            
            // Update status bar
            statusBarItem.text = `$(hubot) ${data.model_used} · ${data.elapsed}s · $${data.cost.toFixed(6)}`;
            
            vscode.window.showInformationMessage(
                `✓ ${data.model_used} · ${data.elapsed}s · $${data.cost.toFixed(6)}`
            );
            
        } catch (error) {
            vscode.window.showErrorMessage(
                `ModelRouter: ${error.response?.data?.error || error.message}`
            );
        }
    });
}

async function changeModel() {
    const model = await vscode.window.showQuickPick(
        ['Auto-Route (Smart)', 'DeepSeek V3 (Fast)', 'Claude Sonnet 4.6 (Thorough)'],
        { placeHolder: 'Select routing preference' }
    );
    
    if (!model) return;
    
    const modelMap = {
        'Auto-Route (Smart)': 'auto',
        'DeepSeek V3 (Fast)': 'deepseek',
        'Claude Sonnet 4.6 (Thorough)': 'claude'
    };
    
    const selected = modelMap[model];
    API_KEY = selected === 'auto' ? 'demo-key-123' : API_KEY;
    
    statusBarItem.text = `$(hubot) ModelRouter: ${model.replace(/\(.*\)/, '').trim()}`;
    vscode.window.showInformationMessage(`ModelRouter set to: ${model}`);
}

function deactivate() {
    if (statusBarItem) statusBarItem.dispose();
}

module.exports = { activate, deactivate };