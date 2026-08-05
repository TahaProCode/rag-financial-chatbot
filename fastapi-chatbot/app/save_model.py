from sentence_transformers import SentenceTransformer

print("Downloading model...")
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
model.save("./local_models/all-MiniLM-L6-v2")
print("Saved successfully!")