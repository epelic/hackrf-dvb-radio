from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Station:
    enabled: bool = True
    name: str = "Radio"
    lcn: int = 701
    source: str = ""
    codec: str = "mp2"
    bitrate_kbps: int = 160
    channels: str = "stereo"
    service_id: int | None = None
    pmt_pid: int | None = None
    audio_pid: int | None = None
    sample_rate: int = 48000


@dataclass
class Config:
    frequency_mhz: float = 474.0
    tx_gain: int = 10
    amplifier_enabled: bool = False
    bandwidth_mhz: int = 8
    transmission_mode: str = "8K"
    constellation: str = "16-QAM"
    fec: str = "1/2"
    guard_interval: str = "1/4"
    capture_seconds: int = 30
    provider_name: str = "HackRF Radio"
    network_name: str = "HackRF DVB-T"
    network_id: int = 1
    transport_stream_id: int = 1
    original_network_id: int = 1
    stations: list[Station] = field(default_factory=lambda: [
        Station(name="Radio 1", lcn=701, source="sine=frequency=1000", bitrate_kbps=160),
        Station(name="Radio 2", lcn=702, source="sine=frequency=1500", bitrate_kbps=160),
    ])

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["stations"] = [Station(**item) for item in raw.get("stations", [])]
        return cls(**raw)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
