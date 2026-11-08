"""Agente Google ADK con modello configurabile via LiteLLM (default: Ollama Cloud)."""
import os
from contextvars import ContextVar
from datetime import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from . import notify_client, skills

APP_NAME = "jarvis"

# Dispositivo e parlante della richiesta in corso: servono al tool set_reminder per scegliere il destinatario.
_request: ContextVar[dict] = ContextVar("request", default={})
_GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
         "settembre", "ottobre", "novembre", "dicembre"]


def get_current_time() -> str:
    """Data e ora attuali nel fuso orario locale, inserite nel prompt a ogni richiesta."""
    now = datetime.now(ZoneInfo(os.getenv("AGENT_TIMEZONE", "Europe/Rome")))
    return f"{_GIORNI[now.weekday()]} {now.day} {_MESI[now.month - 1]} {now.year}, ore {now.hour}:{now.minute:02d}"


async def set_reminder(text: str, minutes_from_now: int = 0) -> str:
    """Programma un promemoria o un timer per la persona che sta parlando.

    Args:
        text: cosa ricordare, scritto come messaggio da dire ad alta voce (es. "Devi comprare il latte.").
        minutes_from_now: tra quanti minuti ricordarlo. 0 = appena possibile, alla prossima
            interazione con quella persona (o subito sul dispositivo se non e' riconosciuta).
    """
    if not notify_client.enabled():
        return "Il servizio promemoria non è attivo."
    req = _request.get()
    speaker = req.get("speaker")
    target = notify_client.person_target(speaker) if speaker else f"device:{req.get('device', 'unknown')}"
    try:
        await notify_client.create(text.strip()[:500], target, minutes_from_now=minutes_from_now)
    except Exception:
        return "Non sono riuscito a salvare il promemoria."
    return "Promemoria salvato."


def build_agent() -> LlmAgent:
    extra = {}
    if os.getenv("LLM_THINK", "").lower() in ("0", "false", "no"):
        extra["think"] = False   # modelli ragionanti (kimi, gpt-oss...): niente ragionamento nella risposta parlata
    model = LiteLlm(
        model=os.getenv("LLM_MODEL", "ollama_chat/gpt-oss:120b"),
        api_base=os.getenv("LLM_API_BASE", "https://ollama.com"),
        api_key=os.getenv("LLM_API_KEY") or None,
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "160")),   # risposte parlate: brevi
        **extra,
    )
    lang = os.getenv("AGENT_LANGUAGE", "italiano")
    base = (

            "Sei JARVIS, un assistente vocale su uno smart speaker. "
            f"Rispondi sempre in {lang}, in modo breve e naturale (al massimo 2 frasi corte, circa 25 parole in totale): "
            "la risposta verrà letta ad alta voce, quindi niente markdown, elenchi o emoji. "
            "Il testo dell'utente è una trascrizione automatica e può contenere errori: "
            "interpretalo con buon senso e, se è davvero incomprensibile, chiedi di ripetere con una domanda breve. "
            "Fai una domanda SOLO se ti manca un'informazione indispensabile per rispondere; "
            "non chiudere mai con domande di cortesia (\"vuoi altro?\", \"vuoi più dettagli?\"). "
            "Non superare mai 30 parole. "
            "Se un messaggio inizia con [Nome sta parlando], quella è la persona riconosciuta dalla voce: "
            "puoi chiamarla per nome, ogni tanto e senza esagerare, e non ripetere mai il prefisso. "
            "Senza prefisso l'interlocutore è un ospite non identificato."
    )
    return LlmAgent(
        name="jarvis",
        model=model,
        description="Assistente vocale domestico.",
        tools=[set_reminder] + skills.all_tools(),
        instruction=lambda _ctx: f"Adesso è {get_current_time()}. " + base + skills.index_text() + skills.bodies_text() + _memory_text(),
    )


# Memorie dell'utente per la richiesta in corso (niente nello storico della sessione, quindi nessun accumulo).
_memories: ContextVar[list[str]] = ContextVar("memories", default=[])


def _memory_text() -> str:
    mem = _memories.get()
    if not mem:
        return ""
    return ("\nCosa sai di questa persona (usalo solo se pertinente, senza elencarlo né dire che lo ricordi):\n"
            + "\n".join(f"- {m}" for m in mem))


class Assistant:
    def __init__(self) -> None:
        self.sessions = InMemorySessionService()
        self.runner = Runner(agent=build_agent(), app_name=APP_NAME, session_service=self.sessions)
        self._known: set[str] = set()

    async def ask(self, device_id: str, text: str, speaker: str | None = None,
                  memories: list[str] | None = None) -> str:
        """Una conversazione separata per ogni persona riconosciuta (e una per gli ospiti)."""
        _memories.set(memories or [])
        _request.set({"device": device_id, "speaker": speaker})
        await skills.activate(f"{device_id}:{speaker or 'ospite'}", text)
        sid = f"{device_id}:{speaker or 'ospite'}"
        if sid not in self._known:
            await self.sessions.create_session(app_name=APP_NAME, user_id=sid, session_id=sid)
            self._known.add(sid)
        if speaker:
            text = f"[{speaker} sta parlando] {text}"
        msg = types.Content(role="user", parts=[types.Part(text=text)])
        reply = ""
        async for ev in self.runner.run_async(user_id=sid, session_id=sid, new_message=msg):
            if ev.is_final_response() and ev.content and ev.content.parts:
                reply = "".join(p.text or "" for p in ev.content.parts).strip()
        return reply

    def reload_skills(self) -> list[dict]:
        """Rilegge le skill e aggiorna i tool dell'agente; le sessioni in corso restano."""
        skills.load_all()
        self.runner.agent.tools = skills.all_tools()
        return skills.listing()
