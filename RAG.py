from Settings import settings
from llama_index.core import VectorStoreIndex, StorageContext, load_index_from_storage, SimpleDirectoryReader, Settings, get_response_synthesizer
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.readers.web import MainContentExtractorReader# TrafilaturaWebReader, BeautifulSoupWebReader, SimpleWebPageReader
from llama_index.core.postprocessor import SimilarityPostprocessor
from Utils import displayError, displayInfo
from time import time
import os

class RAG:
	def __init__(self):
		Settings.embed_model = OllamaEmbedding(base_url=settings.host, model_name="nomic-embed-text")
		#Settings.embed_model = HuggingFaceEmbedding(model_name=f"BAAI/bge-{settings.embed_model}-en-v1.5")
		self.index = None

	def load_index(self, folder):
		try:
			storage_context = StorageContext.from_defaults(persist_dir=folder)
			self.index = load_index_from_storage(storage_context)
		except Exception as e: displayError(e)

	def save_index(self, folder):
		try:
			self.index.storage_context.persist(persist_dir=folder)
		except Exception as e: displayError(e)

	def loadUrl(self, url, setStatus):
		try:
			start = time()
			documents = MainContentExtractorReader().load_data([url])
			self.index = VectorStoreIndex.from_documents(documents, show_progress=True)
			message = f"Indexed URL into {len(documents)} chunks in {time()-start:0.2f} seconds."
			displayInfo("Index", message)
			setStatus(message)
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def loadFolder(self, path, setStatus):
		try:
			start = time()
			if isinstance(path, str):
				documents = SimpleDirectoryReader(path, recursive=True).load_data()
			else:
				documents = SimpleDirectoryReader(input_files=path).load_data()

			self.index = VectorStoreIndex.from_documents(documents, show_progress=True)
			message = f"Indexed folder into {len(documents)} chunks in {time()-start:0.2f} seconds."
			displayInfo("Index", message)
			setStatus(message)
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def ask(self, question):
		node_postprocessors = [SimilarityPostprocessor(similarity_cutoff=settings.similarity_cutoff)]
		query_engine = self.index.as_query_engine(similarity_top_k=settings.similarity_top_k, node_postprocessors = node_postprocessors, response_mode='no_text')
		response = query_engine.query(question)
		if response.source_nodes:
			query_engine = self.index.as_query_engine(similarity_top_k=settings.similarity_top_k, node_postprocessors = node_postprocessors, response_mode=settings.response_mode, streaming=True)
			self.response = query_engine.query(question)
			return self.response.response_gen
		raise Exception("No texts found for the question using the current rag settings")