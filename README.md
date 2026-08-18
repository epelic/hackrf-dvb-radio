# HackRF DVB Radio

<p align="center"><img src="assets/app.png" alt="HackRF DVB Radio logo" width="420"></p>

**English** · [Italiano](README.it.md)

Windows application for creating and transmitting a radio-only DVB-T multiplex with a HackRF One. Each audio source becomes a separate DVB service with its own service name and configurable logical channel number (LCN).

The current tested release is **0.3.1**. Its default RF profile is 474 MHz, 8 MHz, 8K, 16-QAM, FEC 1/2 and guard interval 1/4. The application also supports 5/6/7/8 MHz channels, 2K/8K modes, QPSK/16-QAM/64-QAM, selectable FEC and guard interval, with automatic capacity recalculation. The capacity display separates the theoretical DVB-T bitrate from a 70% stable live-pipeline limit and blocks configurations exceeding that practical ceiling.

## Features

- Dynamic number of radio services.
- HTTP, HTTPS, Icecast, Shoutcast, HLS and local-file inputs through FFmpeg.
- MP2 or AAC-LC (ADTS), configurable bitrate, 32/44.1/48 kHz sampling and mono/stereo.
- `AUTO` mode stream-copies compatible MP2/AAC inputs and transcodes incompatible sources to MP2.
- Automatic or manually overridden Service ID, PMT PID and audio PID.
- PAT, PMT, SDT and NIT generation, including effective EACEM LCN descriptors.
- Configurable multiplex/network name.
- Constant-bitrate MPEG-TS, DVB-T modulation, IQ generation and direct HackRF output.
- Dark interface with a segmented multiplex-capacity display.
- RF amplifier control and 0–47 dB TX VGA control.
- Automatic reconnection for online streams.

The architecture is ready for a future single TV service, but video is intentionally not implemented in this release.

## Quick start

1. Download and run `HackRF-DVB-Radio-Setup-0.2.11.exe` from the GitHub release.
2. Keep an Internet connection available while setup installs FFmpeg, TSDuck and Radioconda (GNU Radio, gr-dtv and SoapyHackRF).
3. Connect the HackRF One and start the application.
4. Double-click station cells to edit the name, LCN, source and identifiers.
5. Connect the RF output through suitable attenuation and press **Avvia trasmissione RF**.

The built-in `sine=frequency=1000` and `sine=frequency=1500` sources allow an immediate two-service test. RF transmission never starts automatically.

## Build on Windows

Install Radioconda and run:

```powershell
.\build_windows.ps1
```

The script builds the application with PyInstaller and creates the Windows installer with Inno Setup. The supplied logo is included in `assets/app.png`; the Windows icon is `assets/app.ico`.

## RF safety and legal notice

Transmit only on frequencies and at power levels permitted by local law. For bench testing, use a shielded cable path and adequate attenuation. Never connect the HackRF output directly to a television or receiver input without an attenuator.
