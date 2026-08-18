from __future__ import annotations

import subprocess
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import Config, Station
from .engine import build_transport_stream, dvbt_bitrate, resource_path, start_transmitter, tool_status, usable_mux_bitrate, user_data_dir

APP_VERSION = "0.2.11"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self._apply_dark_theme()
        self.title("HackRF DVB Radio")
        icon = resource_path("assets/app.ico")
        if icon.exists():
            self.iconbitmap(default=str(icon))
        self.geometry("1120x610")
        self.minsize(900, 520)
        self.config_path = user_data_dir() / "config.json"
        self.ts_path = user_data_dir() / "radio-mux.ts"
        self.cfg = Config.load(self.config_path)
        self.tx: subprocess.Popen | None = None
        self.rows = []
        self._build()
        self._load_rows()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _apply_dark_theme(self):
        self.configure(background="#171a1f")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background="#171a1f", foreground="#e7eaf0", fieldbackground="#242932", bordercolor="#3b424e", lightcolor="#3b424e", darkcolor="#111318", troughcolor="#242932", font=("Segoe UI", 9))
        style.configure("TFrame", background="#171a1f")
        style.configure("TLabel", background="#171a1f", foreground="#e7eaf0")
        style.configure("TButton", background="#2c323c", foreground="#f4f6f9", padding=(9, 5), borderwidth=1)
        style.map("TButton", background=[("active", "#3a4350"), ("pressed", "#20252c")])
        style.configure("TEntry", fieldbackground="#242932", foreground="#f4f6f9", insertcolor="#ffffff")
        style.configure("TCombobox", fieldbackground="#242932", foreground="#f4f6f9", arrowcolor="#cbd2dc")
        style.map("TCombobox", fieldbackground=[("readonly", "#242932")], foreground=[("readonly", "#f4f6f9")], selectbackground=[("readonly", "#315d87")], selectforeground=[("readonly", "#ffffff")])
        style.configure("TCheckbutton", background="#171a1f", foreground="#e7eaf0")
        style.map("TCheckbutton", background=[("active", "#171a1f")], foreground=[("active", "#ffffff")])
        style.configure("Treeview", background="#20242b", fieldbackground="#20242b", foreground="#e7eaf0", rowheight=25, bordercolor="#343b46")
        style.map("Treeview", background=[("selected", "#315d87")], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background="#2b313a", foreground="#ffffff", relief="flat", padding=(5, 5))
        style.map("Treeview.Heading", background=[("active", "#39424e")])
        self.option_add("*TCombobox*Listbox.background", "#242932")
        self.option_add("*TCombobox*Listbox.foreground", "#f4f6f9")
        self.option_add("*TCombobox*Listbox.selectBackground", "#315d87")

    def _build(self):
        top = ttk.Frame(self, padding=10); top.pack(fill="x")
        self.freq = tk.StringVar(value=str(self.cfg.frequency_mhz)); self.gain = tk.StringVar(value=str(self.cfg.tx_gain)); self.seconds = tk.StringVar(value=str(self.cfg.capture_seconds)); self.amplifier = tk.BooleanVar(value=self.cfg.amplifier_enabled)
        for label, var, width in (("Frequenza MHz", self.freq, 10), ("Guadagno TX", self.gain, 6), ("Verifica s", self.seconds, 6)):
            ttk.Label(top, text=label).pack(side="left", padx=(0, 4)); ttk.Entry(top, textvariable=var, width=width).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(top, text="Amplificatore RF +14 dB", variable=self.amplifier).pack(side="left", padx=(0, 14))
        rf = ttk.Frame(self, padding=(10, 0, 10, 8)); rf.pack(fill="x")
        self.mux_name = tk.StringVar(value=self.cfg.network_name)
        ttk.Label(rf, text="Nome multiplex").pack(side="left", padx=(0, 4)); ttk.Entry(rf, textvariable=self.mux_name, width=20).pack(side="left", padx=(0, 18))
        self.bandwidth = tk.StringVar(value=str(self.cfg.bandwidth_mhz)); self.mode = tk.StringVar(value=self.cfg.transmission_mode); self.constellation = tk.StringVar(value=self.cfg.constellation); self.fec = tk.StringVar(value=self.cfg.fec); self.guard = tk.StringVar(value=self.cfg.guard_interval)
        choices = (("Banda MHz", self.bandwidth, ("5", "6", "7", "8")), ("Modalità", self.mode, ("2K", "8K")), ("Costellazione", self.constellation, ("QPSK", "16-QAM", "64-QAM")), ("FEC", self.fec, ("1/2", "2/3", "3/4", "5/6", "7/8")), ("Guardia", self.guard, ("1/32", "1/16", "1/8", "1/4")))
        for label, var, values in choices:
            ttk.Label(rf, text=label).pack(side="left", padx=(0, 4)); box = ttk.Combobox(rf, textvariable=var, values=values, state="readonly", width=8); box.pack(side="left", padx=(0, 14)); box.bind("<<ComboboxSelected>>", lambda _e: self.update_capacity())
        cols = ("on", "name", "lcn", "source", "codec", "bitrate", "rate", "mode", "sid", "pmt", "audio")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=15)
        heads = ("ON", "Nome", "LCN", "URL / file", "Codec", "kbps", "kHz", "Modo", "Service ID", "PMT PID", "Audio PID")
        widths = (45, 120, 50, 290, 65, 50, 55, 60, 75, 70, 75)
        for col, head, width in zip(cols, heads, widths): self.tree.heading(col, text=head); self.tree.column(col, width=width, anchor="center" if col != "source" else "w")
        self.tree.pack(fill="both", expand=True, padx=10)
        self.tree.bind("<Double-1>", self.edit_cell)
        buttons = ttk.Frame(self, padding=10); buttons.pack(fill="x")
        ttk.Button(buttons, text="+ Radio", command=self.add_station).pack(side="left")
        ttk.Button(buttons, text="Rimuovi", command=self.remove_station).pack(side="left", padx=5)
        ttk.Button(buttons, text="Salva", command=self.save).pack(side="left", padx=5)
        ttk.Button(buttons, text="Verifica multiplex", command=self.prepare).pack(side="left", padx=(25, 5))
        self.tx_button = ttk.Button(buttons, text="Avvia trasmissione RF", command=self.toggle_tx); self.tx_button.pack(side="left", padx=5)
        ttk.Button(buttons, text="INFO", command=self.show_info).pack(side="right")
        self.status = tk.StringVar(value="Pronto — la trasmissione RF è spenta")
        ttk.Label(self, textvariable=self.status, padding=(10, 3)).pack(fill="x")
        self.capacity = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.capacity, padding=(10, 3), foreground="#69b7ff").pack(fill="x")
        self.capacity_percent = 0.0
        self.capacity_segments = []
        self.capacity_hitboxes = []
        self.capacity_bar = tk.Canvas(self, height=20, highlightthickness=0, background="#303640")
        self.capacity_bar.pack(fill="x", padx=10, pady=(0, 8))
        self.capacity_bar.bind("<Configure>", lambda _e: self._draw_capacity_bar())
        self.capacity_bar.bind("<Motion>", self._capacity_hover)
        self.capacity_bar.bind("<Leave>", lambda _e: self.capacity_detail.set("Passa il mouse sui segmenti per vedere i singoli servizi"))
        self.capacity_detail = tk.StringVar(value="Passa il mouse sui segmenti per vedere i singoli servizi")
        ttk.Label(self, textvariable=self.capacity_detail, padding=(10, 0, 10, 5)).pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.update_capacity())

    def show_info(self):
        window = tk.Toplevel(self)
        window.title("DVB Radio — Info")
        window.configure(background="#171a1f")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()
        icon = resource_path("assets/app.ico")
        if icon.exists():
            window.iconbitmap(default=str(icon))
        logo = resource_path("assets/app.png")
        if logo.exists():
            self._info_logo = tk.PhotoImage(file=str(logo)).subsample(3, 3)
            ttk.Label(window, image=self._info_logo).pack(padx=32, pady=(24, 8))
        ttk.Label(window, text="DVB Radio", font=("Segoe UI", 18, "bold")).pack(padx=32)
        ttk.Label(window, text=f"Version {APP_VERSION}", font=("Segoe UI", 10)).pack(pady=(3, 14))
        ttk.Label(window, text="Copyright © 2026 SatWolf").pack()
        website = tk.Label(window, text="www.freewaves.it", background="#171a1f", foreground="#69b7ff", cursor="hand2", font=("Segoe UI", 10, "underline"))
        website.pack(pady=(5, 18))
        website.bind("<Button-1>", lambda _e: webbrowser.open("https://www.freewaves.it"))
        ttk.Button(window, text="OK", command=window.destroy).pack(pady=(0, 20))
        window.update_idletasks()
        window.geometry(f"+{self.winfo_rootx() + (self.winfo_width() - window.winfo_width()) // 2}+{self.winfo_rooty() + (self.winfo_height() - window.winfo_height()) // 2}")

    def _load_rows(self):
        self.tree.delete(*self.tree.get_children())
        for s in self.cfg.stations:
            rate_label = "44.1" if s.sample_rate == 44100 else str(s.sample_rate // 1000)
            self.tree.insert("", "end", values=("SÌ" if s.enabled else "NO", s.name, s.lcn, s.source, s.codec.upper(), s.bitrate_kbps, rate_label, s.channels, s.service_id or "AUTO", f"0x{s.pmt_pid:X}" if s.pmt_pid else "AUTO", f"0x{s.audio_pid:X}" if s.audio_pid else "AUTO"))
        self.update_capacity()

    def update_capacity(self):
        total = 0
        segments = []
        for item in self.tree.get_children():
            v = self.tree.item(item, "values")
            if v and v[0] == "SÌ":
                bitrate = int(v[5]); total += bitrate; segments.append((str(v[1]), bitrate * 1.10))
        # Margine conservativo del 10% per PES/TS e PSI/SI.
        estimated = int(total * 1.10 + 96)
        preview = Config(bandwidth_mhz=int(self.bandwidth.get()), transmission_mode=self.mode.get(), constellation=self.constellation.get(), fec=self.fec.get(), guard_interval=self.guard.get())
        theoretical = dvbt_bitrate(preview) / 1000
        capacity = usable_mux_bitrate(preview) / 1000
        percent = min(999, estimated * 100 / capacity)
        self.capacity_percent = percent
        self.capacity_segments = segments
        self.capacity.set(
            f"Carico stabile: {estimated / 1000:.2f} / {capacity / 1000:.2f} Mbit/s ({percent:.0f}%)"
            f" · capacità DVB-T teorica {theoretical / 1000:.2f} Mbit/s"
        )
        self._draw_capacity_bar()

    def _draw_capacity_bar(self):
        if not hasattr(self, "capacity_bar"): return
        canvas = self.capacity_bar; width = max(1, canvas.winfo_width()); height = max(1, canvas.winfo_height())
        canvas.delete("all")
        percent = self.capacity_percent
        canvas.create_rectangle(0, 0, width, height, fill="#303640", outline="")
        self.capacity_hitboxes = []
        capacity_kbps = max(1, usable_mux_bitrate(Config(bandwidth_mhz=int(self.bandwidth.get()), transmission_mode=self.mode.get(), constellation=self.constellation.get(), fec=self.fec.get(), guard_interval=self.guard.get())) / 1000)
        x = 0.0
        overhead_width = width * min(96 / capacity_kbps, 1)
        canvas.create_rectangle(x, 0, x + overhead_width, height, fill="#34506f", outline="#ffffff")
        self.capacity_hitboxes.append((x, x + overhead_width, "PSI/SI e overhead", 96.0, 9600 / capacity_kbps))
        x += overhead_width
        palette = ("#2f80c1", "#34a477", "#7659b5", "#d68532", "#2f9cab", "#bf5f7a")
        for index, (name, bitrate) in enumerate(self.capacity_segments):
            segment_width = width * bitrate / capacity_kbps
            x2 = min(width, x + segment_width)
            canvas.create_rectangle(x, 0, x2, height, fill=palette[index % len(palette)], outline="#ffffff")
            if x2 - x >= 55: canvas.create_text((x + x2) / 2, height / 2, text=name[:12], fill="white", font=("Segoe UI", 8))
            self.capacity_hitboxes.append((x, x2, name, bitrate, bitrate * 100 / capacity_kbps))
            x += segment_width
            if x >= width: break
        canvas.create_line(width * 0.75, 0, width * 0.75, height, fill="#ffffff")
        canvas.create_line(width * 0.90, 0, width * 0.90, height, fill="#ffffff")
        outline = "#d64545" if percent >= 90 else ("#e59b25" if percent >= 75 else "#2e9d57")
        canvas.create_rectangle(1, 1, width - 1, height - 1, outline=outline, width=2)

    def _capacity_hover(self, event):
        for x1, x2, name, bitrate, percent in self.capacity_hitboxes:
            if x1 <= event.x <= x2:
                self.capacity_detail.set(f"{name}: {bitrate:.0f} kbit/s stimati · {percent:.1f}% del multiplex")
                return
        self.capacity_detail.set("Spazio libero nel multiplex")

    def _read_rows(self):
        stations = []
        for item in self.tree.get_children():
            v = self.tree.item(item, "values")
            parse = lambda x: None if str(x).upper() == "AUTO" else int(str(x), 0)
            rate = {"32": 32000, "44.1": 44100, "48": 48000}[str(v[6])]
            stations.append(Station(enabled=v[0] == "SÌ", name=v[1], lcn=int(v[2]), source=v[3], codec=v[4].lower(), bitrate_kbps=int(v[5]), channels=v[7], service_id=parse(v[8]), pmt_pid=parse(v[9]), audio_pid=parse(v[10]), sample_rate=rate))
        mux_name = self.mux_name.get().strip()
        if not mux_name: raise ValueError("Il nome multiplex non può essere vuoto")
        self.cfg.stations = stations; self.cfg.network_name = mux_name; self.cfg.frequency_mhz = float(self.freq.get()); self.cfg.tx_gain = int(self.gain.get()); self.cfg.amplifier_enabled = bool(self.amplifier.get()); self.cfg.capture_seconds = int(self.seconds.get()); self.cfg.bandwidth_mhz = int(self.bandwidth.get()); self.cfg.transmission_mode = self.mode.get(); self.cfg.constellation = self.constellation.get(); self.cfg.fec = self.fec.get(); self.cfg.guard_interval = self.guard.get()

    def save(self):
        try: self._read_rows(); self.cfg.save(self.config_path); self.status.set("Configurazione salvata")
        except Exception as exc: messagebox.showerror("Configurazione", str(exc))

    def add_station(self):
        n = len(self.tree.get_children()) + 1
        self.tree.insert("", "end", values=("SÌ", f"Radio {n}", 700+n, "", "MP2", 160, "48", "stereo", "AUTO", "AUTO", "AUTO"))
        self.update_capacity()

    def remove_station(self):
        for item in self.tree.selection(): self.tree.delete(item)
        self.update_capacity()

    def edit_cell(self, event):
        item = self.tree.identify_row(event.y); column = self.tree.identify_column(event.x)
        if not item or not column: return
        index = int(column[1:]) - 1; box = self.tree.bbox(item, column)
        old = self.tree.item(item, "values")[index]
        if index == 0:
            vals = list(self.tree.item(item, "values")); vals[0] = "NO" if old == "SÌ" else "SÌ"; self.tree.item(item, values=vals); self.update_capacity(); return
        if index in (4, 6, 7):
            choices = ("AUTO", "MP2", "AAC-LC (ADTS)") if index == 4 else (("32", "44.1", "48") if index == 6 else ("mono", "stereo"))
            entry = ttk.Combobox(self.tree, values=choices, state="readonly")
            entry.set(old)
        else:
            entry = ttk.Entry(self.tree); entry.insert(0, old)
        entry.place(x=box[0], y=box[1], width=box[2], height=box[3]); entry.focus_set()
        def commit(_=None):
            vals = list(self.tree.item(item, "values")); vals[index] = entry.get(); self.tree.item(item, values=vals); entry.destroy()
            self.update_capacity()
        entry.bind("<Return>", commit); entry.bind("<FocusOut>", commit)
        if isinstance(entry, ttk.Combobox): entry.bind("<<ComboboxSelected>>", commit)

    def prepare(self):
        self.save(); self.status.set("Preparazione in corso…")
        def work():
            try:
                build_transport_stream(self.cfg, self.ts_path, lambda m: self.after(0, self.status.set, m))
                self.after(0, self.status.set, f"Multiplex pronto: {self.ts_path.name}")
            except Exception as exc: self.after(0, lambda: messagebox.showerror("Multiplex", str(exc))); self.after(0, self.status.set, "Preparazione fallita")
        threading.Thread(target=work, daemon=True).start()

    def toggle_tx(self):
        if self.tx and self.tx.poll() is None:
            process = self.tx
            self.tx = None
            try:
                process.stdin.write("STOP\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, AttributeError):
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            self.tx_button.config(text="Avvia trasmissione RF"); self.status.set("Trasmissione RF fermata"); return
        try:
            self._read_rows(); self.tx = start_transmitter(self.cfg, self.ts_path); self.tx_button.config(text="FERMA trasmissione RF"); amp = " · AMP +14 dB" if self.cfg.amplifier_enabled else ""; self.status.set(f"TRASMISSIONE ATTIVA a {self.cfg.frequency_mhz:.3f} MHz{amp}")
            threading.Thread(target=self._watch_tx, args=(self.tx,), daemon=True).start()
        except Exception as exc: messagebox.showerror("Trasmissione", str(exc))

    def _watch_tx(self, process):
        time.sleep(1.5)
        code = process.poll()
        if code is not None and self.tx is process:
            self.tx = None
            log_path = user_data_dir() / "transmitter.log"
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:] if log_path.exists() else ""
            self.after(0, self.tx_button.config, {"text": "Avvia trasmissione RF"})
            self.after(0, self.status.set, "Trasmissione non avviata")
            self.after(0, lambda: messagebox.showerror("Errore HackRF", "Il trasmettitore si è arrestato.\n\n" + detail))

    def close(self):
        if self.tx and self.tx.poll() is None:
            try:
                self.tx.stdin.write("STOP\n")
                self.tx.stdin.flush()
                self.tx.wait(timeout=5)
            except Exception:
                self.tx.kill()
        self.destroy()


def main():
    App().mainloop()
