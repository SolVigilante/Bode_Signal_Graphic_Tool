#!/usr/bin/env python3
"""
overlay_csv.py — Superpone dos archivos CSV para comparar:
  - Diagramas de Bode (magnitud [dB] y fase [deg] vs frecuencia)
  - Señales de osciloscopio / transitorios (amplitud vs tiempo)

Pensado para archivos que vienen de:
  - Osciloscopios (Tektronix, Rigol, Keysight, etc.) — suelen traer filas de
    metadata antes de los datos, y nombres de columnas variables.
  - LTSpice (File > Export Data as Text) — separado por tabs, con columnas
    tipo "Freq." / "V(nodo)" (a veces como número complejo "(dB,fase)").

Uso típico:
    python overlay_csv.py bode medido.csv simulado.csv \
        --labels "Medición" "LTSpice" --title "Bode - Filtro RLC"

    python overlay_csv.py signal ch1.csv ch2.csv \
        --labels "Entrada" "Salida" --title "Osciloscopio"

Si el autodetect de columnas falla, se puede forzar todo a mano con
--time-col / --volt-col / --freq-col / --mag-col / --phase-col
(nombre o índice de columna).
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# --------------------------------------------------------------------------
# Carga robusta de CSV: detecta delimitador y salta filas de metadata
# --------------------------------------------------------------------------

def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        # fallback: el que más aparezca en la primera línea
        first_line = sample.splitlines()[0] if sample.splitlines() else ","
        counts = {d: first_line.count(d) for d in [",", ";", "\t"]}
        return max(counts, key=counts.get)


def _is_numeric_row(fields):
    ok = 0
    for f in fields:
        f = f.strip()
        if _to_complex_or_float(f) is not None:
            ok += 1
    return ok >= max(1, len(fields) - 1)  # tolera 1 columna no numérica (ej. texto)


def load_csv(path, delimiter=None, skiprows=None):
    """
    Devuelve (header: list[str], rows: list[list[str]])
    Detecta automáticamente el delimitador y descarta líneas de metadata
    previas a la fila de encabezado real (típico de exports de osciloscopio).
    """
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # típico en exports de LTSpice/osciloscopio (° mal codificado en UTF-8)
    lines = [l for l in text.splitlines() if l.strip() != ""]
    if not lines:
        raise ValueError(f"{path} está vacío")

    if delimiter is None:
        delimiter = _sniff_delimiter("\n".join(lines[:5]))

    reader = list(csv.reader(lines, delimiter=delimiter))

    if skiprows is not None:
        header = reader[skiprows]
        data_rows = reader[skiprows + 1:]
        return [h.strip() for h in header], data_rows

    # Autodetección: la fila de encabezado es la última fila NO numérica
    # antes de que empiecen filas numéricas.
    header_idx = 0
    for i, row in enumerate(reader):
        if _is_numeric_row(row):
            header_idx = max(0, i - 1)
            break
    else:
        header_idx = 0

    header = [h.strip() for h in reader[header_idx]]
    data_rows = reader[header_idx + 1:]
    data_rows = [r for r in data_rows if len(r) == len(header) and _is_numeric_row(r)]
    return header, data_rows


# --------------------------------------------------------------------------
# Parsing de valores (soporta números normales y complejos estilo LTSpice)
# --------------------------------------------------------------------------

_complex_re = re.compile(
    r"^\(?\s*(-?[\d.eE+-]+)\s*[A-Za-zÀ-ÿ°Ω%]*\s*,\s*(-?[\d.eE+-]+)\s*[A-Za-zÀ-ÿ°Ω%]*\s*\)?$"
)


def _to_complex_or_float(s):
    s = s.strip()
    if s == "":
        return None
    m = _complex_re.match(s)
    if m:
        try:
            return (float(m.group(1)), float(m.group(2)))  # (mag_dB o real, fase o imag)
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _find_col(header, name_hint_list, index_override=None):
    if index_override is not None:
        try:
            return int(index_override)
        except ValueError:
            index_override_lower = index_override.lower()
            for i, h in enumerate(header):
                if h.lower() == index_override_lower:
                    return i
            raise ValueError(f"No se encontró la columna '{index_override}'")

    lower = [h.lower() for h in header]
    for hint in name_hint_list:
        for i, h in enumerate(lower):
            if hint in h:
                return i
    return None


# --------------------------------------------------------------------------
# Extracción de datasets
# --------------------------------------------------------------------------

def extract_signal(header, rows, time_col=None, volt_col=None):
    ti = _find_col(header, ["time", "tiempo", "x-axis", "sec"], time_col)
    vi = _find_col(header, ["ch1", "ch2", "v(", "volt", "y-axis", "ampl"], volt_col)
    if ti is None:
        ti = 0
    if vi is None:
        vi = 1 if len(header) > 1 else 0

    t, v = [], []
    for r in rows:
        tv = _to_complex_or_float(r[ti])
        vv = _to_complex_or_float(r[vi])
        if isinstance(tv, float) and isinstance(vv, float):
            t.append(tv)
            v.append(vv)
    return np.array(t), np.array(v)


def extract_bode(header, rows, freq_col=None, mag_col=None, phase_col=None, mag_is_db=True):
    fi = _find_col(header, ["freq", "frecuencia", "hz"], freq_col)
    mi = _find_col(header, ["v(", "i(", "db(", "mag", "gain", "amplitud"], mag_col)
    pi = _find_col(header, ["phase", "fase", "deg", "ang"], phase_col)
    if fi is None:
        fi = 0

    freq, mag, phase = [], [], []
    for r in rows:
        fv = _to_complex_or_float(r[fi])
        if not isinstance(fv, float):
            continue

        # Caso LTSpice: una sola columna compleja "(dB, fase)" para V(nodo)
        if mi is not None and pi is None and len(r) > mi:
            val = _to_complex_or_float(r[mi])
            if isinstance(val, tuple):
                freq.append(fv)
                mag.append(val[0])
                phase.append(val[1])
                continue

        mv = _to_complex_or_float(r[mi]) if mi is not None and mi < len(r) else None
        pv = _to_complex_or_float(r[pi]) if pi is not None and pi < len(r) else None

        if isinstance(mv, tuple):  # columna de magnitud también viene compleja
            mv, pv2 = mv
            pv = pv if isinstance(pv, float) else pv2

        if isinstance(mv, float):
            freq.append(fv)
            mag.append(mv if mag_is_db else 20 * np.log10(abs(mv) + 1e-30))
            phase.append(pv if isinstance(pv, float) else np.nan)

    return np.array(freq), np.array(mag), np.array(phase)


# --------------------------------------------------------------------------
# Plots
# --------------------------------------------------------------------------

def plot_signal(datasets, labels, title, style, save):
    plt.style.use("dark_background" if style == "dark" else "default")
    fig, ax = plt.subplots(figsize=(9, 5))
    for (t, v), lbl in zip(datasets, labels):
        ax.plot(t, v, label=lbl, linewidth=1.4)
    ax.set_xlabel("Tiempo [s]")
    ax.set_ylabel("Amplitud [V]")
    ax.set_title(title or "Superposición de señales")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    _finish(fig, save)


def plot_bode(datasets, labels, title, style, save):
    plt.style.use("dark_background" if style == "dark" else "default")
    fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    for (f, m, p), lbl in zip(datasets, labels):
        ax_mag.semilogx(f, m, label=lbl, linewidth=1.4)
        ax_phase.semilogx(f, p, label=lbl, linewidth=1.4)
    ax_mag.set_ylabel("Magnitud [dB]")
    ax_mag.grid(True, which="both", alpha=0.3)
    ax_mag.legend()
    ax_mag.set_title(title or "Diagrama de Bode")

    ax_phase.set_ylabel("Fase [°]")
    ax_phase.set_xlabel("Frecuencia [Hz]")
    ax_phase.grid(True, which="both", alpha=0.3)
    ax_phase.legend()

    fig.tight_layout()
    _finish(fig, save)


def _finish(fig, save):
    if save:
        fig.savefig(save, dpi=150)
        print(f"Guardado: {save}")
    else:
        plt.show()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Superpone dos CSV (Bode o señales de osciloscopio).")
    p.add_argument("mode", choices=["bode", "signal"], help="Tipo de gráfico")
    p.add_argument("file1")
    p.add_argument("file2")
    p.add_argument("--labels", nargs=2, default=None, metavar=("L1", "L2"))
    p.add_argument("--title", default=None)
    p.add_argument("--style", choices=["white", "dark"], default="white")
    p.add_argument("--save", default=None, help="Ruta de salida (png). Si no se pasa, muestra la figura.")
    p.add_argument("--delimiter", default=None, help="Forzar delimitador (',', ';', '\\t')")
    p.add_argument("--skiprows", type=int, default=None, help="Forzar índice de fila de encabezado (0-based)")

    # overrides de columnas (nombre o índice), aplican a ambos archivos
    p.add_argument("--time-col", default=None)
    p.add_argument("--volt-col", default=None)
    p.add_argument("--freq-col", default=None)
    p.add_argument("--mag-col", default=None)
    p.add_argument("--phase-col", default=None)
    p.add_argument("--mag-linear", action="store_true",
                    help="La columna de magnitud viene en escala lineal, no en dB")

    args = p.parse_args()
    labels = args.labels or [Path(args.file1).stem, Path(args.file2).stem]

    datasets = []
    for f in (args.file1, args.file2):
        header, rows = load_csv(f, delimiter=args.delimiter, skiprows=args.skiprows)
        if args.mode == "signal":
            datasets.append(extract_signal(header, rows, args.time_col, args.volt_col))
        else:
            datasets.append(extract_bode(
                header, rows, args.freq_col, args.mag_col, args.phase_col,
                mag_is_db=not args.mag_linear,
            ))

    if args.mode == "signal":
        plot_signal(datasets, labels, args.title, args.style, args.save)
    else:
        plot_bode(datasets, labels, args.title, args.style, args.save)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(0)
    main()