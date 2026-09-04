import logging
import os
import sys

os.makedirs("logs", exist_ok=True)

def setup_logging():
    logger = logging.getLogger("rag_chatbot")

    # Agar already configured hai (reload ki wajah se) to dobara handlers na lagayein
    if logger.handlers:
        return logger

    # 1. Environment variable se check karein (Default: DEBUG = False)
    # Aap env mein DEBUG="true" ya LOG_LEVEL="DEBUG" rakh sakte hain
    is_debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    
    # Base level set karein
    logger.setLevel(logging.DEBUG if is_debug else logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    # 2. Production-safe logs (INFO level always active)
    info_handler = logging.FileHandler("logs/info.log")
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    logger.addHandler(info_handler)

    # 3. Terminal Output (Console)
    console_handler = logging.StreamHandler(sys.stdout)
    # Local par DEBUG show hoga, Production/Git par sirf INFO
    console_handler.setLevel(logging.DEBUG if is_debug else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 4. Debug File Handler (Sirf tab attach hoga jab DEBUG mode True ho)
    if is_debug:
        debug_handler = logging.FileHandler("logs/debug.log")
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(formatter)
        logger.addHandler(debug_handler)

    return logger

# Har file mein isse import karke use karenge
logger = setup_logging()