<<<<<<< HEAD
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, ServiceContext, Settings
from llama_index.core.embeddings import resolve_embed_model
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.readers.web import SimpleWebPageReader
from Utils import displayError
from time import time

class RAG:
	def __init__(self, host, model):
		self.setModel(host=host, model=model)

	def setModel(self, host, model):
		#self.embed_model = OllamaEmbedding(base_url=host, model_name=model)
=======
from llama_index import VectorStoreIndex, SimpleDirectoryReader, ServiceContext
from llama_index.embeddings import resolve_embed_model
from llama_index.llms import Ollama
from Utils import displayError
from llama_index import download_loader

class RAG:
	def __init__(self, model, host):
>>>>>>> 48128a31d794baaa59c79ebfc51f3443331af89c
		self.embed_model = resolve_embed_model("local:BAAI/bge-small-en-v1.5")
		self.llm = Ollama(model=model, request_timeout=300.0, base_url=host)
		self.service_context = ServiceContext.from_defaults(embed_model=self.embed_model, llm=self.llm)

<<<<<<< HEAD
	def loadUrl(self, url, setStatus):
		try:
			start = time()
			documents = SimpleWebPageReader(html_to_text=True).load_data([url])
			self.index = VectorStoreIndex.from_documents(documents, service_context=self.service_context)
			setStatus(f"Indexed URL into {len(documents)} chunks in {time()-start:0.2f} seconds.")
=======
	def setModel(self, model, host):
		print("Rag:", model)
		self.llm = Ollama(model=model, request_timeout=300.0, base_url=host)
		self.service_context = ServiceContext.from_defaults(embed_model=self.embed_model, llm=self.llm)

	def loadUrl(self, url, setStatus):
		try:
			TrafilaturaWebReader = download_loader("TrafilaturaWebReader")
			documents = TrafilaturaWebReader().load_data([url])
			self.index = VectorStoreIndex.from_documents(documents, service_context=self.service_context)
			setStatus(f"Indexed URL into {len(documents)} chunks.")
>>>>>>> 48128a31d794baaa59c79ebfc51f3443331af89c
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def loadFolder(self, folder, setStatus):
		try:
<<<<<<< HEAD
			start = time()
			documents = SimpleDirectoryReader(folder, recursive=True).load_data()
			self.index = VectorStoreIndex.from_documents(documents, service_context=self.service_context)
			setStatus(f"Indexed folder into {len(documents)} chunks in {time()-start:0.2f} seconds.")
=======
			documents = SimpleDirectoryReader(folder, recursive=True).load_data()
			self.index = VectorStoreIndex.from_documents(documents, service_context=self.service_context)
			setStatus(f"Indexed folder into {len(documents)} chunks.")
>>>>>>> 48128a31d794baaa59c79ebfc51f3443331af89c
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def ask(self, question):
		query_engine = self.index.as_query_engine(service_context=self.service_context, streaming=True)
		response = query_engine.query(question)
		return response.response_gen
