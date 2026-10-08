import os
from sentence_transformers import SentenceTransformer

# Environment variable se token read karein
hf_token = os.getenv("HF_TOKEN")

# Agar token blank/empty string ho, toh usay None set karein
if not hf_token or not hf_token.strip():
    hf_token = None

print("Downloading model...")
model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2",
    token=hf_token
)

model.save("./local_models/all-MiniLM-L6-v2")
print("Saved successfully!")