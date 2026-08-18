from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
from fractions import Fraction

from gnuradio import blocks, digital, dtv, filter, gr, network, soapy
import pmt


class DvbtTx(gr.top_block):
    def __init__(self, source: str | None, udp_port: int | None, pipe_input: bool, frequency: float, gain: float, bandwidth: int = 8, mode: str = "8K", constellation: str = "16-QAM", fec: str = "1/2", guard: str = "1/4", amplifier: bool = False, validate_only: bool = False):
        super().__init__("HackRF DVB-T Radio", catch_exceptions=True)
        samp_rate = bandwidth * 1_000_000.0 * 8 / 7
        fft_size, payload_carriers, tm = (8192, 6048, dtv.T8k) if mode == "8K" else (2048, 1512, dtv.T2k)
        modulation = {"QPSK": dtv.MOD_QPSK, "16-QAM": dtv.MOD_16QAM, "64-QAM": dtv.MOD_64QAM}[constellation]
        code_rate = {"1/2": dtv.C1_2, "2/3": dtv.C2_3, "3/4": dtv.C3_4, "5/6": dtv.C5_6, "7/8": dtv.C7_8}[fec]
        gi_num, gi_den = (int(x) for x in guard.split("/"))
        guard_code = {"1/32": dtv.GI_1_32, "1/16": dtv.GI_1_16, "1/8": dtv.GI_1_8, "1/4": dtv.GI_1_4}[guard]
        if pipe_input:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            src = blocks.file_descriptor_source(gr.sizeof_char, sys.stdin.fileno(), False)
        elif udp_port is not None:
            src = network.udp_source(gr.sizeof_char, 1, udp_port, 0, 1316, False, False, False)
        else:
            src = blocks.file_source(gr.sizeof_char, source, True, 0, 0); src.set_begin_tag(pmt.PMT_NIL)
        energy = dtv.dvbt_energy_dispersal(1)
        rs = dtv.dvbt_reed_solomon_enc(2, 8, 0x11D, 255, 239, 8, 51, 8)
        conv = dtv.dvbt_convolutional_interleaver(136, 12, 17)
        coder = dtv.dvbt_inner_coder(1, payload_carriers, modulation, dtv.NH, code_rate)
        bit_int = dtv.dvbt_bit_inner_interleaver(payload_carriers, modulation, dtv.NH, tm)
        sym_int = dtv.dvbt_symbol_inner_interleaver(payload_carriers, tm, 1)
        mapper = dtv.dvbt_map(payload_carriers, modulation, dtv.NH, tm, 1)
        refs = dtv.dvbt_reference_signals(gr.sizeof_gr_complex, payload_carriers, fft_size, modulation, dtv.NH, code_rate, code_rate, guard_code, tm, 1, 0)
        cp_len = fft_size * gi_num // gi_den
        prefix = digital.ofdm_cyclic_prefixer(fft_size, fft_size + cp_len, 0, "")
        hackrf_rate = float(8_000_000 if bandwidth == 7 else (bandwidth + 1) * 1_000_000)
        ratio = Fraction(int(hackrf_rate), int(samp_rate)).limit_denominator(256)
        resampler = filter.rational_resampler_ccc(interpolation=ratio.numerator, decimation=ratio.denominator, taps=[], fractional_bw=0.4)
        if validate_only:
            sink = blocks.null_sink(gr.sizeof_gr_complex)
        else:
            sink = soapy.sink("driver=hackrf", "fc32", 1, "", "", [""], [""])
            sink.set_sample_rate(0, hackrf_rate); sink.set_bandwidth(0, bandwidth * 1_000_000); sink.set_antenna(0, "TX/RX"); sink.set_frequency(0, frequency)
            sink.set_gain(0, "VGA", gain)
            # Questa unità HackRF espone il controllo AMP invertito tramite
            # Soapy: 0 abilita fisicamente lo stadio, 14 lo disabilita.
            sink.set_gain(0, "AMP", 0 if amplifier else 14)
        self.connect(src, energy, rs, conv, coder, bit_int, sym_int, mapper, refs, prefix, resampler, sink)


def main():
    parser = argparse.ArgumentParser(); source = parser.add_mutually_exclusive_group(required=True); source.add_argument("--input"); source.add_argument("--udp-port", type=int); source.add_argument("--pipe-input", action="store_true"); parser.add_argument("--control-port", type=int); parser.add_argument("--frequency", type=float, required=True); parser.add_argument("--gain", type=float, default=10); parser.add_argument("--bandwidth", type=int, choices=(5,6,7,8), default=8); parser.add_argument("--mode", choices=("2K","8K"), default="8K"); parser.add_argument("--constellation", choices=("QPSK","16-QAM","64-QAM"), default="16-QAM"); parser.add_argument("--fec", choices=("1/2","2/3","3/4","5/6","7/8"), default="1/2"); parser.add_argument("--guard", choices=("1/32","1/16","1/8","1/4"), default="1/4"); parser.add_argument("--amp", action="store_true"); parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(); tb = DvbtTx(args.input, args.udp_port, args.pipe_input, args.frequency, args.gain, args.bandwidth, args.mode, args.constellation, args.fec, args.guard, args.amp, args.validate_only)
    if args.validate_only:
        print("DVB-T flowgraph OK")
        return
    def stop(*_):
        tb.stop()
        tb.wait()
        raise SystemExit(0)
    signal.signal(signal.SIGINT, stop)
    # Su Windows Popen.terminate usa TerminateProcess. Non intercettare SIGTERM:
    # il driver HackRF deve essere rilasciato anche se lo scheduler GNU Radio è bloccato.
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, stop)
    tb.start()
    # Canale di controllo esplicito per Windows: i segnali di terminazione
    # possono lasciare libhackrf occupata mentre lo scheduler è bloccato.
    if args.control_port:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", args.control_port)); server.listen(1)
            connection, _ = server.accept()
            with connection: connection.recv(32)
    else:
        while True:
            command = sys.stdin.readline()
            if not command or command.strip().upper() == "STOP": break
    tb.stop()
    tb.wait()


if __name__ == "__main__": main()
