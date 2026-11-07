"""Registrazione vocale guidata ("JARVIS, impara la mia voce, sono Andrea"), senza coinvolgere l'LLM.

Macchina a stati per dispositivo: chiede il nome (se manca), fa ripetere alcune frasi e salva l'embedding medio.
Le risposte sono fisse: sono veloci e non dipendono dal modello.
"""
import re
import time
from dataclasses import dataclass, field

from . import speaker

PHRASES = [
    "il mattino ha l'oro in bocca",
    "domani andremo al mare se il tempo sarà bello",
    "mi piace ascoltare la musica mentre preparo la cena",
    "accendi la luce della cucina e abbassa il volume",
]
MIN_SAMPLE_S = 1.5       # frasi più corte non bastano per un buon embedding
MAX_RETRIES = 2          # tentativi falliti per frase prima di annullare
IDLE_TIMEOUT_S = 25      # oltre questo silenzio la registrazione è abbandonata

INTENT = re.compile(r"\b(impar\w+|registr\w+|memorizz\w+|riconosc\w+|ricord\w+)\b.{0,30}\bvoce\b", re.I)
NAME = re.compile(r"\b(?:mi chiamo|sono|il mio nome (?:è|e'|e))\s+([^\W\d_]{2,20})", re.I)
YES = re.compile(r"(s[iì]|esatto|giusto|corretto|confermo|certo|va bene|ok)", re.I)
NO = re.compile(r"(no|sbagliato|errato|non è|non e)", re.I)
CANCEL = re.compile(r"\b(annulla\w*|lascia stare|basta così|lascia perdere)\b", re.I)


@dataclass
class _State:
    stage: str                      # "name" | "samples"
    name: str = ""
    samples: list = field(default_factory=list)
    fails: int = 0
    touched: float = field(default_factory=time.monotonic)


_states: dict[str, _State] = {}


def _parse_name(text: str, loose: bool = False) -> str | None:
    if m := NAME.search(text):
        return m.group(1).capitalize()
    if loose:   # risposta alla domanda "come ti chiami?": basta il nome da solo
        words = re.findall(r"[^\W\d_]+", text)
        if 1 <= len(words) <= 3:
            return words[-1].capitalize()
    return None


def active(device: str) -> bool:
    st = _states.get(device)
    return bool(st) and time.monotonic() - st.touched <= IDLE_TIMEOUT_S


def _confirm(st: _State) -> tuple[str, bool]:
    st.stage = "confirm"   # il riconoscimento dei nomi propri è il punto debole: meglio chiedere conferma
    return f"Hai detto {st.name}, giusto?", True


def _start_samples(st: _State) -> tuple[str, bool]:
    st.stage = "samples"
    return f"Piacere {st.name}. Ti faccio ripetere {len(PHRASES)} frasi. Prima: {PHRASES[0]}.", True


def handle(device: str, text: str, pcm: bytes, rate: int) -> tuple[str, bool] | None:
    """Restituisce (risposta, follow_up) se la richiesta riguarda la registrazione, altrimenti None."""
    if not speaker.enabled():
        return None
    st = _states.get(device)
    if st and time.monotonic() - st.touched > IDLE_TIMEOUT_S:
        _states.pop(device, None)
        st = None

    if st is None:
        if not INTENT.search(text):
            return None
        st = _states[device] = _State(stage="name")
        st.name = _parse_name(text) or ""
        st.touched = time.monotonic()
        if st.name:
            return _confirm(st)
        return "Certo. Come ti chiami?", True

    st.touched = time.monotonic()
    if CANCEL.search(text):
        _states.pop(device, None)
        return "Va bene, annullo la registrazione.", False

    if st.stage == "name":
        name = _parse_name(text, loose=True)
        if not name:
            return "Non ho capito il nome. Come ti chiami?", True
        st.name = name
        return _confirm(st)

    if st.stage == "confirm":
        if NO.search(text) and not YES.search(text):
            st.stage = "name"
            return "Scusa. Come ti chiami? Dimmi solo il nome.", True
        if YES.search(text):
            return _start_samples(st)
        if name := _parse_name(text, loose=True):   # ha ripetuto il nome invece di rispondere sì/no
            st.name = name
            return _confirm(st)
        return f"Scusa, ho capito {st.name}: è giusto? Rispondi sì o no.", True

    # stage == "samples"
    idx = len(st.samples)
    if speaker.seconds(pcm, rate) < MIN_SAMPLE_S or not text:
        st.fails += 1
        if st.fails > MAX_RETRIES:
            _states.pop(device, None)
            return "Non riesco a sentirti bene, riproviamo più tardi.", False
        return f"Non ti ho sentito bene. Ripeti: {PHRASES[idx]}.", True

    st.fails = 0
    st.samples.append(speaker.embed(pcm, rate))
    if len(st.samples) < len(PHRASES):
        return f"Bene. Ora: {PHRASES[len(st.samples)]}.", True

    _states.pop(device, None)
    speaker.enroll(st.name, st.samples)
    return f"Fatto {st.name}, adesso riconosco la tua voce.", False

