from __future__ import annotations

import os
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from .config import Config, Station


# A live multiplex needs headroom for PSI/SI repetition, PES/TS packetisation,
# encoder rate variation and bursty network inputs.  Above 70% of the nominal
# DVB-T payload rate the current Windows pipeline is no longer reliably smooth.
USABLE_MUX_RATIO = 0.70


def dvbt_bitrate(config: Config) -> int:
    bits = {"QPSK": 2, "16-QAM": 4, "64-QAM": 6}[config.constellation]
    fec_num, fec_den = (int(x) for x in config.fec.split("/"))
    gi_num, gi_den = (int(x) for x in config.guard_interval.split("/"))
    carriers, fft = (6048, 8192) if config.transmission_mode == "8K" else (1512, 2048)
    rate = (config.bandwidth_mhz * 1_000_000 * 8 / 7) * (carriers / fft)
    rate *= bits * (fec_num / fec_den) * (188 / 204) * (gi_den / (gi_den + gi_num))
    return round(rate)


def usable_mux_bitrate(config: Config) -> int:
    """Practical payload ceiling for stable live transmission."""
    return round(dvbt_bitrate(config) * USABLE_MUX_RATIO)


def application_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def resource_path(name: str) -> Path:
    return application_root() / name


def user_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HackRF DVB Radio"
    base.mkdir(parents=True, exist_ok=True)
    return base


def find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    candidates = {
        "ffmpeg": list(Path(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages").glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe")),
        "ffprobe": list(Path(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages").glob("Gyan.FFmpeg*/*/bin/ffprobe.exe")),
        "tsp": [Path(r"C:\Program Files\TSDuck\bin\tsp.exe")],
        "tstables": [Path(r"C:\Program Files\TSDuck\bin\tstables.exe")],
        "hackrf_info": [Path.home() / "radioconda" / "Library" / "bin" / "hackrf_info.exe"],
        "radioconda_python": [Path.home() / "radioconda" / "python.exe"],
    }.get(name, [])
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def assign_ids(stations: list[Station]) -> list[Station]:
    active = [s for s in stations if s.enabled]
    used_lcn: set[int] = set()
    used_sid: set[int] = set()
    used_pid: set[int] = set()
    for index, station in enumerate(active):
        station.service_id = station.service_id or (101 + index)
        station.pmt_pid = station.pmt_pid or (0x1000 + index)
        station.audio_pid = station.audio_pid or (0x0101 + index)
        if station.lcn in used_lcn:
            raise ValueError(f"LCN duplicato: {station.lcn}")
        if station.service_id in used_sid:
            raise ValueError(f"Service ID duplicato: {station.service_id}")
        for pid in (station.pmt_pid, station.audio_pid):
            if not 0x20 <= pid <= 0x1FFE or pid in used_pid:
                raise ValueError(f"PID non valido o duplicato: 0x{pid:04X}")
            used_pid.add(pid)
        used_lcn.add(station.lcn)
        used_sid.add(station.service_id)
    if not active:
        raise ValueError("Abilitare almeno una radio")
    return active


def _input_args(station: Station) -> list[str]:
    if station.source.startswith("sine="):
        return ["-re", "-f", "lavfi", "-i", station.source]
    if station.source.lower().startswith(("http://", "https://")):
        return ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-i", station.source]
    source = str(Path(station.source).expanduser())
    return ["-re", "-stream_loop", "-1", "-i", source]


def _auto_encoder(station: Station) -> str:
    if station.source.startswith("sine="):
        return "mp2"
    ffprobe = find_tool("ffprobe")
    if not ffprobe:
        return "mp2"
    source = station.source if station.source.lower().startswith(("http://", "https://")) else str(Path(station.source).expanduser())
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-rw_timeout", "10000000", "-select_streams", "a:0", "-show_entries", "stream=codec_name,sample_rate,channels", "-of", "json", source], capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
        stream = json.loads(result.stdout)["streams"][0]
        compatible = stream.get("codec_name") in ("mp2", "aac") and int(stream.get("sample_rate", 0)) in (32000, 44100, 48000) and int(stream.get("channels", 0)) in (1, 2)
        return "copy" if compatible else "mp2"
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError, json.JSONDecodeError):
        return "mp2"


def make_psi_xml(config: Config, active: list[Station], work: Path) -> tuple[Path, Path, Path]:
    nit_path, sdt_path, pat_path = work / "nit.xml", work / "sdt.xml", work / "pat.xml"
    services = "\n".join(f'          <service service_id="{s.service_id}" service_type="2"/>' for s in active)
    lcns = "\n".join(f'          <service service_id="{s.service_id}" logical_channel_number="{s.lcn}" visible_service="true"/>' for s in active)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<tsduck>
  <NIT version="0" current="true" network_id="{config.network_id}" actual="true">
    <network_name_descriptor network_name="{escape(config.network_name)}"/>
    <transport_stream transport_stream_id="{config.transport_stream_id}" original_network_id="{config.original_network_id}">
      <service_list_descriptor>
{services}
      </service_list_descriptor>
      <terrestrial_delivery_system_descriptor centre_frequency="{int(config.frequency_mhz * 1_000_000)}" bandwidth="{config.bandwidth_mhz}MHz" priority="HP" no_time_slicing="true" no_MPE_FEC="true" constellation="{config.constellation}" hierarchy_information="0" code_rate_HP_stream="{config.fec}" code_rate_LP_stream="{config.fec}" guard_interval="{config.guard_interval}" transmission_mode="{config.transmission_mode.lower()}" other_frequency="false"/>
      <eacem_logical_channel_number_descriptor>
{lcns}
      </eacem_logical_channel_number_descriptor>
    </transport_stream>
  </NIT>
</tsduck>
'''
    nit_path.write_text(xml, encoding="utf-8")
    sdt_services = "\n".join(
        f'''    <service service_id="{s.service_id}" EIT_schedule="false" EIT_present_following="false" running_status="running" CA_mode="false">
      <service_descriptor service_type="2" service_provider_name="{escape(config.provider_name)}" service_name="{escape(s.name)}"/>
    </service>''' for s in active
    )
    sdt_path.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<tsduck>
  <SDT version="0" current="true" transport_stream_id="{config.transport_stream_id}" original_network_id="{config.original_network_id}" actual="true">
{sdt_services}
  </SDT>
</tsduck>
''', encoding="utf-8")
    pat_services = "\n".join(f'    <service service_id="{s.service_id}" program_map_PID="{s.pmt_pid}"/>' for s in active)
    pat_path.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<tsduck>
  <PAT version="0" current="true" transport_stream_id="{config.transport_stream_id}" network_PID="16">
{pat_services}
  </PAT>
</tsduck>
''', encoding="utf-8")
    return nit_path, sdt_path, pat_path


def _ffmpeg_command(config: Config, active: list[Station], destination: str, duration: int | None = None) -> list[str]:
    ffmpeg = find_tool("ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y"]
    for station in active:
        cmd += _input_args(station)
    for i, station in enumerate(active):
        encoder = {"mp2": "mp2", "aac-lc": "aac", "aac-lc (adts)": "aac", "auto": "auto"}.get(station.codec.lower())
        if not encoder:
            raise ValueError(f"Codec non supportato: {station.codec}")
        if encoder == "auto":
            encoder = _auto_encoder(station)
        cmd += ["-map", f"{i}:a:0", f"-c:a:{i}", encoder]
        if encoder != "copy":
            cmd += [f"-b:a:{i}", f"{station.bitrate_kbps}k", f"-ar:a:{i}", str(station.sample_rate), f"-ac:a:{i}", "2" if station.channels == "stereo" else "1"]
        if encoder == "aac":
            cmd += [f"-profile:a:{i}", "aac_low"]
        cmd += ["-streamid", f"{i}:{station.audio_pid}", "-program", f"program_num={station.service_id}:title={station.name}:st={i}"]
    pmt_start = min(s.pmt_pid for s in active)
    if [s.pmt_pid for s in active] != list(range(pmt_start, pmt_start + len(active))):
        raise ValueError("In questa milestone i PMT PID devono essere consecutivi")
    mux_rate = dvbt_bitrate(config)
    estimated_rate = sum(s.bitrate_kbps for s in active) * 1100 + 96_000
    usable_rate = usable_mux_bitrate(config)
    if estimated_rate > usable_rate:
        raise ValueError(
            "Le radio superano il limite stabile del profilo DVB-T "
            f"({estimated_rate / 1e6:.2f} richiesti, {usable_rate / 1e6:.2f} Mbit/s utilizzabili; "
            f"capacità teorica {mux_rate / 1e6:.2f} Mbit/s)"
        )
    cmd += ["-metadata", f"service_provider={config.provider_name}", "-mpegts_transport_stream_id", str(config.transport_stream_id), "-mpegts_original_network_id", str(config.original_network_id), "-mpegts_pmt_start_pid", str(pmt_start), "-mpegts_flags", "+nit+resend_headers", "-muxrate", str(mux_rate), "-pat_period", "0.1", "-sdt_period", "0.5", "-nit_period", "0.5"]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-f", "mpegts", destination]
    return cmd


def build_transport_stream(config: Config, output: Path, log) -> Path:
    tsp = find_tool("tsp")
    if not find_tool("ffmpeg") or not tsp:
        raise RuntimeError("Mancano FFmpeg o TSDuck. Usare 'Installa dipendenze'.")
    active = assign_ids(config.stations)
    work = user_data_dir()
    raw = work / "mux-raw.ts"
    nit, sdt, pat = make_psi_xml(config, active, work)
    cmd = _ffmpeg_command(config, active, str(raw), config.capture_seconds)
    log("Creo il multiplex audio CBR…")
    subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    log("Inserisco NIT e LCN…")
    subprocess.run([tsp, "-I", "file", str(raw),
                    "-P", "inject", str(pat), "--pid", "0", "--replace",
                    "-P", "inject", str(nit), "--pid", "16", "--replace", "--fix-missing-pds",
                    "-P", "inject", str(sdt), "--pid", "17", "--replace",
                    "-O", "file", str(output)], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return output


def tool_status() -> dict[str, bool]:
    return {name: bool(find_tool(name)) for name in ("ffmpeg", "tsp", "hackrf_info", "radioconda_python")}


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TxSession:
    class ControlChannel:
        def __init__(self, port): self.port = port
        def write(self, message):
            with socket.create_connection(("127.0.0.1", self.port), timeout=2) as channel:
                channel.sendall(message.encode("ascii"))
        def flush(self): pass

    def __init__(self, transmitter, processor, producer, control_port):
        self.transmitter, self.processor, self.producer = transmitter, processor, producer
        self.stdin = self.ControlChannel(control_port)

    def poll(self):
        for process in (self.transmitter, self.processor, self.producer):
            code = process.poll()
            if code is not None:
                return code
        return None

    def _stop_helpers(self):
        for process in (self.producer, self.processor):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill()

    def wait(self, timeout=None):
        try:
            return self.transmitter.wait(timeout=timeout)
        finally:
            self._stop_helpers()

    def kill(self):
        if self.transmitter.poll() is None: self.transmitter.kill()
        self._stop_helpers()


def start_transmitter(config: Config, ts_path: Path) -> TxSession:
    py = find_tool("radioconda_python")
    tsp = find_tool("tsp")
    if not py or not tsp or not find_tool("ffmpeg"):
        raise RuntimeError("Mancano Radioconda/GNU Radio, TSDuck o FFmpeg")
    active = assign_ids(config.stations)
    work = user_data_dir()
    nit, sdt, pat = make_psi_xml(config, active, work)
    input_port, control_port = _free_udp_port(), _free_udp_port()
    script = application_root() / "dvb_tx.py"
    flags = subprocess.CREATE_NO_WINDOW
    env = os.environ.copy()
    radio_bin = str(Path(py).parent / "Library" / "bin")
    env["PATH"] = radio_bin + os.pathsep + env.get("PATH", "")
    log_path = user_data_dir() / "transmitter.log"
    log_file = log_path.open("w", encoding="utf-8")
    transmitter = subprocess.Popen(
        [py, str(script), "--pipe-input", "--control-port", str(control_port), "--frequency", str(config.frequency_mhz * 1e6), "--gain", str(config.tx_gain), "--bandwidth", str(config.bandwidth_mhz), "--mode", config.transmission_mode, "--constellation", config.constellation, "--fec", config.fec, "--guard", config.guard_interval] + (["--amp"] if config.amplifier_enabled else []),
        creationflags=flags, env=env, stdin=subprocess.PIPE, stdout=log_file, stderr=subprocess.STDOUT,
    )
    log_file.close()
    processor = subprocess.Popen([tsp, "-I", "ip", str(input_port), "--local-address", "127.0.0.1",
        "-P", "inject", str(pat), "--pid", "0", "--replace",
        "-P", "inject", str(nit), "--pid", "16", "--replace", "--fix-missing-pds",
        "-P", "inject", str(sdt), "--pid", "17", "--replace",
        "-P", "regulate", "--bitrate", str(dvbt_bitrate(config)), "--packet-burst", "7",
        "-O", "file", "-"], creationflags=flags, stdout=transmitter.stdin, stderr=subprocess.DEVNULL)
    transmitter.stdin.close()
    producer = subprocess.Popen(_ffmpeg_command(config, active, f"udp://127.0.0.1:{input_port}?pkt_size=1316"), creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return TxSession(transmitter, processor, producer, control_port)
