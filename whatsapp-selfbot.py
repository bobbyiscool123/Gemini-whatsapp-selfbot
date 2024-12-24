import time
import json
import logging
import os
from datetime import datetime
import asyncio
from pyppeteer import launch
import subprocess
import signal
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
TARGET_PHONE_NUMBER = os.getenv("TARGET_PHONE_NUMBER")
CHAT_HISTORY_FILE = "chat_history.json"
WHATSAPP_JS_DIR = "whatsapp-js"
WHATSAPP_JS_FILE = "whatsapp.js"
MODEL_NAME = "gemini-pro"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHROME_PATH = os.getenv("CHROME_PATH")

# Configure logging
log_file_name = "messaging_bot_" + datetime.now().strftime("%Y%m%d") + ".log"
logging.basicConfig(filename=log_file_name, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logging.getLogger('').addHandler(console_handler)

# Get the absolute path to the WHATSAPP_JS_DIR
WHATSAPP_JS_DIR = os.path.abspath(WHATSAPP_JS_DIR)

# Get the path to npm
try:
    npm_path = subprocess.run(["where", "npm"], capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]
    if not npm_path.lower().endswith(".cmd"):
      npm_path = npm_path + ".cmd"
    logging.info(f"npm path: {npm_path}")
except subprocess.CalledProcessError as e:
    logging.error(f"Could not get npm path: {e}")
    npm_path = "npm"  # fallback to just npm if path can't be found

# Ensure directory exists for whatsapp js
if not os.path.exists(WHATSAPP_JS_DIR):
    os.makedirs(WHATSAPP_JS_DIR)
    logging.info(f"Created directory: {WHATSAPP_JS_DIR}")
else:
    logging.info(f"Directory exists: {WHATSAPP_JS_DIR}")

def initialize_chat_history():
    """Initializes chat history file if it doesn't exist."""
    if not os.path.exists(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, 'w') as f:
            json.dump([], f)
        logging.info("Initialized new chat history file.")

def load_chat_history():
    """Loads chat history from a JSON file."""
    try:
        with open(CHAT_HISTORY_FILE, 'r') as f:
            chat_history = json.load(f)
        logging.info("Chat history loaded.")
        return chat_history
    except (FileNotFoundError, json.JSONDecodeError):
         logging.error("Could not load history file or file not found")
         return []

def save_chat_history(chat_history):
    """Saves chat history to a JSON file."""
    with open(CHAT_HISTORY_FILE, 'w') as f:
        json.dump(chat_history, f, indent=4)
    logging.info("Chat history saved.")

async def setup_whatsapp_js():
    """Sets up the whatsapp-web.js environment."""
    try:
        logging.info("Setting up whatsapp-web.js...")
        # Ensure Node.js is installed
        subprocess.run(["node", "-v"], check=True, capture_output=True)
        # Check if whatsapp-web.js is installed or not, install it if not found
        if not os.path.exists(os.path.join(WHATSAPP_JS_DIR, "node_modules")):
            logging.info("Installing whatsapp-web.js dependencies")
            # Log current working directory
            logging.info(f"Current working directory: {os.getcwd()}")

            # Execute npm init
            init_command = [npm_path, "init", "-y"]
            logging.info(f"Executing: {init_command} in {WHATSAPP_JS_DIR}")
            init_process = subprocess.run(init_command, cwd=WHATSAPP_JS_DIR, capture_output=True, text=True)
            if init_process.returncode != 0:
                logging.error(f"npm init failed. Output:\n{init_process.stderr}")
                return False
            else:
               logging.info(f"npm init successful. Output:\n{init_process.stdout}")
            # Execute npm install
            install_command = [npm_path, "install", "whatsapp-web.js", "qrcode-terminal"]
            logging.info(f"Executing: {install_command} in {WHATSAPP_JS_DIR}")
            install_process = subprocess.run(install_command, cwd=WHATSAPP_JS_DIR, capture_output=True, text=True)
            if install_process.returncode != 0:
                logging.error(f"npm install failed. Output:\n{install_process.stderr}")
                return False
            else:
                logging.info(f"npm install successful. Output:\n{install_process.stdout}")

        # Create js file if not exists
        if not os.path.exists(os.path.join(WHATSAPP_JS_DIR, WHATSAPP_JS_FILE)):
            logging.info("Creating whatsapp.js")
            with open(os.path.join(WHATSAPP_JS_DIR, WHATSAPP_JS_FILE), "w") as f:
                f.write("""
                const qrcode = require('qrcode-terminal');
                const { Client, LocalAuth } = require('whatsapp-web.js');
                const client = new Client({
                   authStrategy: new LocalAuth(),
                    puppeteer: {
                        headless: true,
                        args: ['--no-sandbox', '--disable-setuid-sandbox']
                    }
                });

                client.on('qr', qr => {
                    qrcode.generate(qr, {small: true});
                });

                client.on('ready', () => {
                    console.log('Client is ready!');
                });

                client.on('message', async message => {
                    if (message.from === process.env.PHONE_NUMBER || message.from.endsWith('@g.us')) {
                       return
                    }
                    if(message.from !== process.env.TARGET_PHONE_NUMBER){
                      return
                    }
                    const message_content = {sender_id: message.from, text: message.body, timestamp: Date.now()};
                    console.log(JSON.stringify(message_content));
                });

                client.initialize();

                process.on('SIGINT', () => {
                    client.destroy();
                  process.exit();
                });
                """)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error setting up whatsapp-web.js: {e}")
        return False
    except FileNotFoundError as e:
        logging.error(f"Error finding file: {e}")
        return False

    return True

class WhatsAppBot:
    def __init__(self, chrome_path):
      self.chrome_path = chrome_path
    async def launch_browser(self):
       user_data_dir = os.path.join(os.getcwd(), 'chrome_user_data')
       browser = await launch(
            headless=False,
            executablePath=self.chrome_path,
             args=[
                 '--window-size=1280,720',
                '--no-sandbox',
                 '--disable-setuid-sandbox'

            ],
            userDataDir=user_data_dir,
        )
       return browser
    async def send_message(self, recipient_id, message_text):
        """Sends a message to a recipient using pyppeteer."""
        logging.info(f"Sending message to {recipient_id}: {message_text}")
        browser = None
        try:
           browser = await self.launch_browser()
           page = await browser.newPage()
           await page.goto(f'https://web.whatsapp.com/send?phone={recipient_id}&text={message_text}')
           logging.info(f"Waiting for input box")
           input_selector = 'div[contenteditable="true"][data-testid="conversation-compose-box-input"]'
           send_button_selector = 'span[data-testid="send"]'
           max_retries = 3
           for attempt in range(max_retries):
                try:
                  await page.waitForSelector(input_selector, {'timeout': 30000})
                  last_message_selector = 'div.message-in:last-child, div.message-out:last-child'
                  await page.waitForSelector(last_message_selector, {'timeout': 30000})
                  last_message = await page.querySelector(last_message_selector)
                  if not last_message:
                     logging.error("Could not find last message container")
                     return False
                   # Hover over the last message
                  await last_message.hover()
                  # Click on the reply button (adjust selector as needed)
                  reply_button_selector = 'div[aria-label="Reply"]'
                  await page.waitForSelector(reply_button_selector, {'timeout': 30000})
                  reply_button = await page.querySelector(reply_button_selector)
                  if not reply_button:
                     logging.error("Could not find reply button")
                     return False
                  await reply_button.click()
                  logging.info("Reply button clicked")
                  await page.type(input_selector, message_text)
                  logging.info("Input box found and message typed")

                  try:
                    await page.waitForSelector(send_button_selector, {'timeout': 20000})
                    await page.click(send_button_selector)
                    logging.info("Send button clicked")
                    break  # Exit the loop if successful

                  except Exception as e:
                      logging.info(f"Send button not found, trying to send with enter {e}")
                      await page.keyboard.press('Enter')
                      break
                except Exception as e:
                    logging.error(f"Error on attempt {attempt+1}/{max_retries}: {e}")
                    if attempt == max_retries - 1 :
                      logging.error(f"Failed to send message after {max_retries} retries")
                      return False
                    else:
                       logging.info(f"Retrying... {attempt+1}/{max_retries}")
                       await asyncio.sleep(2) # add delay before retry
           return True
        except Exception as e:
            logging.error(f"Error sending message to {recipient_id}: {e}")
            return False
        finally:
           if browser:
            await browser.close()

    async def get_previous_chats(self, target_phone_number, chat_history):
        """Gets the previous chat messages and returns the new updated history."""
        logging.info(f"Getting previous chats for {target_phone_number}")
        browser = None
        try:
            browser = await self.launch_browser()
            page = await browser.newPage()
            await page.goto(f'https://web.whatsapp.com/send?phone={target_phone_number}')
            logging.info(f"Waiting for input box")
            await page.waitForSelector('div[contenteditable="true"]', {'timeout': 60000})
            logging.info(f"Input box found")

            limit = 100  # Number of messages to fetch per batch
            while len(chat_history) < limit:
                try:
                    messages = await page.evaluate("""
                        () => {
                             const messageContainers = document.querySelectorAll('div.message-in, div.message-out');
                             const messages = [];
                             messageContainers.forEach(container => {
                                     const sender = container.classList.contains('message-in') ? 'Them' : 'Me';
                                     const textElement = container.querySelector('span.selectable-text');
                                     const text = textElement ? textElement.textContent : '';
                                    messages.push({sender_id: sender, text: text});
                             });
                             return messages;
                            }
                    """)
                    if not messages:
                        logging.info("No more messages in the chat history")
                        break
                    for message in messages:
                        chat_history.append({"sender_id": message['sender_id'], "text": message['text'], "timestamp": datetime.now().isoformat()})
                    if len(chat_history) >= limit:
                        break
                    load_more_button = await page.querySelector('div[aria-label="Load earlier messages"]')
                    if not load_more_button:
                       logging.info("No more 'load more' button, ending fetch ")
                       break
                    await load_more_button.click()
                    logging.info("Clicked Load more, waiting to load")
                    await asyncio.sleep(2)

                except Exception as e:
                   logging.error(f"Error fetching messages: {e}")
                   break

            logging.info(f"Finished getting previous chats for {target_phone_number}")
            return chat_history

        except Exception as e:
            logging.error(f"Error launching the browser for getting chat history : {e}")
            return chat_history
        finally:
          if browser:
            await browser.close()

def generate_gemini_response(chat_history, new_message_text):
    """Generates a response using the Gemini API, incorporating chat history."""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
    prompt = f"""You are an AI assistant that replies like the user.
        Given the following recent message, generate a reply in the style of the user (you).
        """
    if chat_history:
        last_message = chat_history[-1]
        sender = "Me" if last_message["sender_id"] == "me" else "Them"
        prompt += f"{sender}: {last_message['text']}\n"
    prompt += f"Them: {new_message_text}\nMe:"
    try:
       logging.info(f"Generated prompt {prompt}")
       response = model.generate_content(prompt)
       logging.info(f"Gemini generated response: {response.text}")
       return response.text.strip()
    except Exception as e:
        logging.error(f"Error generating Gemini response: {e}")
        return "Sorry, I'm having trouble responding right now."

async def send_initial_message(bot, target_phone_number, initial_message_text="Hello! This is an automated message."):
     """Sends an initial message to the target phone number."""
     logging.info(f"Sending initial message to {target_phone_number}")
     return await bot.send_message(target_phone_number, initial_message_text)

async def handle_message(bot, message, chat_history):
    """Handles a new message, generates a response using Gemini, and updates chat history."""
    sender_id = message.get("sender_id")
    message_text = message.get("text", "").lower()
    timestamp = message.get("timestamp")

    if not sender_id:
        logging.error("Could not get message sender ID. Cannot respond.")
        return chat_history

    if sender_id != TARGET_PHONE_NUMBER:
       logging.info(f"Ignoring message from {sender_id} - not the target")
       return chat_history
    logging.info(f"Received message from {sender_id}: {message_text}")
    chat_history.append({"sender_id": sender_id, "text": message_text, "timestamp": timestamp})

    gemini_response_text = generate_gemini_response(chat_history, message_text)
    if await bot.send_message(sender_id, gemini_response_text):
        logging.info(f"Successfully responded to {sender_id}")
        chat_history.append({"sender_id": "me", "text": gemini_response_text, "timestamp": datetime.now().isoformat()})
    else:
        logging.error(f"Failed to respond to {sender_id}")

    return chat_history

async def main():
    """Main loop to continuously check for and process new messages."""
    initialize_chat_history()
    chat_history = load_chat_history()
    setup_result = await setup_whatsapp_js()
    if not setup_result:
        logging.error("Setup failed. Cannot start.")
        return

    whatsapp_bot = WhatsAppBot(CHROME_PATH)
    whatsapp_process = None

    try:
        # Start whatsapp.js
        whatsapp_process = subprocess.Popen(["node", WHATSAPP_JS_FILE], cwd=WHATSAPP_JS_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ)
        logging.info("whatsapp-web.js started.")

        chat_history = await whatsapp_bot.get_previous_chats(TARGET_PHONE_NUMBER, chat_history)
        save_chat_history(chat_history)
        # Send initial message after startup
        await send_initial_message(whatsapp_bot, TARGET_PHONE_NUMBER)

        while True:
           if whatsapp_process.poll() is not None:
                logging.error(f"whatsapp-web.js process exited with code: {whatsapp_process.returncode}")
                break
           line = whatsapp_process.stdout.readline().strip()
           if line.startswith('{'):
               try:
                   message = json.loads(line)
                   chat_history = await handle_message(whatsapp_bot, message, chat_history)
                   save_chat_history(chat_history)
               except json.JSONDecodeError:
                   logging.error(f"Error decoding message: {line}")

           await asyncio.sleep(1) # Sleep with asyncio instead of time

    except Exception as e:
        logging.error(f"An unexpected error occurred in main: {e}")
    finally:
         # Cleanly shutdown
         if whatsapp_process:
           logging.info("Stopping whatsapp.js process")
           whatsapp_process.send_signal(signal.SIGINT)
           whatsapp_process.wait()
         logging.info("Message bot stopped")
         print("Bot stopped")

if __name__ == "__main__":
    logging.info("Starting message bot...")
    asyncio.run(main())