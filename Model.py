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
import itertools
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.web import (
    MainContentExtractorReader,
    TrafilaturaWebReader,
    BeautifulSoupWebReader,
)
from llama_index.llms.openai_like import OpenAILike
import Tools
import Compact
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


class Client(OpenAILike):
    """OpenAILike, minus the parameter it sends whether or not you asked.

    llama_index puts `temperature` into every request unconditionally: it is a
    constructor field with a default of its own rather than part of
    additional_kwargs, so a preset with the Temperature box left empty still
    sent 0.1. That is wrong twice over. It quietly overrides whatever default
    the server would have used, which is the one thing an empty box should
    mean. And some models reject the parameter outright — `temperature` is
    deprecated for this model — which fails the whole request over a value the
    user never set and cannot see.

    Whether the preset set one is read off additional_kwargs rather than kept
    as a flag of its own, since that dict is what actually goes out: the two
    cannot drift apart.
    """

    def _get_model_kwargs(self, **kwargs):
        options = super()._get_model_kwargs(**kwargs)
        if "temperature" not in self.additional_kwargs:
            options.pop("temperature", None)
        return options


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


def tools_enabled():
    """Whether the model is allowed to call tools.

    One switch for the whole app, on the Chat menu, rather than a preset field:
    it is a decision about what you are doing right now, not about which server
    you are talking to, and it wants to be one keystroke away when you change
    your mind mid-chat.
    """
    return bool(settings.tools)


def field(obj, name, default=None):
    """Read name off an object or a dict, whichever the server library gave us."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def plain(value):
    """A pydantic model as the dict it was parsed from, or the value unchanged."""
    dump = getattr(value, "model_dump", None)
    return dump() if callable(dump) else value


def extra_content(call):
    """The vendor fields hung off one streamed tool call fragment, if any.

    Gemini's thinking models sign every function call and its OpenAI-compatible
    endpoint carries the signature as `extra_content.google.thought_signature`.
    The name is not in the OpenAI schema, so the openai library parses it into
    the model's extras rather than a field; both places are checked because a
    server that answers us with plain dicts has it as a key.
    """
    if isinstance(call, dict):
        return call.get("extra_content")
    found = getattr(call, "extra_content", None)
    if found is None:
        found = (getattr(call, "model_extra", None) or {}).get("extra_content")
    return plain(found)


def collect_extras(chunk, extras):
    """Remember the vendor fields on this chunk's tool call fragments, by index.

    Gemini refuses the next request outright if a function call is sent back
    without its thought signature — 400, "Function call is missing a
    thought_signature" — so a signature lost here kills every turn in which the
    model calls a tool. It is lost by default: `update_tool_calls()` merges the
    streamed fragments by copying the fields it knows about into the first
    fragment's object, and the signature is not one of them. So we read the raw
    chunks ourselves. Keyed by the call's own index rather than by arrival,
    since a fragment can be for any call in progress and the field can be on
    any fragment of one.
    """
    raw = getattr(chunk, "raw", None)
    choices = getattr(raw, "choices", None)
    if choices is None and isinstance(raw, dict):
        choices = raw.get("choices")
    if not choices:
        return
    delta = field(choices[0], "delta")
    for i, call in enumerate(field(delta, "tool_calls") or []):
        found = extra_content(call)
        if found:
            index = field(call, "index")
            extras[index if index is not None else i] = found


def tool_calls_of(chunk, extras=None):
    """Tool calls accumulated on the last streamed chunk, as OpenAI dicts.

    llama_index merges the streamed tool call fragments for us, so the final
    chunk carries the whole list in additional_kwargs. What it does not carry
    is anything outside the OpenAI schema, which collect_extras() saved.
    """
    message = getattr(chunk, "message", None)
    raw = field(getattr(message, "additional_kwargs", {}) or {}, "tool_calls") or []
    calls = []
    for i, call in enumerate(raw):
        function = field(call, "function") or {}
        name = field(function, "name") or ""
        if not name:
            continue
        index = field(call, "index")
        made = {
            "id": field(call, "id") or f"call_{i}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": field(function, "arguments") or "",
            },
        }
        found = (extras or {}).get(index if index is not None else i) or extra_content(
            call
        )
        if found:
            made["extra_content"] = found
        calls.append(made)
    return calls


def transcript_lines(message, name):
    """How one stored message reads in the transcript, tool rounds included."""
    content = (message.content or "").strip()
    if message.role == "tool":
        return [f"Result: {trim(content)}"]
    if message.additional_kwargs.get("background"):
        return [f"Background: {content}"]
    if message.role != "assistant":
        return [f"You: {content}"]
    lines = [f"{name}: {content}"] if content else []
    for call in message.additional_kwargs.get("tool_calls") or []:
        function = field(call, "function") or {}
        described = Tools.describe(
            field(function, "name") or "", field(function, "arguments") or ""
        )
        lines.append(f"Tool: {trim(described)}")
    return lines


# How many of your messages back tool calls and their results are still sent.
# 1 means the turn in progress only.
KEEP_TOOL_TURNS = 1


def with_environment(messages):
    """Add what the machine looks like, when the model can act on the machine.

    A system message of its own, after the preset's, rather than part of it: the
    preset's prompt is yours to write and this is not, and it has to be built
    fresh every request since the working directory and the date both move while
    the app is open. With tools off none of it means anything, so it is left out.
    """
    if not tools_enabled():
        return messages
    at = 0
    while at < len(messages) and messages[at].role == "system":
        at += 1
    return (
        list(messages[:at])
        + [ChatMessage(role="system", content=Tools.environment())]
        + list(messages[at:])
    )


def outgoing(messages, summary="", summary_at=0, env=True):
    """What the server actually sees: a summary of old turns, recent tool rounds.

    Anything before summary_at is replaced by the summary, which stands in for it
    as a message from you, since a conversation the model is told it wrote itself
    invites it to repeat what it says there.

    Every call and its result would otherwise be resent on every later request,
    and a session that runs a few chatty commands ends up spending most of its
    context replaying output nobody needs any more. Older rounds keep whatever
    the assistant said around them and lose the calls, both the call and its
    result together, since a call the server cannot match to a result makes the
    whole history unusable.

    env is off for the summary request, which strips the tool list for the same
    reason: a model still being told how to run commands writes commands rather
    than prose.
    """
    if summary:
        cut = min(summary_at, len(messages))
        messages = (
            [m for m in messages[:cut] if m.role == "system"]
            + [
                ChatMessage(
                    role="user", content=summary, additional_kwargs={"summary": True}
                )
            ]
            + list(messages[cut:])
        )
    starts = [i for i, m in enumerate(messages) if m.role == "user"]
    if len(starts) <= KEEP_TOOL_TURNS:
        return with_environment(messages) if env else messages
    cut = starts[-KEEP_TOOL_TURNS]
    kept = []
    for i, message in enumerate(messages):
        if i >= cut:
            kept.append(message)
            continue
        if message.role == "tool":
            continue
        if message.additional_kwargs.get("tool_calls"):
            if not (message.content or "").strip():
                continue
            message = ChatMessage(role=message.role, content=message.content)
        kept.append(message)
    return with_environment(kept) if env else kept


def finish_reason(chunk):
    """Why the server stopped, from a streamed chunk, or "" if it did not say.

    Only the raw chunk carries it, and only one chunk in the stream has it: with
    stream_options the last chunk is the usage one and its choices list is empty.
    """
    raw = getattr(chunk, "raw", None)
    choices = getattr(raw, "choices", None)
    if choices is None and isinstance(raw, dict):
        choices = raw.get("choices")
    if not choices:
        return ""
    first = choices[0]
    reason = (
        first.get("finish_reason")
        if isinstance(first, dict)
        else getattr(first, "finish_reason", None)
    )
    return reason or ""


def max_output():
    """The reply length this preset asked for, or 0 if it did not ask."""
    try:
        return int(get_parameters().get("max_tokens") or 0)
    except (TypeError, ValueError):
        return 0


def halfway(messages, start):
    """A message boundary about midway between start and the end, or None.

    The overflow path cannot summarize everything at once: that request would
    carry the same history the server just refused. Halving it is the cheapest
    thing that might fit. The cut lands on one of your messages, so a tool call
    is never separated from its result.
    """
    starts = [i for i, m in enumerate(messages) if m.role == "user" and i > start]
    # One message left to cut at means the cut would land in front of it and
    # summarize nothing, so the retry would send the same request again.
    if len(starts) < 2:
        return None
    return starts[len(starts) // 2]


def trim(text, limit=200):
    """One line, at most limit characters: what the transcript shows for tools."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text[:limit] + "..." if len(text) > limit else text


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
        # What everything before summary_at was compacted into, and how many
        # tokens the last exchange took, which is what decides the next one.
        self.summary = ""
        self.summary_at = 0
        self.used = 0
        self.prompt_used = 0
        self.output_used = 0
        self.stop = ""
        self.generate = False
        self.image = None
        self.documentURL = None
        self.document = None
        self.rag = None
        self.token_counter = TokenCountingHandler(
            tokenizer=tiktoken.encoding_for_model("gpt-3.5-turbo").encode
        )
        # So a command in its first seconds, before it goes to the background,
        # is cut short by the same escape that stops the reply.
        Tools.stop_when(lambda: not self.generate)

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
        if tools_enabled():
            additional_kwargs["tools"] = Tools.TOOLS
        Settings.llm = Client(
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

    def to_send(self):
        """The messages this request goes out with, compaction and trimming applied."""
        return outgoing(self.messages, self.summary, self.summary_at)

    def reset_context(self):
        """Drop the summary, for when the messages it stood in for are gone."""
        self.summary = ""
        self.summary_at = 0
        self.used = 0

    def recover(self, window, again):
        """Compact and retry once when a reply came back cut short.

        The truncated reply is dropped from the history the retry goes out with,
        since asking again with half an answer already in place invites the model
        to carry on from it rather than start over. It stays in the transcript,
        because the user has already read it and text that disappears is worse
        than text that is explained.
        """
        if again or not Compact.truncated(
            self.stop, self.output_used, max_output(), self.prompt_used, context_window()
        ):
            return False
        upto = halfway(self.messages, self.summary_at)
        if upto is None:
            return False
        wx.CallAfter(
            window.response.AppendText,
            f"Cut short: that reply ended early, which usually means the "
            f"conversation is too long for the model. Compacting and asking "
            f"again.{os.linesep}",
        )
        mark = self.summary_at
        try:
            self.compact(window, upto)
        except Exception as e:
            wx.CallAfter(window.setStatus, f"Could not compact: {e}")
            return False
        if self.summary_at == mark:
            return False
        del self.messages[-1:]
        return True

    def compact(self, window, upto=None):
        """Replace the conversation up to upto with a summary of it."""
        upto = len(self.messages) if upto is None else upto
        wx.CallAfter(window.setStatus, "Compacting conversation...")
        summary = Compact.summarize(
            Settings.llm,
            outgoing(self.messages[:upto], self.summary, self.summary_at, env=False),
        )
        if not summary:
            return
        self.summary = summary
        self.summary_at = upto
        self.used = 0
        wx.CallAfter(
            window.response.AppendText,
            f"Compacted: the conversation so far was replaced with a summary of it, "
            f"{len(summary)} characters long.{os.linesep}",
        )
        wx.CallAfter(window.setStatus, "Compacted")

    def send(self, window):
        """Ask the server, compacting and trying once more if the history is too big."""
        try:
            return self.start()
        except Exception as e:
            if not Compact.overflowed(e):
                raise
            # The server has just said the conversation no longer fits, so
            # there is nothing left to lose by summarizing it and asking again.
            upto = halfway(self.messages, self.summary_at)
            if upto is None:
                raise
            mark = self.summary_at
            wx.CallAfter(window.setStatus, "Too long for the model, compacting...")
            try:
                self.compact(window, upto)
            except Exception:
                # Report what the server said, not what went wrong trying to
                # work around it.
                raise e
            if self.summary_at == mark:
                raise e
            return self.start()

    def start(self):
        """Send the request and pull the first chunk.

        The library only talks to the server when the stream is first read, so
        without this a request that is refused fails somewhere in the middle of
        showing a reply, too late to do anything about it.
        """
        response = Settings.llm.stream_chat(self.to_send())
        try:
            first = next(response)
        except StopIteration:
            return iter(())
        return itertools.chain([first], response)

    def maybe_compact(self, window):
        """Compact when the exchange that just finished nearly filled the window."""
        if not Compact.needed(self.used, context_window()):
            return
        # One message too big for the window on its own cannot be helped by
        # summarizing what came before it, so do not keep trying.
        if len(self.messages) - self.summary_at < 2:
            return
        try:
            self.compact(window)
        except Exception as e:
            # A failed summary is not a failed answer: the user already has one.
            wx.CallAfter(window.setStatus, f"Could not compact: {e}")

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
        # A background command that ends after its turn is over has no way to
        # speak up on its own, so what it did rides along with the next message.
        note = Tools.notes()
        mark = len(self.messages)
        if note:
            self.messages.append(
                ChatMessage(
                    role="user", content=note, additional_kwargs={"background": True}
                )
            )
            wx.CallAfter(
                window.response.AppendText, f"Background: {note}{os.linesep}"
            )
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
                response = self.send(window)
            self.generate = True
            rounds = 0
            calls = 0
            retried = False
            while True:
                text, tool_calls, data, start_time, ttf, end_time = self.stream(
                    response, window
                )
                if rounds == 0 and settings.show_context and content.startswith("/q "):
                    self.showContext(window)
                self.showStats(window, data, start_time, ttf, end_time)
                self.messages.append(
                    ChatMessage(
                        role="assistant",
                        content=text.strip(),
                        additional_kwargs=(
                            {"tool_calls": tool_calls} if tool_calls else {}
                        ),
                    )
                )
                if not tool_calls:
                    if self.generate and self.recover(window, retried):
                        retried = True
                        response = self.send(window)
                        continue
                    break
                # A dangling tool call the server never sees an answer for makes
                # the whole history unusable, so every call gets a tool message
                # even when we are not going to run it.
                allowed = (
                    self.generate
                    and rounds < Tools.MAX_TOOL_ROUNDS
                    and calls < Tools.MAX_TOOL_CALLS
                )
                calls += len(tool_calls)
                for call in tool_calls:
                    self.messages.append(self.runTool(call, window, allowed))
                if not allowed:
                    break
                # Polls only look at work already running, so they do not spend
                # the budget: waiting for a build would otherwise use it all up.
                if any(
                    call["function"]["name"] not in Tools.FREE for call in tool_calls
                ):
                    rounds += 1
                wx.CallAfter(window.setStatus, "Processing...")
                response = self.send(window)
            if self.generate:
                self.maybe_compact(window)
        except Exception as e:
            del self.messages[mark:]
            displayError(e)
        finally:
            self.generate = False
            self.image = None
            self.document = None
            self.documentURL = None
            Settings.callback_manager = CallbackManager([])
            wx.CallAfter(window.onStopGeneration)

    def stream(self, response, window):
        """Consume one streamed response: show it, return its text and tool calls."""
        wx.CallAfter(window.response.AppendText, assistant_name() + ": ")
        start_time = time()
        thinking = False
        message = ""
        sentence = ""
        ttf = 0
        data = None
        extras = {}
        self.stop = ""
        for chunk in response:
            if not ttf:
                ttf = time()
            if not sentence:
                wx.CallAfter(window.setStatus, "Typing...")
            data = chunk
            collect_extras(chunk, extras)
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
            self.stop = finish_reason(chunk) or self.stop
            if not self.generate:
                break
        end_time = time()
        if sentence and settings.speakResponse:
            wx.CallAfter(window.speech.speak, sentence)
        wx.CallAfter(window.response.AppendText, os.linesep)
        return message, tool_calls_of(data, extras), data, start_time, ttf, end_time

    def runTool(self, call, window, allowed):
        """Run one tool call, echo it to the transcript, return its tool message."""
        name = call["function"]["name"]
        arguments = call["function"]["arguments"]
        wx.CallAfter(
            window.response.AppendText,
            f"Tool: {trim(Tools.describe(name, arguments))}{os.linesep}",
        )
        if allowed:
            wx.CallAfter(window.setStatus, f"Running {name}...")
            result = Tools.call(name, arguments)
        elif self.generate:
            result = "Not run: the limit on tool calls in one message was reached."
        else:
            result = "Not run: the user stopped generation."
        wx.CallAfter(window.response.AppendText, f"Result: {trim(result)}{os.linesep}")
        return ChatMessage(
            role="tool",
            content=result,
            additional_kwargs={"tool_call_id": call["id"], "name": name},
        )

    def showContext(self, window):
        """List the chunks RAG retrieved, with their similarity scores."""
        nodes = self.rag.response.source_nodes
        for i in range(len(nodes)):
            text = re.sub(r"\n+", "\n", nodes[i].text)
            wx.CallAfter(
                window.response.AppendText,
                f"----------{os.linesep}Context {i+1} similarity score: {nodes[i].score:.2f}\n{text}{os.linesep}",
            )

    def showStats(self, window, data, start_time, ttf, end_time):
        """Token counts and speeds for the round that just finished."""
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
            self.used = prompt_count + gen_count
            self.prompt_used = prompt_count
            self.output_used = gen_count
            gen_duration = max(end_time - ttf, 1e-6)
            stat = f"Estimated Speed: Total: {total:.2f} seconds, Prompt Processing: {prompt_count} tokens ({prompt_count/prompt_duration:.2f} tokens/second), Text Generation: {gen_count} tokens ({gen_count/gen_duration:.2f} tokens/second)"
            wx.CallAfter(window.setStatus, stat)
        elif self.token_counter.total_llm_token_count:
            self.used = self.token_counter.total_llm_token_count
            self.prompt_used = self.token_counter.prompt_llm_token_count
            self.output_used = self.token_counter.completion_llm_token_count
            status_message = f"Embedding Tokens: {self.token_counter.total_embedding_token_count}, LLM Prompt Tokens: {self.token_counter.prompt_llm_token_count}, LLM Completion Tokens: {self.token_counter.completion_llm_token_count}, Total LLM Token Count {self.token_counter.total_llm_token_count}"
            wx.CallAfter(window.setStatus, status_message)
        else:
            wx.CallAfter(window.setStatus, "Finished")
