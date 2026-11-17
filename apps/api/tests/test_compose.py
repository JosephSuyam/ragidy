from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "infrastructure/docker/docker-compose.yml"


def test_multi_network_services_set_distinct_priorities() -> None:
    # Compose 2.24.6 sorts equal priorities unstably, then attaches one network (compose#11533).
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    for name, service in services.items():
        networks = service.get("networks", [])
        if len(networks) > 1:
            assert isinstance(networks, dict), (
                f"{name}: use the long networks syntax with priorities"
            )
            priorities = [(config or {}).get("priority", 0) for config in networks.values()]
            assert len(set(priorities)) == len(priorities), (
                f"{name}: network priorities must differ"
            )
