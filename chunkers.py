import uuid
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

class BaselineChunker:
    """
    Simulates the 'existing/current chunker'.
    Uses a basic RecursiveCharacterTextSplitter.
    """
    def __init__(self, chunk_size=300, chunk_overlap=50):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        
    def chunk(self, text: str, metadata: dict) -> list[Document]:
        # Split text into chunks
        texts = self.splitter.split_text(text)
        docs = []
        for t in texts:
            chunk_meta = metadata.copy()
            chunk_meta['chunk_id'] = f"chunk_{uuid.uuid4().hex[:8]}"
            docs.append(Document(page_content=t, metadata=chunk_meta))
        return docs

class StructureAwareChunker:
    """
    Structure-aware chunker that understands Recipe title, Ingredients table, Method, Allergens.
    Never separates an ingredient row from its table header or its parent recipe title.
    """
    def chunk(self, recipe_data: dict) -> list[Document]:
        """
        recipe_data format expected:
        {
            "title": "Idli",
            "description": "...",
            "cuisine": "...",
            "dietary_tags": "...",
            "allergens": "...",
            "yield": "...",
            "ingredients_headers": ["Ingredient", "Amount", "Ratio %"],
            "ingredients_rows": [["Idli rice", "800 g", "100%"], ...],
            "method_steps": ["1. Soak...", "2. Grind..."],
            "notes": "...",
            "source_file": "TamilNadu_Recipe_Cards.docx",
            "recipe_id": "rec_123"
        }
        """
        docs = []
        
        # Base metadata applied to every chunk for this recipe
        base_meta = {
            "source_file": recipe_data.get("source_file", ""),
            "recipe_id": recipe_data.get("recipe_id", ""),
            "cuisine": recipe_data.get("cuisine", ""),
            "dietary_tags": recipe_data.get("dietary_tags", ""),
        }
        
        title = recipe_data.get("title", "Unknown Recipe")
        
        # Helper to add a chunk
        def add_chunk(content: str):
            meta = base_meta.copy()
            meta['chunk_id'] = f"chunk_{uuid.uuid4().hex[:8]}"
            docs.append(Document(page_content=content.strip(), metadata=meta))

        # 1. Metadata/Overview Chunk
        overview = f"Recipe Title: {title}\n"
        if recipe_data.get("description"):
            overview += f"Description: {recipe_data['description']}\n"
        if recipe_data.get("cuisine"):
            overview += f"Cuisine: {recipe_data['cuisine']}\n"
        if recipe_data.get("dietary_tags"):
            overview += f"Dietary Tags: {recipe_data['dietary_tags']}\n"
        if recipe_data.get("allergens"):
            overview += f"Allergens: {recipe_data['allergens']}\n"
        if recipe_data.get("yield"):
            overview += f"Yield: {recipe_data['yield']}\n"
        add_chunk(overview)
        
        # 2. Ingredient Chunks
        # We chunk each ingredient row separately, but firmly attach the recipe title and headers
        headers = recipe_data.get("ingredients_headers", [])
        for row in recipe_data.get("ingredients_rows", []):
            ing_text = f"Recipe Title: {title}\nIngredients Table Row:\n"
            for i, header in enumerate(headers):
                val = row[i] if i < len(row) else ""
                ing_text += f"- {header}: {val}\n"
            add_chunk(ing_text)
            
        # 3. Method Steps Chunks
        for step in recipe_data.get("method_steps", []):
            step_text = f"Recipe Title: {title}\nMethod Step:\n{step}"
            add_chunk(step_text)
            
        # 4. Notes Chunk
        if recipe_data.get("notes"):
            notes_text = f"Recipe Title: {title}\nCook's Notes:\n{recipe_data['notes']}"
            add_chunk(notes_text)
            
        return docs
