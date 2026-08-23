"""
Idempotent document ingestion — safe to run every time the container starts.
Skips ingestion entirely if document_chunks already has data.
"""
import os
import re
import uuid
from pathlib import Path
from typing import List

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "rag-chatbot"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "taha123"),
}

# Inside the container this will be the mounted volume path (see docker-compose.yml)
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))


def normalize_name(filename: str) -> str:
    name = filename.lower()
    name = re.sub(r"\s*\(\d+\)", "", name)
    return name.strip()


def parse_filename(filename: str) -> dict:
    name = filename.replace(".pdf", "")
    parts = name.split("_")
    company = parts[0] if len(parts) > 0 else None
    filing_type = parts[1] if len(parts) > 1 else None
    year = parts[2] if len(parts) > 2 else None
    quarter = parts[3] if len(parts) > 3 else None
    period = f"{quarter} {year}" if quarter and year else year
    return {
        "company": company, "filing_type": filing_type,
        "year": year, "quarter": quarter, "period": period,
    }


def collect_pdf_files() -> List[Path]:
    if not DATA_DIR.exists():
        print(f"[ingest] DATA_DIR {DATA_DIR} does not exist — skipping ingestion.")
        return []

    seen = set()
    files = []
    for folder in [f for f in DATA_DIR.iterdir() if f.is_dir()]:
        for pdf_file in folder.glob("*.pdf"):
            norm = normalize_name(pdf_file.name)
            if norm in seen:
                continue
            seen.add(norm)
            files.append(pdf_file)
    return files


def already_ingested(conn) -> bool:
    """Check if document_chunks exists AND has rows."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'document_chunks'
            );
        """)
        table_exists = cur.fetchone()[0]
        if not table_exists:
            return False

        cur.execute("SELECT COUNT(*) FROM document_chunks;")
        count = cur.fetchone()[0]
        return count > 0


def run_ingestion():
    """Entry point — call this on app startup. No-op if data is already there."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True

    try:
        if already_ingested(conn):
            print("[ingest] document_chunks already has data — skipping ingestion.")
            return

        pdf_files = collect_pdf_files()
        if not pdf_files:
            print("[ingest] No PDF files found — nothing to ingest.")
            return

        print(f"[ingest] Found {len(pdf_files)} PDFs to process...")

        # Imports here (not at module top) so the app can start even if these
        # heavy libs are briefly unavailable and ingestion is skipped anyway.
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_experimental.text_splitter import SemanticChunker
        from langchain_community.document_loaders import PyMuPDFLoader
        from sentence_transformers import SentenceTransformer

        hf_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        semantic_splitter = SemanticChunker(
            embeddings=hf_embeddings,
            breakpoint_threshold_type="percentile",
            breakpoint_threshold_amount=95,
        )

        all_chunks = []
        for pdf_file in pdf_files:
            print(f"[ingest] Processing {pdf_file.name}...")
            try:
                loader = PyMuPDFLoader(str(pdf_file))
                documents = loader.load()
                file_metadata = parse_filename(pdf_file.name)
                for doc in documents:
                    doc.metadata["source"] = pdf_file.name
                    doc.metadata["source_type"] = "pdf"
                    doc.metadata.update(file_metadata)
                chunks = semantic_splitter.split_documents(documents)
                all_chunks.extend(chunks)
            except Exception as e:
                print(f"[ingest] Error processing {pdf_file.name}: {e}")

        print(f"[ingest] Total chunks: {len(all_chunks)}")

        model = SentenceTransformer("all-MiniLM-L6-v2")
        texts = [c.page_content for c in all_chunks]
        embeddings = model.encode(texts, show_progress_bar=True)
        embedding_dim = model.get_sentence_embedding_dimension()

        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(f"""
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
            """)

            rows = []
            for i, (chunk, embedding) in enumerate(zip(all_chunks, embeddings)):
                chunk_id = f"chunk_{uuid.uuid4().hex[:8]}_{i}"
                meta = chunk.metadata
                rows.append((
                    chunk_id, chunk.page_content, meta.get("company"),
                    meta.get("filing_type"), meta.get("quarter"), meta.get("year"),
                    meta.get("period"), meta.get("source"), embedding.tolist(),
                ))

            execute_values(cur, """
                INSERT INTO document_chunks
                (chunk_id, content, company, filing_type, quarter, year, period, source, embedding)
                VALUES %s
                ON CONFLICT (chunk_id) DO NOTHING;
            """, rows)

            print(f"[ingest] Inserted {len(rows)} chunks into Postgres.")
    finally:
        conn.close()


if __name__ == "__main__":
    run_ingestion()