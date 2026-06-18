"""
ModelRouter Slack Bot
@modelrouter write a binary search in python
"""

from flask import Flask, request, jsonify
from router import process_with_fallback

app = Flask(__name__)

@app.route('/slack/events', methods=['POST'])
def slack_events():
    """
    Handle Slack slash commands.
    Deploy this as a separate microservice.
    """
    data = request.json
    
    # Slack verification
    if data.get('type') == 'url_verification':
        return jsonify({'challenge': data['challenge']})
    
    # Handle slash command: /route [prompt]
    if data.get('event', {}).get('type') == 'app_mention':
        text = data['event']['text']
        # Remove the @mention
        prompt = text.split('>', 1)[-1].strip() if '>' in text else text
        
        result = process_with_fallback(prompt)
        
        # Post response back to Slack
        import requests
        requests.post(data['event']['channel'], json={
            'text': f"*Routed to {result.get('model_used', 'Unknown')}*\n```{result.get('result', '')[:3000]}```"
        })
    
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(port=5001)