"""Loads `configs/models.yaml`, agent YAMLs, and their JSON Schemas."""
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from string import Template

import yaml
from jsonschema import Draft202012Validator

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


@dataclass(frozen=True)
class ModelSpec:
    """One LLM deployment entry (`SAP_LLM.models.<key>`)."""
    key: str
    provider: str
    model_name: str
    description: str = ""


@dataclass(frozen=True)
class AgentSpec:
    """An LLM agent: prompt template, generation params, and output JSON Schema."""
    name: str
    model: str
    system_prompt: str
    generation: dict
    schema: dict
    validator: Draft202012Validator = field(repr=False, compare=False)

    def render_prompt(self, **variables) -> str:
        """Fills `$placeholders` in the system prompt; unknown placeholders are left as-is."""
        return Template(self.system_prompt).safe_substitute(**variables)


@dataclass(frozen=True)
class Registry:
    """Everything defined in `models.yaml`."""
    models: dict[str, ModelSpec]
    agents: dict[str, AgentSpec]
    chatbot: dict


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_schema(path: Path) -> dict:
    """Reads a JSON Schema file and checks it is a valid draft 2020-12 schema."""
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=1)
def load_registry(config_dir: Path = CONFIG_DIR) -> Registry:
    """Parses `models.yaml` and every agent it registers (cached)."""
    root = _load_yaml(config_dir / "models.yaml")
    sap = root["SAP_LLM"]
    models = {k: ModelSpec(key=k, provider=v["provider"], model_name=v["model_name"],
                           description=v.get("description", ""))
              for k, v in sap["models"].items()}
    agents = {}
    for name, entry in sap["agents"].items():
        if entry["model"] not in models:
            raise ValueError(f"Agent {name!r} references unknown model {entry['model']!r}")
        cfg = _load_yaml(config_dir / entry["config"])
        schema = load_schema(config_dir / entry["schema"])
        agents[name] = AgentSpec(name=name, model=entry["model"], system_prompt=cfg["system_prompt"],
                                 generation=cfg.get("generation", {}), schema=schema,
                                 validator=Draft202012Validator(schema))
    return Registry(models=models, agents=agents, chatbot=root.get("chatbot", {}))
