from anthropic import Anthropic
import os

def chat_with_claude(user_message, conversation_history=None):
    """
    Send a message to Claude and get a response
    
    Args:
        user_message: The user's message string
        conversation_history: Optional list of previous messages for context
    
    Returns:
        Claude's response as a string
    """
    # Initialize the client with your API key
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    
    # Build the messages array
    messages = conversation_history or []
    messages.append({
        "role": "user",
        "content": user_message
    })
    
    # Make the API call
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=messages
    )
    
    # Extract the text from the response
    return response.content[0].text