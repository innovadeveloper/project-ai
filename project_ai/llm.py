"""
llm.py — Cliente mínimo para Ollama (/api/chat).

Usa solo stdlib (urllib). Lanza LLMError si no puede conectar o parsear.
La respuesta del modelo debe ser JSON:
    {"causa": "...", "confianza": 0.85, "comando": "...", "explicacion": "..."}
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import NodeConfig


# --------------------------------------------------------------------------
# Tipos
# --------------------------------------------------------------------------

class LLMError(Exception):
    """Error al llamar a Ollama o al parsear su respuesta."""


@dataclass
class LLMResponse:
    """Respuesta parseada del modelo."""
    raw: str
    causa: str
    confianza: float    # 0..1
    comando: str | None
    explicacion: str | None

    @classmethod
    def parse(cls, text: str) -> "LLMResponse":
        d = _extract_json(text)
        return cls(
            raw=text,
            causa=str(d.get("causa", "")),
            confianza=float(d.get("confianza", 0.0)),
            comando=d.get("comando") or None,
            explicacion=d.get("explicacion") or None,
        )


# --------------------------------------------------------------------------
# Prompt de sistema
# --------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Eres un asistente de diagnóstico de builds de software.\n"
    "Analiza el fragmento de log de error y devuelve ÚNICAMENTE JSON válido "
    "con este formato exacto:\n"
    '{"causa": "descripción breve", "confianza": 0.85, '
    '"comando": "comando exacto para arreglar o null", '
    '"explicacion": "explicación en 1-2 frases"}\n'
    "Responde SOLO con el JSON, sin texto adicional ni bloques de código."
)


# --------------------------------------------------------------------------
# Llamada principal
# --------------------------------------------------------------------------

def chat(
    user_msg: str,
    *,
    node: NodeConfig,
    system: str = SYSTEM_PROMPT,
) -> LLMResponse:
    """Envía un mensaje a Ollama y devuelve la respuesta parseada.

    Raises:
        LLMError: si no puede conectar, si el servidor devuelve error,
                  o si la respuesta no contiene JSON válido.
    """
    payload = json.dumps({
        "model": node.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        "stream": False,
        "options": {"num_ctx": node.num_ctx},
    }).encode()

    url = node.url.rstrip("/") + "/api/chat"
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=node.timeout) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        raise LLMError(f"No se pudo conectar con Ollama en {node.url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LLMError(f"Respuesta inválida de Ollama: {exc}") from exc

    content = body.get("message", {}).get("content", "")
    try:
        return LLMResponse.parse(content)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise LLMError(f"El modelo no devolvió JSON válido: {content[:120]}") from exc


# --------------------------------------------------------------------------
# Helper de extracción de JSON
# --------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON del texto del modelo.

    Los modelos a veces envuelven la respuesta en ```json ... ```.
    """
    # Quitar bloques markdown si los hay
    clean = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    # Intento directo
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Buscar el primer objeto {...}
    m = re.search(r"\{[^{}]*\}", clean, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No se encontró JSON en la respuesta: {text[:100]}")
