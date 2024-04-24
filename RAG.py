from Settings import settings
from llama_index.core import VectorStoreIndex, StorageContext, load_index_from_storage, SimpleDirectoryReader, Settings, get_response_synthesizer
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.readers.web import MainContentExtractorReader, TrafilaturaWebReader, BeautifulSoupWebReader
from llama_index.core.postprocessor import SimilarityPostprocessor
from Utils import displayError, displayInfo
from time import time
import os

class RAG:
	def __init__(self):
		Settings.embed_model = OllamaEmbedding(base_url=settings.host, model_name="nomic-embed-text") # nomic-embed-text, mxbai-embed-large, snowflake-arctic-embed
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

	def build_index(self, documents, setStatus):
		nodes = Settings.node_parser(documents)
		node_texts = [n.get_content(metadata_mode="embed") for n in nodes]
		embeddings = []
		for i, text in enumerate(node_texts):
			setStatus(f"Creating embeddings for {i}/{len(node_texts)}")
			embeddings.append(Settings.embed_model.get_text_embedding(text))
		for node, embedding in zip(nodes, embeddings):
			node.embedding = embedding
		return VectorStoreIndex(nodes=nodes)

	def loadUrl(self, url, setStatus):
		try:
			start = time()
			try:
				documents = MainContentExtractorReader().load_data([url])
				if len(documents)==0 or documents[0].text.strip()=="":
					raise(Exception("nothing found."))
			except:
				try:
					documents = TrafilaturaWebReader().load_data([url])
					if len(documents)==0 or documents[0].text.strip()=="":
						raise(Exception("nothing found."))
				except:
					documents = BeautifulSoupWebReader().load_data([url])
					if len(documents)==0 or documents[0].text.strip()=="":
						raise(Exception("nothing found."))

			#self.index = VectorStoreIndex.from_documents(documents) # , show_progress=True
			self.index = self.build_index(documents, setStatus)
			message = f"Indexed URL into {len(documents)} chunks in {time()-start:0.2f} seconds."
			displayInfo("Index", message)
			setStatus(message)
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def loadFolder(self, path, setStatus):
		try:
			setStatus("Loading files.")
			start = time()
			if isinstance(path, str):
				documents = SimpleDirectoryReader(path, recursive=True).load_data()
			else:
				documents = SimpleDirectoryReader(input_files=path).load_data()

			#self.index = VectorStoreIndex.from_documents(documents) # , show_progress=True
			self.index = self.build_index(documents, setStatus)
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