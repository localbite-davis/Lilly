import os
from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings

class MemoryStore:
    """
    Vector database manager for Lily's long-term memory.
    Ensures that "she remembers everything" by storing and retrieving call summaries,
    fears, and preferences as semantic vectors.
    """
    def __init__(self):
        self.pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        self.index_name = "lily-patient-memory"
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        
        # Ensure index exists
        if self.index_name not in [idx.name for idx in self.pc.list_indexes()]:
            self.pc.create_index(
                name=self.index_name,
                dimension=1536, # OpenAI embedding dimension
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )
        
        self.index = self.pc.Index(self.index_name)

    def save_memory(self, patient_id: int, text: str, memory_type: str = "call_summary"):
        """
        Embeds a piece of information and saves it to Pinecone.
        """
        vector = self.embeddings.embed_query(text)
        
        # We use a composite ID (e.g., patient_id_timestamp) to store multiple memories
        import time
        memory_id = f"pt_{patient_id}_{int(time.time())}"
        
        self.index.upsert(
            vectors=[{
                "id": memory_id,
                "values": vector,
                "metadata": {
                    "patient_id": patient_id,
                    "type": memory_type,
                    "text": text
                }
            }]
        )

    def retrieve_relevant_context(self, patient_id: int, current_query: str, top_k: int = 3) -> str:
        """
        Fetches the most semantically relevant past memories for the current conversation.
        """
        query_vector = self.embeddings.embed_query(current_query)
        
        results = self.index.query(
            vector=query_vector,
            filter={"patient_id": {"$eq": patient_id}},
            top_k=top_k,
            include_metadata=True
        )
        
        contexts = [match["metadata"]["text"] for match in results["matches"]]
        return "\n".join(contexts)
