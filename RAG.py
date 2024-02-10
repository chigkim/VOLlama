from llama_index import VectorStoreIndex, SimpleDirectoryReader, ServiceContext
from llama_index.embeddings import resolve_embed_model
from llama_index.llms import Ollama
from Utils import displayError
from llama_index import download_loader

class RAG:
	def __init__(self, model, host):
		self.embed_model = resolve_embed_model("local:BAAI/bge-small-en-v1.5")
		self.llm = Ollama(model=model, request_timeout=300.0, base_url=host)
		self.service_context = ServiceContext.from_defaults(embed_model=self.embed_model, llm=self.llm)

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
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def loadFolder(self, folder, setStatus):
		try:
			documents = SimpleDirectoryReader(folder, recursive=True).load_data()
			self.index = VectorStoreIndex.from_documents(documents, service_context=self.service_context)
			setStatus(f"Indexed folder into {len(documents)} chunks.")
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def ask(self, question):
		query_engine = self.index.as_query_engine(service_context=self.service_context, streaming=True)
		response = query_engine.query(question)
		return response.response_gen
