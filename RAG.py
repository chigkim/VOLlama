from Settings import settings
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.readers.web import MainContentExtractorReader# TrafilaturaWebReader, BeautifulSoupWebReader, SimpleWebPageReader
from Utils import displayError, displayInfo
from time import time
from tiktoken_ext import openai_public
import tiktoken_ext
from Parameters import get_parameters

class RAG:
	def __init__(self, host, model):
		#Settings.embed_model = OllamaEmbedding(base_url=host, model_name=model)
		Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
		options = get_parameters()
		Settings.llm = Ollama(model=model, request_timeout=300.0, base_url=host, additional_kwargs=options)
		self.index = None

	def loadUrl(self, url, setStatus):
		try:
			start = time()
			documents = MainContentExtractorReader().load_data([url])
			self.index = VectorStoreIndex.from_documents(documents)
			message = f"Indexed URL into {len(documents)} chunks in {time()-start:0.2f} seconds."
			displayInfo("Index", message)
			setStatus(message)
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def loadFolder(self, folder, setStatus):
		try:
			start = time()
			documents = SimpleDirectoryReader(folder, recursive=True).load_data()
			self.index = VectorStoreIndex.from_documents(documents)
			message = f"Indexed folder into {len(documents)} chunks in {time()-start:0.2f} seconds."
			displayInfo("Index", message)
			setStatus(message)
		except Exception as e:
			displayError(e)
			setStatus("Failed to index.")

	def ask(self, question):
		query_engine = self.index.as_query_engine(response_mode=settings.ragResponseMode, streaming=True)
		self.response = query_engine.query(question)
		return self.response.response_gen
