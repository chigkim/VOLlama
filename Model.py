from Settings import settings
from Parameters import get_parameters
from ollama import Client as Ollama_Client
from openai import OpenAI as OpenAI_client
import google.generativeai as gemini_client
from llama_index.core import Settings
from llama_index.core.base.llms.types import ChatResponse
from llama_index.core.schema import ImageDocument
from llama_index.llms.ollama import Ollama
from llama_index.llms.openai import OpenAI
from llama_index.llms.gemini import Gemini
from llama_index.core.llms import ChatMessage
from llama_index.multi_modal_llms.openai.utils import (
	generate_openai_multi_modal_chat_message,
)
import wx
from Utils import displayError
from pathlib import Path
import os
from Parameters import get_parameters
from RAG import RAG
import re
import tiktoken
import tiktoken_ext
from tiktoken_ext import openai_public
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
import base64
from llama_index.core import SimpleDirectoryReader
from llama_index.llms.openai_like import OpenAILike


def encode_image(image_path):
	with open(image_path, "rb") as image_file:
		return base64.b64encode(image_file.read()).decode("utf-8")


class Model:
	def __init__(self):
		self.messages = []
		self.generate = False
		self.image = None
		self.document = None
		self.rag = None
		self.models = []
		self.token_counter = TokenCountingHandler(
			tokenizer=tiktoken.encoding_for_model("gpt-3.5-turbo").encode
		)

	def get_models(self):
		ids = []
		if settings.llm_name == "Ollama":
			ids = [
				model["name"]
				for model in Ollama_Client(host=settings.ollama_base_url).list()[
					"models"
				]
			]
		if settings.llm_name == "OpenAI":
			if not settings.openai_api_key:
				return ids
			client = OpenAI_client(api_key=settings.openai_api_key)
			ids = [
				i.id for i in list(client.models.list().data) if i.id.startswith("gpt")
			]
		if settings.llm_name == "OpenAILike":
			client = OpenAI_client(
				base_url=settings.openailike_base_url,
				api_key=settings.openailike_api_key,
			)
			ids = [i.id for i in list(client.models.list().data)]
		if settings.llm_name == "Gemini":
			if not settings.gemini_api_key:
				return ids
			gemini_client.configure(api_key=settings.gemini_api_key)
			ids = [
				m.name
				for m in list(gemini_client.list_models())
				if "generateContent" in m.supported_generation_methods
			]
		ids.sort()
		self.models = ids
		return ids

	def init_llm(self):
		if settings.model_name not in self.models:
			settings.model_name = self.get_models()[0]
		options = get_parameters()
		if settings.llm_name == "Ollama":
			Settings.llm = Ollama(
				model=settings.model_name,
				request_timeout=3600,
				base_url=settings.ollama_base_url,
				additional_kwargs=options,
			)
		if settings.llm_name == "OpenAI":
			if not settings.openai_api_key:
				return
			additional_kwargs = {
				"seed": options["seed"],
				"temperature": options["temperature"],
				"top_p": options["top_p"],
				"max_tokens": options["num_ctx"],
				"presence_penalty": options["presence_penalty"],
				"frequency_penalty": options["frequency_penalty"],
			}
			Settings.llm = OpenAI(
				model=settings.model_name,
				api_key=settings.openai_api_key,
				additional_kwargs=additional_kwargs,
			)
		elif settings.llm_name == "Gemini":
			if not settings.gemini_api_key:
				return
			os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
			generate_kwargs = {
				"temperature": options["temperature"],
				"top_p": options["top_p"],
				"top_k": options["top_k"],
				"max_output_tokens": options["num_ctx"],
			}
			Settings.llm = Gemini(
				model_name=settings.model_name, generate_kwargs=generate_kwargs
			)
		elif settings.llm_name == "OpenAILike":
			if not settings.openailike_base_url or not settings.openailike_api_key:
				return
			additional_kwargs = {
				"seed": options["seed"],
				"temperature": options["temperature"],
				"top_p": options["top_p"],
				"max_tokens": options["num_ctx"],
				"presence_penalty": options["presence_penalty"],
				"frequency_penalty": options["frequency_penalty"],
				"timeout": 3600,
			}
			Settings.llm = OpenAILike(
				model=settings.model_name,
				api_base=settings.openailike_base_url,
				api_key=settings.openailike_api_key,
				timeout=3600,
				additional_kwargs=additional_kwargs,
			)
			Settings.llm.is_chat_model = True
		else:
			return
		Settings.chunk_size = settings.chunk_size
		Settings.chunk_overlap = settings.chunk_overlap
		Settings.similarity_top_k = settings.similarity_top_k
		Settings.similarity_cutoff = settings.similarity_cutoff
		Settings.context_window = options["num_ctx"]
		# Settings.num_output = options['num_ctx']-256

	def delete(self):
		Ollama_Client(host=settings.ollama_base_url).delete(settings.model_name)

	def create(self, name, modelfile):
		Ollama_Client(host=settings.ollama_base_url).create(
			name, modelfile=modelfile, stream=False
		)

	def modelfile(self):
		return Ollama_Client(host=settings.ollama_base_url).show(settings.model_name)[
			"modelfile"
		]

	def load_index(self, folder):
		if not self.rag:
			self.rag = RAG()
		self.rag.load_index(folder)

	def startRag(self, path, setStatus):
		self.rag = RAG()
		if isinstance(path, list):
			self.rag.loadFolder(path, setStatus)
		elif path.startswith("http"):
			self.rag.loadUrl(path, setStatus)
		else:
			self.rag.loadFolder(path, setStatus)

	def loadDocument(self, paths):
		required_exts = [
			".hwp",
			".pdf",
			".docx",
			".pptx",
			".ppt",
			".pptm",
			".csv",
			".epub",
			".md",
			".mbox",
		]
		documents = SimpleDirectoryReader(
			input_files=paths, required_exts=required_exts
		).load_data()
		texts = [f"```{d.metadata['file_name']}\n{d.text}\n```" for d in documents]
		self.document = "\n---\n".join(texts)

	def setModel(self, name):
		if settings.model_name == name:
			return
		settings.model_name = name

	def setSystem(self, system):
		if system == "":
			return
		system = ChatMessage(role="system", content=system)
		if len(self.messages) == 0 or self.messages[0].role != "system":
			self.messages.insert(0, system)
		elif self.messages[0].role == "system":
			self.messages[0] = system

	def ask(self, content, window):
		self.init_llm()
		self.token_counter.reset_counts()
		if not self.image:
			Settings.callback_manager = CallbackManager([self.token_counter])
		if self.document:
			content += "\n---\n" + self.document
			self.document = None
		message = ChatMessage(role="user", content=content)
		if self.image:
			image = encode_image(self.image)
			document = ImageDocument(image=image, image_path=self.image)
			if settings.llm_name == "Ollama":
				message = ChatMessage(
					role="user", content=content, additional_kwargs={"images": [image]}
				)
			elif settings.llm_name == "Gemini":
				message = ChatMessage(
					role="user",
					content=content,
					additional_kwargs={"images": [document]},
				)
			elif settings.llm_name == "OpenAI" or settings.llm_name == "OpenAILike":
				message = generate_openai_multi_modal_chat_message(
					prompt=content,
					role="user",
					image_documents=[document],
					image_detail="auto",
				)
			else:
				print("Unknown")
		try:
			if content.startswith("/q ") and self.rag:
				if not self.rag.index:
					displayError(Exception("No index found."))
					return
				message.content = message.content[3:]
				self.messages.append(message)
				wx.CallAfter(window.setStatus, "Processing with RAG...")
				response = self.rag.ask(message.content)
			else:
				self.messages.append(message)
				if settings.llm_name == "Gemini" and self.image:
					self.messages = self.messages[-1:]
				wx.CallAfter(window.setStatus, "Processing...")
				response = Settings.llm.stream_chat(self.messages)
			assistant_name = settings.model_name.capitalize()
			if ":" in assistant_name:
				assistant_name = assistant_name[: assistant_name.index(":")]
			wx.CallAfter(window.response.AppendText, assistant_name + ": ")
			self.generate = True
			message = ""
			sentence = ""
			for chunk in response:
				if not sentence:
					wx.CallAfter(window.setStatus, "Typing...")
				data = chunk
				if not isinstance(chunk, str):
					chunk = chunk.delta
				message += chunk
				if settings.speakResponse:
					sentence += chunk
					if re.search(r"[\.\?!\n]\s*$", sentence):
						sentence = sentence.strip()
						if sentence:
							wx.CallAfter(window.speech.speak, sentence)
						sentence = ""
				wx.CallAfter(window.response.AppendText, chunk)
				if not self.generate:
					break
			if sentence and settings.speakResponse:
				wx.CallAfter(window.speech.speak, sentence)
			wx.CallAfter(window.response.AppendText, os.linesep)
			if settings.show_context and content.startswith("/q ") and self.rag:
				nodes = self.rag.response.source_nodes
				for i in range(len(nodes)):
					text = nodes[i].text
					text = re.sub(r"\n+", "\n", text)
					wx.CallAfter(
						window.response.AppendText,
						f"----------{os.linesep}Context {i+1} similarity score: {nodes[i].score:.2f}\n{text}{os.linesep}",
					)
			if (
				isinstance(data, ChatResponse)
				and hasattr(data, "raw")
				and "total_duration" in data.raw
			):
				data = data.raw
				div = 1000000000
				total = data["total_duration"] / div
				load = data["load_duration"] / div
				prompt_count = (
					data["prompt_eval_count"] if "prompt_eval_count" in data else 0
				)
				prompt_duration = data["prompt_eval_duration"] / div
				gen_count = data["eval_count"]
				gen_duration = data["eval_duration"] / div
				stat = f"Total: {total:.2f} seconds, Load: {load:.2f} seconds, Prompt Processing: {prompt_count} tokens ({prompt_count/prompt_duration:.2f} tokens/second), Text Generation: {gen_count} tokens ({gen_count/gen_duration:.2f} tokens/second)"
				wx.CallAfter(window.setStatus, stat)
			elif self.token_counter.total_llm_token_count:
				status_message = f"Embedding Tokens: {self.token_counter.total_embedding_token_count}, LLM Prompt Tokens: {self.token_counter.prompt_llm_token_count}, LLM Completion Tokens: {self.token_counter.completion_llm_token_count}, Total LLM Token Count {self.token_counter.total_llm_token_count}"
				wx.CallAfter(window.setStatus, status_message)
			else:
				wx.CallAfter(window.setStatus, "Finished")
			if self.image:
				self.messages[-1] = ChatMessage(role="user", content=content)
			self.messages.append(ChatMessage(role="assistant", content=message.strip()))
		except Exception as e:
			self.messages.pop()
			displayError(e)
		finally:
			self.generate = False
			self.image = None
			Settings.callback_manager = CallbackManager([])
			wx.CallAfter(window.onStopGeneration)
