"""
Thin wrapper around the RAG pipeline you already built (embeddings,
Postgres/pgvector retrieval, Ollama generation). Loaded ONCE at app
startup (embedding models are slow to load) and reused across requests.

Note: SentenceTransformer's method is `get_sentence_embedding_dimension()`.
"""
import os
import re
from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer
import ollama
from .database import get_conn

OLLAMA_MODEL = "qwen3:4b"
LOCAL_MODEL_PATH = "./local_models/all-MiniLM-L6-v2"

# Patterns for greetings / small talk
_SMALL_TALK_PATTERNS = [
    r"^\s*(hi|hello|hey|yo|hola|greetings)\b",
    r"how are you",
    r"how('?s| is) it going",
    r"what'?s up",
    r"good (morning|afternoon|evening|night)",
    r"^\s*(who are you|what are you)\b",
    r"what can you (do|help)",
    r"^\s*thank(s| you)",
    r"^\s*(bye|goodbye|see ya|see you)\b",
]


def is_small_talk(query: str) -> bool:
    """Heuristic: short greeting-shaped messages skip RAG retrieval entirely."""
    q = query.strip().lower()
    if len(q.split()) > 12:
        return False
    return any(re.search(pattern, q) for pattern in _SMALL_TALK_PATTERNS)


def generate_small_talk_reply(query: str, user_profile: dict = None, model: str = OLLAMA_MODEL) -> str:
    """A separate, ungrounded reply path for greetings/small talk."""
    
    # Dynamic profile formatting
    if user_profile:
        name = user_profile.get("name", "User")
        role = user_profile.get("role", "Engineer")
        location = user_profile.get("location", "Lahore")
    else:
        name = "Asad" 
        role = "Software Engineer"
        location = "Lahore"

    system_prompt = f"""You are a friendly assistant embedded in a financial SEC-filings chatbot.
Reply briefly and warmly to greetings or small talk.

Known facts about the user:
- Name: {name}
- Role: {role}
- Location: {location}

Always use these updated facts when answering questions about the user's name or role."""

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        options={"temperature": 0.5},
    )
    return response["message"]["content"]


class EmbeddingsManager:
    def __init__(self, model_path: str = LOCAL_MODEL_PATH):
        self.model_path = model_path
        
        # Check if model is already downloaded locally
        if os.path.exists(LOCAL_MODEL_PATH):
            print(f"Loading embedding model from local storage: {LOCAL_MODEL_PATH}")
            self.model = SentenceTransformer(LOCAL_MODEL_PATH)
        else:
            print("Local model not found. Downloading from Hugging Face...")
            self.model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self.model.save(LOCAL_MODEL_PATH)
            print(f"Model saved locally at {LOCAL_MODEL_PATH}")

        print(f"Model loaded successfully. Dimension: {self.get_embedding_dimension()}")

    def generate_embeddings(self, texts: List[str]):
        return self.model.encode(texts, show_progress_bar=False)

    def get_embedding_dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()


class RAGRetriever:
    def __init__(self, embeddings_manager: EmbeddingsManager):
        self.embeddings_manager = embeddings_manager

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self.embeddings_manager.generate_embeddings([query])[0]
        embedding_list = query_embedding.tolist()

        search_query = """
            SELECT chunk_id, content, company, filing_type, quarter, year, period, source,
                   1 - (embedding <=> %s::vector) AS similarity_score
            FROM document_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(search_query, (embedding_list, embedding_list, top_k))
                    rows = cur.fetchall()
        except Exception as e:
            print(f"Error while retrieving documents: {e}")
            return []

        retrieved_docs = []
        for i, row in enumerate(rows):
            chunk_id, content, company, filing_type, quarter, year, period, source, score = row
            retrieved_docs.append({
                "id": chunk_id,
                "content": content,
                "metadata": {
                    "company": company, "filing_type": filing_type,
                    "quarter": quarter, "year": year,
                    "period": period, "source": source,
                },
                "similarity_score": score,
                "rank": i + 1,
            })
        return retrieved_docs


def generate_answer(query: str, retrieved_docs: List[Dict[str, Any]], model: str = OLLAMA_MODEL) -> str:
    if not retrieved_docs:
        return "I couldn't find relevant information to answer that question."

    context_parts = []
    for doc in retrieved_docs:
        meta = doc["metadata"]
        company = (meta.get("company") or "unknown").upper()
        filing_type = (meta.get("filing_type") or "unknown").upper()
        period = meta.get("period") or "unknown period"
        source_info = f"[{company} {filing_type} - {period}]"
        context_parts.append(f"{source_info}\n{doc['content']}")

    context = "\n\n---\n\n".join(context_parts)

    system_prompt = """You are a financial analyst assistant. Answer the user's question
using ONLY the provided context from SEC filings. If the context doesn't contain enough
information to answer, say so clearly. Always cite which company/filing/period your
answer is based on."""

    user_prompt = f"""Context from SEC filings:

{context}

Question: {query}

Answer based only on the context above:"""

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        options={"temperature": 0.2},
    )
    return response["message"]["content"]


class RAGService:
    """Single entrypoint the API layer calls: query in, answer out."""
    def __init__(self):
        self.embeddings_manager = EmbeddingsManager()
        self.retriever = RAGRetriever(self.embeddings_manager)

    def answer(self, query: str, top_k: int = 5) -> str:
        if is_small_talk(query):
            return generate_small_talk_reply(query)
        docs = self.retriever.retrieve(query, top_k=top_k)
        return generate_answer(query, docs)


# Loaded once, imported by main.py at startup
rag_service: RAGService | None = None


def load_rag_service():
    global rag_service
    if rag_service is None:
        rag_service = RAGService()
    return rag_service