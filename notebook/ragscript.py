# This is the simple python file converted from document.ipynb
import os
from pathlib import Path

# Update this to wherever your 4 folders live
data_dir = Path("../data")  

folders = [f for f in data_dir.iterdir() if f.is_dir()]
print(f"Found {len(folders)} folders:\n")
for folder in folders:
    pdf_files = list(folder.glob("*.pdf"))
    print(f"📁 {folder.name}: {len(pdf_files)} PDF(s)")
    for pdf in pdf_files:
        size_kb = pdf.stat().st_size / 1024
        print(f"   - {pdf.name} ({size_kb:.1f} KB)") # and here teh pdf name and size 
        #after conversion is printing
    print()


# %%
import re
def normalize_name(filename: str) -> str:
    """Strip things like ' (1)' before comparing, to catch duplicate downloads."""
    name = filename.lower()
    name = re.sub(r"\s*\(\d+\)", "", name)  # removes " (1)", " (2)" files
    return name.strip()


all_pdf_files = []
seen_normalized_names = set()
skipped_duplicates = []

folders = [f for f in data_dir.iterdir() if f.is_dir()]

for folder in folders:
    for pdf_file in folder.glob("*.pdf"):
        norm_name = normalize_name(pdf_file.name)
        if norm_name in seen_normalized_names:
            skipped_duplicates.append(pdf_file.name)
            continue
        seen_normalized_names.add(norm_name)
        all_pdf_files.append(pdf_file)

print(f"Total unique PDFs to process: {len(all_pdf_files)}")
print(f"Skipped duplicates: {skipped_duplicates}")

# %%
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from langchain_community.document_loaders import PyMuPDFLoader
# def process_all_pdfs(pdf_files, chunk_size=1000, chunk_overlap=200):
#     text_splitter = RecursiveCharacterTextSplitter(
#         chunk_size=chunk_size,
#         chunk_overlap=chunk_overlap,
#         length_function=len,
#         separators=["\n\n", "\n", " ", ""]
#     )

#     all_chunks = []

#     for pdf_file in pdf_files:
#         print(f"Processing {pdf_file.name}...")
#         try:
#             loader = PyMuPDFLoader(str(pdf_file))
#             documents = loader.load()

#             # extract structured metadata from filename
#             file_metadata = parse_filename(pdf_file.name)

#             # attach metadata to every page/document
#             for doc in documents:
#                 doc.metadata["source"] = pdf_file.name
#                 doc.metadata["source_type"] = "pdf"
#                 doc.metadata.update(file_metadata)

#             # split into chunks (metadata carries over automatically)
#             chunks = text_splitter.split_documents(documents)
#             all_chunks.extend(chunks)

#         except Exception as e:
#             print(f"Error processing {pdf_file.name}: {e}")

#     print(f"\nProcessed {len(pdf_files)} files into {len(all_chunks)} chunks total")
#     return all_chunks


# chunks = process_all_pdfs(all_pdf_files)

# %%
# print(f"Total chunks: {len(chunks)}\n")

# for chunk in chunks[:3]:
#     print("Metadata:", chunk.metadata)
#     print("Content preview:", chunk.page_content[:150])
#     print("-" * 60)

# %%
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_experimental.text_splitter import SemanticChunker

hf_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

semantic_splitter = SemanticChunker(
    embeddings=hf_embeddings,
    breakpoint_threshold_type="percentile",
    breakpoint_threshold_amount=95
)
def parse_filename(filename: str) -> dict:
    """Extract company/filing metadata from a filename like
    'meta_10-K_2024_Q3.pdf' -> company, filing_type, year, quarter."""
    name = filename.replace(".pdf", "")
    parts = name.split("_")

    company = parts[0] if len(parts) > 0 else None
    filing_type = parts[1] if len(parts) > 1 else None
    year = parts[2] if len(parts) > 2 else None
    quarter = parts[3] if len(parts) > 3 else None

    period = f"{quarter} {year}" if quarter and year else year

    return {
        "company": company,
        "filing_type": filing_type,
        "year": year,
        "quarter": quarter,
        "period": period,
    }
# %%
from langchain_community.document_loaders import PyMuPDFLoader
def process_all_pdfs(pdf_files):
    all_chunks = []

    for pdf_file in pdf_files:
        print(f"Processing {pdf_file.name}...")
        try:
            loader = PyMuPDFLoader(str(pdf_file))
            documents = loader.load()

            # extract structured metadata from filename
            file_metadata = parse_filename(pdf_file.name)

            # attach metadata to every page/document
            for doc in documents:
                doc.metadata["source"] = pdf_file.name
                doc.metadata["source_type"] = "pdf"
                doc.metadata.update(file_metadata)

               
            chunks = semantic_splitter.split_documents(documents)
            all_chunks.extend(chunks)

        except Exception as e:
            print(f"Error processing {pdf_file.name}: {e}")

    print(f"\nProcessed {len(pdf_files)} files into {len(all_chunks)} chunks total")
    return all_chunks


chunks = process_all_pdfs(all_pdf_files)
# Semantic Chunking is done okay i make comments of the recursive chunking and if it will not work 
# i will go for the last strategy.



from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List



class EmbeddingsManager:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self._load_model()

    def _load_model(self):
        try:
            print(f"Loading model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name)
            print(f"Model loaded. Embedding dimension: {self.model.get_embedding_dimension()}")
        except Exception as e:
            print(f"Error loading model: {self.model_name} {e}")
            raise e

    def generate_embeddings(self, texts: List[str]) -> np.ndarray:
        if not self.model:
            raise ValueError("Model not loaded")
        print(f"Generating embeddings for {len(texts)} texts...")
        embeddings = self.model.encode(texts, show_progress_bar=True)
        print(f"Generated embeddings with shape: {embeddings.shape}")
        return embeddings

    def get_embedding_dimension(self) -> int:
        if not self.model:
            raise ValueError("Model not loaded")
        return self.model.get_embedding_dimension()



embeddings_manager = EmbeddingsManager()



texts = [chunk.page_content for chunk in chunks]
embeddings = embeddings_manager.generate_embeddings(texts)
print(embeddings.shape)  # should be (num_chunks, 384)

import psycopg2

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "rag_chatbot",
    "user": "postgres",
    "password": "taha123" 
}

conn = psycopg2.connect(**DB_CONFIG)
conn.autocommit = True
cursor = conn.cursor()
print("Connected to Postgres successfully!")

#kkk
cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
print("Vector extension ready hai.")


embedding_dim = embeddings_manager.get_embedding_dimension()  # should print 384
print(f"Embedding dimension: {embedding_dim}")

create_table_query = f"""
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    chunk_id TEXT UNIQUE,
    content TEXT,
    company TEXT,
    filing_type TEXT,
    quarter TEXT,
    year TEXT,
    period TEXT,
    source TEXT,
    embedding vector({embedding_dim})
);
"""
cursor.execute(create_table_query)
print("Table ready.")


from psycopg2.extras import execute_values
import uuid

insert_query = """
INSERT INTO document_chunks 
(chunk_id, content, company, filing_type, quarter, year, period, source, embedding)
VALUES %s
ON CONFLICT (chunk_id) DO NOTHING;
"""

rows_to_insert = []
for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
    chunk_id = f"chunk_{uuid.uuid4().hex[:8]}_{i}"
    meta = chunk.metadata

    rows_to_insert.append((
        chunk_id,
        chunk.page_content,
        meta.get("company"),
        meta.get("filing_type"),
        meta.get("quarter"),
        meta.get("year"),
        meta.get("period"),
        meta.get("source"),
        embedding.tolist()
    ))

execute_values(cursor, insert_query, rows_to_insert)
print(f"Inserted {len(rows_to_insert)} chunks into Postgres.")

# %%
cursor.execute("SELECT COUNT(*) FROM document_chunks;")
print("Total rows in table:", cursor.fetchone()[0])

cursor.execute("SELECT chunk_id, company, filing_type, period, LEFT(content, 100) FROM document_chunks LIMIT 5;")
for row in cursor.fetchall():
    print(row)

# %%
from typing import List, Dict, Any

class RAGRetriever:
    def __init__(self, conn, embeddings_manager):
        self.conn = conn
        self.embeddings_manager = embeddings_manager

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self.embeddings_manager.generate_embeddings([query])[0]
        try:
            cur = self.conn.cursor()
            search_query = """
                SELECT chunk_id, content, company, filing_type, quarter, year, period, source,
                       1 - (embedding <=> %s::vector) AS similarity_score
                FROM document_chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """
            embedding_list = query_embedding.tolist()
            cur.execute(search_query, (embedding_list, embedding_list, top_k))
            rows = cur.fetchall()

            retrieved_docs = []
            for i, row in enumerate(rows):
                chunk_id, content, company, filing_type, quarter, year, period, source, similarity_score = row
                retrieved_docs.append({
                    'id': chunk_id,
                    'content': content,
                    'metadata': {'company': company, 'filing_type': filing_type, 'quarter': quarter,
                                 'year': year, 'period': period, 'source': source},
                    'similarity_score': similarity_score,
                    'rank': i + 1
                })
            print(f"Retrieved {len(retrieved_docs)} documents")
            return retrieved_docs
        except Exception as e:
            print(f"Error while retrieving documents: {e}")
            return []

rag_retriever = RAGRetriever(conn, embeddings_manager)


results = rag_retriever.retrieve("What was meta's revenue in Q3 2024?", top_k=5)
for r in results:
    print(r['metadata']['company'], r['metadata']['period'], round(r['similarity_score'], 3))
    print(r['content'][:150])
    print("-" * 60)

# %% [markdown]
# Open Ai LLM Connection


from dotenv import load_dotenv
import os

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
print("Key loaded:", openai_api_key is not None)


import ollama

response = ollama.chat(
    model="qwen3:4b",
    messages=[{"role": "user", "content": "Say hello in two sentence."}]
)
print(response['message']['content'])

# %%
import ollama
from typing import List, Dict, Any

def generate_answer(query: str, retrieved_docs: List[Dict[str, Any]], model: str = "qwen3:4b") -> str:
    if not retrieved_docs:
        return "I couldn't find relevant information to answer that question."

    context_parts = []
    for doc in retrieved_docs:
        meta = doc['metadata']
        source_info = f"[{meta['company'].upper()} {meta['filing_type'].upper()} - {meta['period']}]"
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
            {"role": "user", "content": user_prompt}
        ],
        options={"temperature": 0.2}
    )

    return response['message']['content']


def ask_chatbot(query: str, top_k: int = 5) -> str:
    print(f"\nSearching for: {query}\n")
    retrieved_docs = rag_retriever.retrieve(query, top_k=top_k)

    if not retrieved_docs:
        return "No relevant documents found."

    print(f"Using {len(retrieved_docs)} retrieved chunks as context\n")
    answer = generate_answer(query, retrieved_docs)
    return answer


answer = ask_chatbot("What was Apple's revenue in Q1 2024?")
print(answer)


answer = ask_chatbot("Amazon FORM 10-K item 1")
print(answer)

# %%
answer = ask_chatbot("What was Amazon's total net sales in 2023?")
print(answer)





