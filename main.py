import os
import json
import uvicorn
from google import genai
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
PORT = int(os.getenv("PORT", "8080"))
DOMAIN = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("NGROK_URL")
if not DOMAIN:
    raise ValueError("DOMAIN environment variable not set.")
WS_URL = f"wss://{DOMAIN}/ws"

# Updated greeting to reflect the new model
WELCOME_GREETING = "Namaste! Main Ravya hoon, Hitsar Shah ki virtual assistant, Raveendra J Shah and Co. se. Hitsar abhi available nahi hain. Aap ka naam kya hai aur main aapki kya madad kar sakti hoon?"

# System prompt for Gemini
# Gemini works well with a direct instruction like this.
SYSTEM_PROMPT = """You are Ravya, Hitsar Shah ki virtual assistant at Raveendra J Shah and Co., ek CA firm in Surat, Gujarat. Tumhara kaam hai incoming calls receive karna jab Hitsar busy ho, caller ka naam aur purpose samajhna, basic sawaalon ke jawab dena, aur message note karke Hitsar tak pahunchana.

Yeh conversation ek phone call par ho rahi hai, isliye tumhare jawab spoken aloud honge. Koi special characters mat use karo, koi asterisks, bullet points, ya emojis nahi. Saare numbers words mein bolo jaise one thousand nahi ki 1000.

LANGUAGE RULE:
Agar caller Hindi mein bole toh Hindi mein bolo. Agar English mein bole toh English mein bolo. Agar Gujarati mein bole toh Gujarati mein bolo. Hamesha short sentences rakho.

CALL FLOW:

STEP ONE - GREET: Kaho: Namaste, main Ravya hoon, Hitsar Shah ki virtual assistant, Raveendra J Shah and Co. se. Hitsar abhi available nahi hain.

STEP TWO - CALLER KI DETAILS LO: Pucho: Aap ka naam kya hai aur aaj main aapki kya madad kar sakti hoon?

STEP THREE - BASIC SAWAALON KE JAWAB:
Agar firm ke baare mein puche toh kaho: Hum GST, income tax, audit aur company law ka kaam karte hain. Hitsar aapko callback karenge.
Agar fees ya appointment puche toh kaho: Yeh details ke liye Hitsar se directly baat karna better hoga. Main aapka message untak pahuncha dungi.
Agar urgent ho toh kaho: Main samajhti hoon yeh urgent hai. Main abhi Hitsar ko aapka message bhejti hoon.

STEP FOUR - CONFIRM MESSAGE: Kaho: Toh main note kar leti hoon, aapka naam [naam] hai aur aapka message hai [message]. Kya yeh sahi hai?

STEP FIVE - CALL BAND KARO: Kaho: Bahut shukriya [naam]. Main aapka message Hitsar tak zaroor pahunchaati hoon. Aapka din achha rahe.

STRICT RULES:
Hitsar ka personal number kabhi share mat karo. Kisi client ka naam doosre ko mat batao. Specific callback time promise mat karo. Koi bhi case ya filing ki details share mat karo. Agar jawab na pata ho toh kaho: Yeh main confirm nahi kar sakti, Hitsar aapko callback karke bata denge. Ek saath do se zyada sawaal mat pucho. Har response short rakho."""

# --- Gemini API Initialization ---
# Get your Google API key from https://aistudio.google.com/app/apikey
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable not set.")

# Initialize the Gemini client with the new SDK
client = genai.Client(api_key=GOOGLE_API_KEY)

# Store active chat sessions
# We will now store Gemini's chat session objects
sessions = {}

# Create FastAPI app
app = FastAPI()

def gemini_response(chat_session, user_prompt):
    """Get a response from the Gemini API."""
    response = chat_session.send_message(user_prompt)
    return response.text

@app.post("/twiml")
async def twiml_endpoint():
    """Endpoint that returns TwiML for Twilio to connect to the WebSocket"""
    # Note: Twilio ConversationRelay has built-in TTS. We specify a provider and voice.
    # You can change 'ElevenLabs' to 'Amazon' or 'Google' if you prefer their TTS.
    xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
    <Connect>
    <ConversationRelay url="{WS_URL}" welcomeGreeting="{WELCOME_GREETING}" ttsProvider="ElevenLabs" voice="FGY2WhTYpPnrIDTdsKH5" />
    </Connect>
    </Response>"""
    
    return Response(content=xml_response, media_type="text/xml")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication"""
    await websocket.accept()
    call_sid = None
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["type"] == "setup":
                call_sid = message["callSid"]
                print(f"Setup for call: {call_sid}")
                # Start a new chat session for this call using the new SDK
                sessions[call_sid] = client.chats.create(
                    model="gemini-2.5-flash",
                    config={"system_instruction": SYSTEM_PROMPT}
                )
                
            elif message["type"] == "prompt":
                if not call_sid or call_sid not in sessions:
                    print(f"Error: Received prompt for unknown call_sid {call_sid}")
                    continue

                user_prompt = message["voicePrompt"]
                print(f"Processing prompt: {user_prompt}")
                
                chat_session = sessions[call_sid]
                response_text = gemini_response(chat_session, user_prompt)
                
                # The chat_session object automatically maintains history.
                
                # Send the complete response back to Twilio.
                # Twilio's ConversationRelay will handle the text-to-speech conversion.
                await websocket.send_text(
                    json.dumps({
                        "type": "text",
                        "token": response_text,
                        "last": True  # Indicate this is the full and final message
                    })
                )
                print(f"Sent response: {response_text}")
                
            elif message["type"] == "interrupt":
                print(f"Handling interruption for call {call_sid}.")
                
            else:
                print(f"Unknown message type received: {message['type']}")
                
    except WebSocketDisconnect:
        print(f"WebSocket connection closed for call {call_sid}")
        if call_sid in sessions:
            sessions.pop(call_sid)
            print(f"Cleared session for call {call_sid}")

if __name__ == "__main__":
    print(f"Starting server on port {PORT}")
    print(f"WebSocket URL for Twilio: {WS_URL}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
