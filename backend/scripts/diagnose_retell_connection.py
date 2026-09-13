from __future__ import annotations

import sys
from typing import Any

import httpx

from app.core.config import settings


RETELL_API_BASE_URL = "https://api.retellai.com"


def configured(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def collect_tools(llm: dict[str, Any]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []

    def add_tool(tool: Any, scope: str) -> None:
        if not isinstance(tool, dict):
            return
        tools.append(
            {
                "scope": scope,
                "type": tool.get("type"),
                "name": tool.get("name"),
                "method": tool.get("method"),
                "url_configured": configured(tool.get("url")),
                "headers_configured": bool(tool.get("headers")),
            }
        )

    for tool in llm.get("general_tools") or []:
        add_tool(tool, "general")

    for state in llm.get("states") or []:
        if not isinstance(state, dict):
            continue
        state_name = state.get("name") or "state"
        for tool in state.get("tools") or []:
            add_tool(tool, f"state:{state_name}")

    return tools


def safe_agent_summary(agent: dict[str, Any]) -> dict[str, Any]:
    response_engine = agent.get("response_engine") if isinstance(agent.get("response_engine"), dict) else {}
    return {
        "agent_id": agent.get("agent_id"),
        "agent_name": agent.get("agent_name"),
        "version": agent.get("version"),
        "base_version": agent.get("base_version"),
        "is_published": agent.get("is_published"),
        "voice_id": agent.get("voice_id"),
        "response_engine_type": response_engine.get("type"),
        "llm_id_configured": configured(response_engine.get("llm_id")),
        "webhook_configured": configured(agent.get("webhook_url")),
    }


def safe_llm_summary(llm: dict[str, Any]) -> dict[str, Any]:
    default_dynamic_variables = llm.get("default_dynamic_variables")
    if not isinstance(default_dynamic_variables, dict):
        default_dynamic_variables = {}

    tools = collect_tools(llm)
    custom_tools = [tool for tool in tools if str(tool.get("type") or "").lower() in {"custom", "custom_function"}]

    return {
        "llm_id": llm.get("llm_id"),
        "version": llm.get("version"),
        "is_published": llm.get("is_published"),
        "model": llm.get("model"),
        "s2s_model": llm.get("s2s_model"),
        "tool_call_strict_mode": llm.get("tool_call_strict_mode"),
        "prompt_configured": configured(llm.get("general_prompt")),
        "begin_message_configured": configured(llm.get("begin_message")),
        "states_count": len(llm.get("states") or []),
        "tools": tools,
        "custom_functions": custom_tools,
        "default_dynamic_variable_keys": sorted(default_dynamic_variables.keys()),
    }


def print_result(ok: bool, message: str) -> None:
    prefix = "[OK]" if ok else "[FAILED]"
    print(f"{prefix} {message}")


def main() -> int:
    api_key = settings.retell_api_key
    agent_id = settings.retell_agent_id

    api_key_configured = configured(api_key)
    agent_id_configured = configured(agent_id)
    print_result(api_key_configured, "RETELL_API_KEY configurada" if api_key_configured else "RETELL_API_KEY no configurada")
    print_result(agent_id_configured, "RETELL_AGENT_ID configurado" if agent_id_configured else "RETELL_AGENT_ID no configurado")

    if not api_key_configured or not agent_id_configured:
        print_result(False, "No se intento conexion con Retell porque faltan credenciales")
        print_result(True, "Sin llamadas telefonicas realizadas")
        return 1

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with httpx.Client(base_url=RETELL_API_BASE_URL, timeout=20) as client:
            list_response = client.get("/list-agents", headers=headers, params={"limit": 1, "is_latest": "true"})
            if list_response.status_code == 401:
                print_result(False, "Autenticacion rechazada por Retell (HTTP 401)")
                print_result(True, "Sin llamadas telefonicas realizadas")
                return 1
            if list_response.status_code >= 400:
                print_result(False, f"Conexion con Retell fallo (HTTP {list_response.status_code})")
                print_result(True, "Sin llamadas telefonicas realizadas")
                return 1

            print_result(True, "Conexion con Retell")
            print_result(True, "Autenticacion valida")

            agent_response = client.get(f"/get-agent/{agent_id}", headers=headers)
            if agent_response.status_code == 404:
                print_result(False, "Agent no encontrado en la cuenta autenticada (HTTP 404)")
                print_result(True, "Sin llamadas telefonicas realizadas")
                return 1
            if agent_response.status_code >= 400:
                print_result(False, f"Validacion de Agent ID fallo (HTTP {agent_response.status_code})")
                print_result(True, "Sin llamadas telefonicas realizadas")
                return 1

            agent = agent_response.json()
            print_result(True, "Agent encontrado")
            print_result(True, "Agent ID pertenece a la cuenta autenticada")
            print("Agent seguro:", safe_agent_summary(agent))

            response_engine = agent.get("response_engine") if isinstance(agent.get("response_engine"), dict) else {}
            llm_id = response_engine.get("llm_id")
            if configured(llm_id):
                llm_response = client.get(f"/get-retell-llm/{llm_id}", headers=headers)
                if llm_response.status_code < 400:
                    print_result(True, "Retell LLM consultado")
                    print("LLM seguro:", safe_llm_summary(llm_response.json()))
                else:
                    print_result(False, f"Consulta de Retell LLM fallo (HTTP {llm_response.status_code})")
            else:
                print_result(False, "El agent no tiene llm_id consultable")

            print_result(True, "Sin llamadas telefonicas realizadas")
            return 0
    except httpx.HTTPError as exc:
        print_result(False, f"Conexion con Retell fallo ({exc.__class__.__name__})")
        print_result(True, "Sin llamadas telefonicas realizadas")
        return 1


if __name__ == "__main__":
    sys.exit(main())
