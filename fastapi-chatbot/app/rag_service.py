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

# Below this similarity score, retrieved chunks are considered irrelevant
SIMILARITY_THRESHOLD = 0.35

NOT_ENOUGH_INFO_REPLY = (
    "Your query doesn't have enough information. "
    "Please provide me some more details (e.g. company name, filing type, quarter/year)."
)
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

def is_ambiguous_query(query: str, model: str = OLLAMA_MODEL) -> bool:
    """
    LLM-based check: is the query too vague/incomplete to be answered
    meaningfully from SEC filing data (missing company, period, metric, etc.)?
    """
    system_prompt = """You are a query classifier for a financial SEC-filings RAG chatbot.
Decide if the user's question is AMBIGUOUS or CLEAR.

AMBIGUOUS = missing key details needed to search filings, e.g. no company name,
no time period, or the question is too vague/generic to look anything up
(e.g. "what was the revenue?", "how did they do?", "tell me about the filing").

CLEAR = specific enough to search for, even if short (e.g. "Tesla Q2 2023 revenue",
"Apple's net income in FY2022").

Respond with ONLY one word: "AMBIGUOUS" or "CLEAR"."""

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            options={"temperature": 0.0},
        )
        verdict = response["message"]["content"].strip().upper()
        return "AMBIGUOUS" in verdict
    except Exception as e:
        print(f"Error classifying query ambiguity: {e}")
        return False  # fail-open: classifier fail ho to user ko block na karein
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
        return NOT_ENOUGH_INFO_REPLY

    best_score = max((doc.get("similarity_score") or 0) for doc in retrieved_docs)
    if best_score < SIMILARITY_THRESHOLD:
        return NOT_ENOUGH_INFO_REPLY

    # Number each unique source so the model can cite it like [1], [2] ...
    context_parts = []
    citation_list = []
    seen = {}
    counter = 1

    for doc in retrieved_docs:
        meta = doc["metadata"]
        company = (meta.get("company") or "Unknown").upper()
        filing_type = (meta.get("filing_type") or "Unknown").upper()
        period = meta.get("period") or "Unknown period"
        source = meta.get("source") or ""
        key = (company, filing_type, period, source)

        if key not in seen:
            seen[key] = counter
            label = f"{company} {filing_type} ({period})"
            if source:
                label += f" — {source}"
            citation_list.append(f"[{counter}] {label}")
            counter += 1

        num = seen[key]
        context_parts.append(f"[{num}] {doc['content']}")

    context = "\n\n".join(context_parts)
    references = "\n".join(citation_list)

    system_prompt = """You are a financial analyst assistant. Answer the user's question using
ONLY the provided numbered context. Cite sources inline using square brackets like [1], [2],
exactly like a scientific paper — every factual claim must have an inline citation number
pointing to the context chunk it came from. Do NOT write a references or sources section
yourself, it will be added automatically after your answer.

Example:

Context:
[1] Apple's total revenue for fiscal year 2022 was $394.3 billion, an increase of 8% year-over-year.
[2] Apple's net income for fiscal year 2022 was $99.8 billion.

Question: What were Apple's revenue and net income in FY2022?

Answer:
Apple's total revenue for FY2022 was $394.3 billion, up 8% year-over-year [1]. Net income for the same period was $99.8 billion [2]."""

    user_prompt = f"""Context:
{context}

Question: {query}

Answer (use inline [n] citations, do not add a references section):"""

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        options={"temperature": 0.2},
    )
    answer_text = response["message"]["content"]

    return f"{answer_text}\n\n**References:**\n{references}"

class RAGService:
    """Single entrypoint the API layer calls: query in, answer out."""
    def __init__(self):
        self.embeddings_manager = EmbeddingsManager()
        self.retriever = RAGRetriever(self.embeddings_manager)

    def answer(self, query: str, top_k: int = 5) -> str:
        if is_small_talk(query):
            return generate_small_talk_reply(query)
        if is_ambiguous_query(query):
            return NOT_ENOUGH_INFO_REPLY
        docs = self.retriever.retrieve(query, top_k=top_k)
        return generate_answer(query, docs)


# Loaded once, imported by main.py at startup
rag_service: RAGService | None = None


def load_rag_service():
    global rag_service
    if rag_service is None:
        rag_service = RAGService()
    return rag_service