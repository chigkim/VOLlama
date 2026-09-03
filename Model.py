from Settings import settings, active_preset, context_window
from Parameters import get_parameters
from openai import OpenAI as OpenAI_client
from llama_index.core import Settings
from llama_index.core.base.llms.types import ImageBlock, VideoBlock
from llama_index.core.llms import ChatMessage
import wx
from Utils import displayError
from pathlib import Path
import os
from RAG import RAG
import re
import tiktoken
import tiktoken_ext
from tiktoken_ext import openai_public
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
import base64
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.web import (
    MainContentExtractorReader,
    TrafilaturaWebReader,
    BeautifulSoupWebReader,
)
from llama_index.llms.openai_like import OpenAILike
import requests
from time import time


# Parameters that every OpenAI-compatible endpoint understands. Anything else
# in the schema stays local and is never sent.
OPENAI_PARAMS = [
    "temperature",
    "top_p",
    "presence_penalty",
    "frequency_penalty",
    "seed",
    "stop",
    "reasoning_effort",
]


def fetch_models(base_url, api_key):
    """Model ids an OpenAI-compatible endpoint offers, or [] if it has no list."""
    client = OpenAI_client(base_url=base_url, api_key=api_key or "none")
    return sorted(i.id for i in client.models.list().data if i.id)


def assistant_name():
    """What the assistant is called in the transcript: the active preset name."""
    if settings.active_preset:
        return settings.active_preset
    preset = active_preset()
    return preset["model"] if preset and preset.get("model") else "Assistant"


def encode_image(image_path):
    try:
        if is_image_url(image_path):
            response = requests.get(image_path)
            content = response.content
        else:
            with open(image_path, "rb") as image_file:
                content = image_file.read()
        return base64.b64encode(content).decode("utf-8")
    except:
        return None


def is_image_url(url):
    try:
        response = requests.head(url, allow_redirects=True, timeout=5)
        content_type = response.headers.get("Content-Type", "")
        return content_type.startswith("image/")
    except requests.RequestException:
        return False


class Model:
    def __init__(self):
        self.messages = []
        self.generate = False
        self.image = None
        self.documentURL = None
        self.document = None
        self.rag = None
        self.token_counter = TokenCountingHandler(
            tokenizer=tiktoken.encoding_for_model("gpt-3.5-turbo").encode
        )

    def init_llm(self):
        preset = active_preset()
        if not preset:
            raise Exception(
                "No preset configured. Press control+p to create one."
            )
        if not preset.get("base_url"):
            raise Exception("This preset has no base URL. Press control+p to edit it.")
        if not preset.get("model"):
            raise Exception("This preset has no model. Press control+p to edit it.")
        options = {k: v for k, v in get_parameters().items() if v is not None}
        additional_kwargs = {k: v for k, v in options.items() if k in OPENAI_PARAMS}
        additional_kwargs["stream_options"] = {"include_usage": True}
        Settings.llm = OpenAILike(
            model=preset["model"],
            api_base=preset["base_url"],
            api_key=preset.get("api_key") or "none",
            context_window=context_window(),
            is_chat_model=True,
            timeout=3600,
            max_tokens=options.get("max_tokens"),
            additional_kwargs=additional_kwargs,
        )
        Settings.chunk_size = settings.chunk_size
        Settings.chunk_overlap = settings.chunk_overlap
        Settings.similarity_top_k = settings.similarity_top_k
        Settings.similarity_cutoff = settings.similarity_cutoff
        Settings.context_window = context_window()

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

    def getURL(self, url):
        documents = None
        try:
            documents = MainContentExtractorReader().load_data([url])
            if len(documents) == 0 or documents[0].text.strip() == "":
                raise (Exception("nothing found."))
        except:
            try:
                documents = TrafilaturaWebReader().load_data([url])
                if len(documents) == 0 or documents[0].text.strip() == "":
                    raise (Exception("nothing found."))
            except:
                try:
                    documents = BeautifulSoupWebReader().load_data([url])
                    if len(documents) == 0 or documents[0].text.strip() == "":
                        raise (Exception("nothing found."))
                except Exception as e:
                    displayError(e)

        if documents and documents[0].text.strip():
            return documents[0].text.strip()

    def setSystem(self, system):
        if system == "":
            if len(self.messages) > 0 and self.messages[0].role == "system":
                del self.messages[0]
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
        if self.documentURL:
            if is_image_url(self.documentURL):
                self.image = [self.documentURL]
            else:
                self.document = self.getURL(self.documentURL)
        if self.document:
            content += "\n---\n" + self.document
        message = ChatMessage(role="user", content=content)
        if self.image:
            message = ChatMessage(
                role="user",
                content=content,
            )
            for image in self.image:
                if image[image.rindex(".")+1:] == "mp4":
                    message.blocks.append(VideoBlock(path=image))
                else:
                    image = encode_image(image)
                    message.blocks.append(ImageBlock(image=image))
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
                wx.CallAfter(window.setStatus, "Processing...")
                start_time = time()
                response = Settings.llm.stream_chat(self.messages)
            wx.CallAfter(window.response.AppendText, assistant_name() + ": ")
            self.generate = True
            thinking = False
            message = ""
            sentence = ""
            ttf = 0
            for chunk in response:
                if not ttf:
                    ttf = time()
                if not sentence:
                    wx.CallAfter(window.setStatus, "Typing...")
                data = chunk
                text = ""
                if isinstance(chunk, str):
                    text = chunk
                else:
                    reasoning = ""
                    if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                        reasoning = chunk.additional_kwargs.get("thinking_delta") or ""
                    if reasoning and settings.show_reasoning:
                        if not thinking:
                            text += "Reasoning: "
                            thinking = True
                        text += reasoning
                    delta = getattr(chunk, "delta", None)
                    if delta:
                        if thinking:
                            text += "\n---\nResponse: "
                            thinking = False
                        text += delta
                if text:
                    message += text
                    wx.CallAfter(window.response.AppendText, text)
                    if settings.speakResponse:
                        sentence += text
                        if re.search(r"[\.\?!\n]\s*$", sentence):
                            sentence = sentence.strip()
                            if sentence:
                                wx.CallAfter(window.speech.speak, sentence)
                            sentence = ""
                if not self.generate:
                    break
            end_time = time()
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
                hasattr(data, "raw")
                and hasattr(data.raw, "usage")
                and data.raw.usage is not None
            ):
                usage = data.raw.usage
                total = end_time - start_time
                prompt_count = usage.prompt_tokens
                prompt_duration = max(ttf - start_time, 1e-6)
                gen_count = usage.completion_tokens
                gen_duration = max(end_time - ttf, 1e-6)
                stat = f"Estimated Speed: Total: {total:.2f} seconds, Prompt Processing: {prompt_count} tokens ({prompt_count/prompt_duration:.2f} tokens/second), Text Generation: {gen_count} tokens ({gen_count/gen_duration:.2f} tokens/second)"
                wx.CallAfter(window.setStatus, stat)
            elif self.token_counter.total_llm_token_count:
                status_message = f"Embedding Tokens: {self.token_counter.total_embedding_token_count}, LLM Prompt Tokens: {self.token_counter.prompt_llm_token_count}, LLM Completion Tokens: {self.token_counter.completion_llm_token_count}, Total LLM Token Count {self.token_counter.total_llm_token_count}"
                wx.CallAfter(window.setStatus, status_message)
            else:
                wx.CallAfter(window.setStatus, "Finished")
            self.messages.append(ChatMessage(role="assistant", content=message.strip()))
        except Exception as e:
            self.messages.pop()
            displayError(e)
        finally:
            self.generate = False
            self.image = None
            self.document = None
            self.documentURL = None
            Settings.callback_manager = CallbackManager([])
            wx.CallAfter(window.onStopGeneration)
